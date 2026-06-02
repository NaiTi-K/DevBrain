"""
GitHub Service — fetches repos and builds normalized, enriched skill profiles.
Uses PyGitHub (sync) wrapped in asyncio.to_thread for non-blocking calls.

v2 additions (no new pip dependencies — stdlib only):
  analyze_skill_profile() now returns two additional keys:
    "frameworks"             : dict[str, float]  ← deterministic manifest parsing
    "engineering_practices"  : dict               ← CI/CD, test signal, commit
                                                     quality, Python AST metrics

Cross-file contracts preserved:
  - Class name           : GitHubService      (unchanged)
  - Singleton name       : github_service     (unchanged)
  - Method signatures    : get_user_repos, analyze_skill_profile, get_user_info
  - _COMMIT_COUNT_CAP    : 200                (unchanged)
  - _run static method                        (unchanged)
  - analyze_skill_profile return keys:
      skills, repo_count, top_languages, primary_language  (all unchanged)
"""

import ast
import asyncio
import json
import logging
import re
from datetime import datetime

from github import Github, GithubException

logger = logging.getLogger(__name__)

# Commit count is capped to avoid hitting secondary rate limits.
_COMMIT_COUNT_CAP = 200
# How many repos get manifests / CI / commits / AST deep scan (when many repos exist)
_DEEP_SCAN_COUNT = 5
# When total owned repos ≤ this, deep-scan ALL of them (not just top 5)
_DEEP_SCAN_ALL_IF_AT_MOST = 12


def _deep_scan_limit(repo_count: int) -> int:
    if repo_count <= _DEEP_SCAN_ALL_IF_AT_MOST:
        return repo_count
    return min(_DEEP_SCAN_COUNT, repo_count)


def _repo_importance_score(repo: dict) -> float:
    """
    Rank repos for deep analysis when stars don't differentiate them.

    Signals (in priority order):
      1. Code volume (language bytes + repo size)
      2. Recent activity (pushed_at)
      3. Commit count (capped — avoids codecrafter spam winning)
      4. Stars, description, primary language present
    """
    stars = repo.get("stars", 0)
    commits = min(repo.get("commit_count", 0), _COMMIT_COUNT_CAP)
    size_kb = repo.get("size", 0) or 0
    code_bytes = sum(repo.get("languages", {}).values())
    has_description = bool((repo.get("description") or "").strip())
    has_language = bool(repo.get("language"))

    recency = 0.0
    pushed = repo.get("pushed_at")
    if isinstance(pushed, datetime):
        delta = datetime.utcnow() - pushed.replace(tzinfo=None)
        recency = max(0.0, 365.0 - delta.days)

    score = (
        stars * 50.0
        + min(code_bytes / 400.0, 250.0)       # primary: actual code mass
        + min(size_kb, 8_000) * 0.12           # GitHub size in KB
        + min(commits, 80) * 0.8               # commits help but saturate early
        + recency * 0.6
        + (8.0 if has_description else 0.0)
        + (5.0 if has_language else 0.0)
    )

    # Deprioritize empty shells, hello-world, and tiny challenge repos
    if size_kb < 15 and code_bytes < 800:
        score *= 0.08
    elif size_kb < 50 and code_bytes < 3_000:
        score *= 0.35
    elif code_bytes < 500:
        score *= 0.2

    return round(score, 2)


def _select_deep_scan_repos(
    repos: list[dict], limit: int = _DEEP_SCAN_COUNT
) -> tuple[list[dict], list[dict]]:
    """Return top-N repos for deep scan plus transparent ranking metadata."""
    effective_limit = min(limit, len(repos))
    if effective_limit <= 0:
        return [], []

    rankings: list[dict] = []
    for r in repos:
        score = _repo_importance_score(r)
        code_kb = round(sum(r.get("languages", {}).values()) / 1024, 1)
        pushed = r.get("pushed_at")
        rankings.append({
            "name": r["name"],
            "score": score,
            "stars": r.get("stars", 0),
            "commits": r.get("commit_count", 0),
            "size_kb": r.get("size", 0),
            "code_kb": code_kb,
            "pushed_at": pushed.isoformat() if isinstance(pushed, datetime) else None,
            "language": r.get("language"),
        })

    rankings.sort(key=lambda x: x["score"], reverse=True)
    ranked_names = {x["name"] for x in rankings[:effective_limit]}
    top_repos = [r for r in repos if r["name"] in ranked_names]
    top_repos.sort(key=lambda r: _repo_importance_score(r), reverse=True)
    return top_repos, rankings


def _list_owned_repos(gh: Github, username: str, *, has_token: bool):
    """
    List owned repos for analysis.

    Critical: ``get_user(username).get_repos()`` hits ``/users/{user}/repos`` and
    returns **public repos only**. With a PAT we must use ``/user/repos`` via
    ``get_user().get_repos(affiliation="owner")`` to include private repositories.
    """
    sort_kw = {"sort": "pushed", "direction": "desc"}

    if has_token:
        authed = gh.get_user()
        if authed.login.lower() == username.lower():
            logger.info(
                "Listing repos via authenticated /user/repos for %s (includes private)",
                authed.login,
            )
            return authed.get_repos(affiliation="owner", **sort_kw)

        logger.warning(
            "PAT belongs to %s but analyzing %s — only public repos will be listed. "
            "Use a PAT for the same account or log in as that user.",
            authed.login,
            username,
        )

    return gh.get_user(username).get_repos(type="owner", **sort_kw)


# ═══════════════════════════════════════════════════════════════════════════ #
# Framework mapping tables                                                     #
# Pure data — no I/O, no LLM.  Keys are substrings to match in package names. #
# ═══════════════════════════════════════════════════════════════════════════ #

# npm package name substring → display name
# Score is set to 0.85 for runtime deps, 0.70 for devDependencies only.
_NPM_MAP: dict[str, str] = {
    "react":          "React",
    "next":           "Next.js",
    "vue":            "Vue.js",
    "nuxt":           "Nuxt.js",
    "angular/core":   "Angular",
    "svelte":         "Svelte",
    "express":        "Express",
    "fastify":        "Fastify",
    "nestjs/core":    "NestJS",
    "tailwindcss":    "Tailwind CSS",
    "typescript":     "TypeScript",
    "graphql":        "GraphQL",
    "prisma/client":  "Prisma",
    "jest":           "Jest",
    "vitest":         "Vitest",
    "webpack":        "Webpack",
    "vite":           "Vite",
    "socket.io":      "Socket.IO",
    "mongoose":       "Mongoose",
    "sequelize":      "Sequelize",
    "drizzle-orm":    "Drizzle ORM",
    "redux":          "Redux",
    "zustand":        "Zustand",
    "trpc":           "tRPC",
}

# pip package name (exact, lowercased) → display name
_PIP_MAP: dict[str, str] = {
    "fastapi":              "FastAPI",
    "django":               "Django",
    "flask":                "Flask",
    "starlette":            "Starlette",
    "sqlalchemy":           "SQLAlchemy",
    "pydantic":             "Pydantic",
    "celery":               "Celery",
    "pytest":               "Pytest",
    "numpy":                "NumPy",
    "pandas":               "Pandas",
    "scikit-learn":         "scikit-learn",
    "tensorflow":           "TensorFlow",
    "torch":                "PyTorch",
    "transformers":         "HuggingFace Transformers",
    "langchain":            "LangChain",
    "langgraph":            "LangGraph",
    "redis":                "Redis",
    "asyncpg":              "asyncpg",
    "aiohttp":              "aiohttp",
    "httpx":                "HTTPX",
    "alembic":              "Alembic",
    "chromadb":             "ChromaDB",
    "openai":               "OpenAI SDK",
    "anthropic":            "Anthropic SDK",
    "groq":                 "Groq SDK",
}

# go.mod module-path substring → display name
_GO_MAP: dict[str, str] = {
    "gin-gonic/gin":   "Gin",
    "labstack/echo":   "Echo",
    "gofiber/fiber":   "Fiber",
    "go-gorm/gorm":    "GORM",
    "gorilla/mux":     "Gorilla Mux",
    "grpc/grpc-go":    "gRPC",
}

# Cargo.toml crate name → display name
_CARGO_MAP: dict[str, str] = {
    "actix-web": "Actix-Web",
    "axum":      "Axum",
    "tokio":     "Tokio",
    "serde":     "Serde",
    "sqlx":      "SQLx",
    "diesel":    "Diesel",
    "reqwest":   "Reqwest",
    "tonic":     "Tonic (gRPC)",
}


# ═══════════════════════════════════════════════════════════════════════════ #
# Regex constants                                                              #
# ═══════════════════════════════════════════════════════════════════════════ #

# Conventional Commits spec — feat/fix/docs/… : <description>
_CC_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|chore|build|ci|revert)"
    r"(\(.+\))?!?:\s+\S",
    re.IGNORECASE,
)

# CI/CD file paths / directory names to probe (order: cheapest checks first)
_CICD_PROBES: tuple[str, ...] = (
    ".github/workflows",       # GitHub Actions (directory → returns list, not 404)
    ".travis.yml",
    "Jenkinsfile",
    ".circleci/config.yml",
    "azure-pipelines.yml",
    ".gitlab-ci.yml",
    "bitbucket-pipelines.yml",
)

# Common test-directory names to probe
_TEST_DIR_PROBES: tuple[str, ...] = (
    "tests", "test", "__tests__", "spec", "specs",
)

# Manifest files to fetch per repo (order matters — most informative first)
_MANIFEST_FILES: tuple[str, ...] = (
    "package.json",
    "requirements.txt",
    "Pipfile",
    "pyproject.toml",
    "go.mod",
    "Cargo.toml",
)


# ═══════════════════════════════════════════════════════════════════════════ #
# AST visitor — McCabe Cyclomatic Complexity for Python source files           #
# Runs fully in-process on source text.  Never executes untrusted code.       #
# ═══════════════════════════════════════════════════════════════════════════ #

class _ComplexityVisitor(ast.NodeVisitor):
    """
    Walks a Python AST and accumulates:
      complexity     — McCabe Cyclomatic Complexity (starts at 1, +1 per branch)
      class_count    — number of class definitions
      function_count — number of function / async-function definitions
    """

    def __init__(self) -> None:
        self.complexity: int = 1
        self.class_count: int = 0
        self.function_count: int = 0

    # ── Branch-point visitors (+1 complexity each) ─────────────────────────
    def visit_If(self, node: ast.If) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        # Ternary: `x if cond else y`
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # `a and b and c` → 2 extra paths (len(values) - 1)
        self.complexity += len(node.values) - 1
        self.generic_visit(node)

    # ── Structural count visitors ──────────────────────────────────────────
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_count += 1
        self.generic_visit(node)

    # Reuse same handler for async functions
    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_count += 1
        self.generic_visit(node)


# ═══════════════════════════════════════════════════════════════════════════ #
# Pure framework-extraction functions (no I/O, no LLM)                        #
# ═══════════════════════════════════════════════════════════════════════════ #

def _parse_package_json(content: str) -> dict[str, float]:
    """Deterministically extract framework scores from a package.json string."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return {}

    runtime_deps: set[str] = set(data.get("dependencies", {}))
    dev_deps: set[str] = set(data.get("devDependencies", {}))
    all_pkgs = runtime_deps | dev_deps

    found: dict[str, float] = {}
    for pkg in all_pkgs:
        pkg_lower = pkg.lower()
        for fragment, display in _NPM_MAP.items():
            if fragment in pkg_lower:
                score = 0.85 if pkg in runtime_deps else 0.70
                found[display] = max(found.get(display, 0.0), score)
                break
    return found


def _parse_requirements_txt(content: str) -> dict[str, float]:
    """
    Extract framework scores from requirements.txt or Pipfile.
    Handles common specifier formats:  pkg>=1.0,  pkg==1.0,  pkg = "*"
    """
    found: dict[str, float] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "[", "-")):
            continue
        # Strip everything after version specifier or extras
        pkg_name = re.split(r"[><=!;\[\s]", line)[0].strip().lower().strip("\"'")
        if pkg_name in _PIP_MAP:
            found[_PIP_MAP[pkg_name]] = 0.85
    return found


def _parse_pyproject_toml(content: str) -> dict[str, float]:
    """
    Extract framework scores from pyproject.toml via regex line scan.
    Handles Poetry, PDM, and PEP-621 formats without a toml parser dep.
    """
    found: dict[str, float] = {}
    for line in content.splitlines():
        line_lower = line.lower()
        for pkg, display in _PIP_MAP.items():
            # Word-boundary match to avoid e.g. "langchain" matching "langchain-core"
            if re.search(rf"\b{re.escape(pkg)}\b", line_lower):
                found[display] = 0.85
                break
    return found


def _parse_go_mod(content: str) -> dict[str, float]:
    """Extract framework scores from go.mod by scanning require block lines."""
    found: dict[str, float] = {}
    for line in content.splitlines():
        for fragment, display in _GO_MAP.items():
            if fragment in line.lower():
                found[display] = 0.85
                break
    return found


def _parse_cargo_toml(content: str) -> dict[str, float]:
    """Extract framework scores from Cargo.toml via word-boundary regex scan."""
    found: dict[str, float] = {}
    for line in content.splitlines():
        for crate, display in _CARGO_MAP.items():
            if re.search(rf"\b{re.escape(crate)}\b", line.lower()):
                found[display] = 0.85
                break
    return found


# Dispatch table — keyed by manifest filename
_MANIFEST_PARSERS: dict[str, object] = {
    "package.json":    _parse_package_json,
    "requirements.txt": _parse_requirements_txt,
    "Pipfile":         _parse_requirements_txt,   # same line format
    "pyproject.toml":  _parse_pyproject_toml,
    "go.mod":          _parse_go_mod,
    "Cargo.toml":      _parse_cargo_toml,
}


def _extract_all_frameworks(
    manifests_by_repo: dict[str, dict[str, str]],
) -> dict[str, float]:
    """
    Merge framework scores across all repos.
    A framework seen in multiple repos keeps its highest single-repo score.
    """
    merged: dict[str, float] = {}
    for repo_manifests in manifests_by_repo.values():
        for filename, content in repo_manifests.items():
            parser = _MANIFEST_PARSERS.get(filename)
            if parser is None:
                continue
            for fw, score in parser(content).items():  # type: ignore[call-arg]
                merged[fw] = max(merged.get(fw, 0.0), score)
    return merged


# ═══════════════════════════════════════════════════════════════════════════ #
# Engineering-practice scorers (pure Python, deterministic, no I/O)           #
# ═══════════════════════════════════════════════════════════════════════════ #

def _score_commit_quality(messages: list[str]) -> float:
    """
    Score commit hygiene on [0.0, 1.0].

    60% weight — Conventional Commit ratio  (discipline signal)
    40% weight — Average first-line length   (descriptiveness signal)
      length ≥ 72 chars → 1.0
      length ≤  4 chars → 0.0
      interpolated linearly between
    """
    if not messages:
        return 0.0

    cc_hits = sum(1 for m in messages if _CC_RE.match(m))
    cc_ratio = cc_hits / len(messages)

    avg_len = sum(len(m) for m in messages) / len(messages)
    length_score = max(0.0, min(1.0, (avg_len - 4.0) / (72.0 - 4.0)))

    return round(cc_ratio * 0.60 + length_score * 0.40, 4)


def _ast_metrics_for_sources(sources: list[str]) -> dict:
    """
    Run _ComplexityVisitor over each Python source string.
    Silently skips files that fail to parse (syntax errors, encoding noise).

    Returns:
      avg_complexity  — mean McCabe CC across parsed files
                        (≤5 clean, 6–10 moderate, >10 high-risk)
      class_count     — total class definitions found
      function_count  — total function definitions found
    """
    complexities: list[int] = []
    total_classes = 0
    total_functions = 0

    for src in sources:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        v = _ComplexityVisitor()
        v.visit(tree)
        complexities.append(v.complexity)
        total_classes += v.class_count
        total_functions += v.function_count

    if not complexities:
        return {"avg_complexity": 0.0, "class_count": 0, "function_count": 0}

    return {
        "avg_complexity": round(sum(complexities) / len(complexities), 2),
        "class_count": total_classes,
        "function_count": total_functions,
    }


def _compute_engineering_practices(
    cicd_signals: list[bool],
    test_signals: list[bool],
    commit_messages: list[str],
    python_sources: list[str],
) -> dict:
    """
    Aggregate per-repo boolean signals + commit messages + AST results into
    a single flat dict consumed by the github_analyzer prompt formatter.

    All values are deterministic — no LLM involved.
    """
    has_cicd = any(cicd_signals) if cicd_signals else False
    test_signal = (
        round(sum(test_signals) / len(test_signals), 4)
        if test_signals
        else 0.0
    )
    commit_quality = _score_commit_quality(commit_messages)
    ast_m = _ast_metrics_for_sources(python_sources)

    return {
        "has_cicd": has_cicd,
        "test_signal": test_signal,
        "commit_quality": commit_quality,
        **ast_m,   # avg_complexity, class_count, function_count
    }


def _compute_language_skills(repos: list[dict]) -> dict[str, float]:
    """
    Deterministic language skill scoring — algorithm identical to v1.
    Preserved exactly so downstream agents (roadmap, challenge) are unaffected.

    Score = (bytes / max_bytes) + star_bonus (≤0.10) + commit_bonus (≤0.05)
    Capped at 1.0.
    """
    lang_bytes: dict[str, int] = {}
    lang_star_bonus: dict[str, float] = {}
    lang_commit_bonus: dict[str, float] = {}

    for repo in repos:
        stars = repo["stars"]
        commits = repo["commit_count"]
        for lang, nbytes in repo["languages"].items():
            lang_bytes[lang] = lang_bytes.get(lang, 0) + nbytes
            star_w = min(stars / 100, 1.0) * 0.10
            commit_w = min(commits / _COMMIT_COUNT_CAP, 1.0) * 0.05
            lang_star_bonus[lang] = max(lang_star_bonus.get(lang, 0.0), star_w)
            lang_commit_bonus[lang] = max(lang_commit_bonus.get(lang, 0.0), commit_w)

    if not lang_bytes:
        return {}

    max_bytes = max(lang_bytes.values())
    skills: dict[str, float] = {}
    for lang, nbytes in lang_bytes.items():
        base = nbytes / max_bytes
        bonus = lang_star_bonus.get(lang, 0.0) + lang_commit_bonus.get(lang, 0.0)
        skills[lang] = min(round(base + bonus, 4), 1.0)

    return skills


# ═══════════════════════════════════════════════════════════════════════════ #
# GitHubService                                                                #
# ═══════════════════════════════════════════════════════════════════════════ #

class GitHubService:
    def __init__(self) -> None:
        # No default token; each call receives its own token.
        pass

    # ── Internal helper ────────────────────────────────────────────────────

    @staticmethod
    async def _run(fn, *args, **kwargs):
        """Run a synchronous callable in a thread pool (non-blocking)."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    # ── Public API ─────────────────────────────────────────────────────────

    async def get_user_repos(self, username: str, token: str) -> list[dict]:
        """
        Return all non-forked repos for *username* authenticated with *token*.
        Signature and return shape unchanged from v1.
        """
        def _fetch():
            gh = Github(token, retry=0)
            user = gh.get_user(username)
            repos = []
            for repo in user.get_repos(type="owner"):
                if repo.fork:
                    continue
                try:
                    languages = repo.get_languages()
                except GithubException:
                    languages = {}
                try:
                    topics = repo.get_topics()
                except GithubException:
                    topics = []
                repos.append({
                    "name": repo.name,
                    "language": repo.language,
                    "languages": languages,
                    "stars": repo.stargazers_count,
                    "size": repo.size,
                    "updated_at": (
                        repo.updated_at.isoformat()
                        if isinstance(repo.updated_at, datetime)
                        else str(repo.updated_at)
                    ),
                    "description": repo.description or "",
                    "topics": topics,
                })
            return repos

        return await self._run(_fetch)

    async def analyze_skill_profile(
        self, username: str, token: str | None
    ) -> dict:
        """
        Build a fully enriched, deterministic skill profile from all non-forked repos.

        Return shape (existing keys unchanged; two new keys added):
          {
            "skills"               : dict[str, float],  # 0.0–1.0 per language
            "repo_count"           : int,
            "top_languages"        : list[str],
            "primary_language"     : str | None,
            "frameworks"           : dict[str, float],  # NEW — manifest-parsed
            "engineering_practices": dict,              # NEW — deterministic signals
          }

        Skill thresholds for downstream agents (unchanged):
          < 0.30       → beginner
          0.30 – 0.65  → intermediate
          > 0.65       → advanced

        API-call budget per invocation (worst case, 5 top repos):
          Phase 1 (all repos)    : 1 list call + N lang calls
          Phase 2 per top repo   : ≤6 manifest + ≤8 CI/CD probe + ≤5 test probe
                                   + 1 tree call + ≤5 file fetches  (Python only)
          Total                  : well within 5 000 req/h authenticated limit
        """

        def _fetch() -> dict:
            """Single synchronous function — all GitHub API I/O grouped here."""
            gh = Github(auth_token, retry=0)

            # ── Phase 1: collect basic metadata for every owned repo ───────
            repos: list[dict] = []
            forks_skipped = 0
            private_count = 0
            total_listed = 0

            for repo in _list_owned_repos(gh, username, has_token=bool(auth_token)):
                total_listed += 1
                if repo.fork:
                    forks_skipped += 1
                    continue
                if getattr(repo, "private", False):
                    private_count += 1
                try:
                    languages = repo.get_languages()
                except GithubException:
                    languages = {}

                try:
                    commits_pl = repo.get_commits()
                    commit_count = min(commits_pl.totalCount, _COMMIT_COUNT_CAP)
                except GithubException:
                    commit_count = 0
                    commits_pl = None

                pushed_at = repo.pushed_at if isinstance(repo.pushed_at, datetime) else None

                repos.append({
                    "repo_obj":    repo,
                    "name":        repo.name,
                    "language":    repo.language,
                    "languages":   languages,
                    "stars":       repo.stargazers_count,
                    "size":        repo.size,
                    "description": repo.description or "",
                    "pushed_at":   pushed_at,
                    "commit_count": commit_count,
                    "commits_pl":  commits_pl,
                    "private":     bool(getattr(repo, "private", False)),
                })

            repo_stats = {
                "total_listed": total_listed,
                "forks_skipped": forks_skipped,
                "analyzed_count": len(repos),
                "private_count": private_count,
                "public_count": len(repos) - private_count,
            }
            logger.info(
                "Repo inventory for %s: %s (listed=%d, forks_skipped=%d, private=%d)",
                username,
                repo_stats,
                total_listed,
                forks_skipped,
                private_count,
            )

            if not repos:
                return {
                    "repos": [],
                    "manifests_by_repo": {},
                    "cicd_signals": [],
                    "test_signals": [],
                    "commit_messages": [],
                    "python_sources": [],
                    "repo_highlights": [],
                    "repo_rankings": [],
                    "deep_scanned_names": [],
                    "repo_stats": repo_stats,
                }

            # ── Phase 2: rank and deep-analyse most important repos ────────
            top_repos, repo_rankings = _select_deep_scan_repos(
                repos, _deep_scan_limit(len(repos))
            )
            logger.info(
                "Deep scan selection for %s: %s (deep=%d of %d owned non-fork repos)",
                username,
                [r["name"] for r in top_repos],
                len(top_repos),
                len(repos),
            )

            manifests_by_repo: dict[str, dict[str, str]] = {}
            cicd_signals: list[bool] = []
            test_signals: list[bool] = []
            commit_messages: list[str] = []
            python_sources: list[str] = []

            repo_highlights: list[dict] = []

            for r in top_repos:
                repo = r["repo_obj"]

                # ── 2a. Manifests (one targeted GET per file) ──────────────
                repo_manifests: dict[str, str] = {}
                for mf in _MANIFEST_FILES:
                    try:
                        fc = repo.get_contents(mf)
                        if isinstance(fc, list):
                            fc = fc[0]
                        repo_manifests[mf] = fc.decoded_content.decode(
                            "utf-8", errors="ignore"
                        )[:2000]   # cap at 2 KB — prevents token blowup
                    except Exception:
                        pass
                manifests_by_repo[r["name"]] = repo_manifests

                # ── 2b. CI/CD detection (short-circuits on first hit) ──────
                has_cicd = False
                for probe in _CICD_PROBES:
                    try:
                        repo.get_contents(probe)
                        has_cicd = True
                        break
                    except Exception:
                        pass
                cicd_signals.append(has_cicd)

                # ── 2c. Test-directory detection (short-circuits) ──────────
                has_tests = False
                for td in _TEST_DIR_PROBES:
                    try:
                        repo.get_contents(td)
                        has_tests = True
                        break
                    except Exception:
                        pass
                test_signals.append(has_tests)

                repo_commit_samples: list[str] = []

                # ── 2d. Commit messages (first line, up to 20 per repo) ────
                if r["commits_pl"] is not None:
                    try:
                        for i, c in enumerate(r["commits_pl"]):
                            if i >= 20:
                                break
                            first_line = c.commit.message.split("\n")[0].strip()
                            if first_line:
                                commit_messages.append(first_line)
                                if len(repo_commit_samples) < 5:
                                    repo_commit_samples.append(first_line)
                    except Exception:
                        pass

                repo_fw = _extract_all_frameworks({r["name"]: repo_manifests})
                repo_highlights.append({
                    "name": r["name"],
                    "description": (repo.description or "").strip()[:200],
                    "stars": r["stars"],
                    "primary_language": r["language"] or "Unknown",
                    "has_cicd": has_cicd,
                    "has_tests": has_tests,
                    "frameworks": list(repo_fw.keys())[:8],
                    "sample_commits": repo_commit_samples,
                })

                # ── 2e. Python source fetch for AST ───────────────────────
                # Only run when Python is ≥ 30% of this repo's bytes.
                lang_bytes = r["languages"]
                total_bytes = sum(lang_bytes.values()) or 1
                python_ratio = lang_bytes.get("Python", 0) / total_bytes

                if python_ratio >= 0.30:
                    try:
                        branch = repo.default_branch
                        tree = repo.get_git_tree(branch, recursive=True)

                        py_candidates = [
                            item.path
                            for item in tree.tree
                            if (
                                item.type == "blob"
                                and item.path.endswith(".py")
                                and not item.path.endswith("__init__.py")
                                and "migration" not in item.path.lower()
                                and "test_" not in item.path.lower()
                                and item.size is not None
                                and 200 < item.size < 30_000  # skip empty/huge files
                            )
                        ][:5]  # max 5 files per repo → max 25 AST runs total

                        for py_path in py_candidates:
                            try:
                                fc = repo.get_contents(py_path)
                                if not isinstance(fc, list):
                                    src = fc.decoded_content.decode(
                                        "utf-8", errors="ignore"
                                    )
                                    python_sources.append(src)
                            except Exception:
                                pass
                    except Exception:
                        pass   # git tree walk is best-effort; never fatal

            return {
                "repos":            repos,
                "manifests_by_repo": manifests_by_repo,
                "cicd_signals":     cicd_signals,
                "test_signals":     test_signals,
                "commit_messages":  commit_messages,
                "python_sources":   python_sources,
                "repo_highlights":  repo_highlights,
                "repo_rankings":    repo_rankings,
                "deep_scanned_names": [r["name"] for r in top_repos],
                "repo_stats":       repo_stats,
            }

        # ── Execute all I/O off the event loop ────────────────────────────
        auth_token = (token or "").strip() or None
        if not auth_token:
            logger.warning(
                "analyze_skill_profile(%s): no GitHub token — deep signals "
                "(manifests, CI/CD, commits) may be empty due to API rate limits. "
                "Set GITHUB_PAT or pass a PAT in the analyze request.",
                username,
            )

        raw = await self._run(_fetch)

        repos = raw["repos"]
        repo_count = len(repos)
        repo_highlights = raw.get("repo_highlights", [])
        sample_commits = raw.get("commit_messages", [])[:15]
        repo_rankings = raw.get("repo_rankings", [])
        deep_scanned_names = raw.get("deep_scanned_names", [])
        repo_stats = raw.get("repo_stats", {})

        # ── Empty-account fast path ────────────────────────────────────────
        if not repos:
            return {
                "skills": {},
                "repo_count": 0,
                "top_languages": [],
                "primary_language": None,
                "frameworks": {},
                "engineering_practices": {
                    "has_cicd":       False,
                    "test_signal":    0.0,
                    "commit_quality": 0.0,
                    "avg_complexity": 0.0,
                    "class_count":    0,
                    "function_count": 0,
                },
                "repo_highlights": [],
                "sample_commits": [],
                "repo_rankings": [],
                "deep_scanned_names": [],
                "repo_stats": {},
                "used_github_token": bool(auth_token),
            }

        # ── Pure post-processing (CPU-bound, no I/O, no LLM) ──────────────
        skills = _compute_language_skills(repos)
        frameworks = _extract_all_frameworks(raw["manifests_by_repo"])
        ep = _compute_engineering_practices(
            raw["cicd_signals"],
            raw["test_signals"],
            raw["commit_messages"],
            raw["python_sources"],
        )

        sorted_langs = sorted(skills, key=lambda lang: skills[lang], reverse=True)

        return {
            "skills":                skills,
            "repo_count":            repo_count,
            "top_languages":         sorted_langs[:10],
            "primary_language":      sorted_langs[0] if sorted_langs else None,
            "frameworks":            frameworks,
            "engineering_practices": ep,
            "repo_highlights":       repo_highlights,
            "sample_commits":        sample_commits,
            "repo_rankings":         repo_rankings,
            "deep_scanned_names":    deep_scanned_names,
            "repo_stats":            repo_stats,
            "used_github_token":     bool(auth_token),
        }

    async def get_user_info(self, token: str) -> dict:
        """
        Return basic profile info for the authenticated user.
        Signature and return shape unchanged from v1.
        """
        def _fetch():
            gh = Github(token, retry=0)
            user = gh.get_user()
            return {
                "github_id":    user.id,
                "login":        user.login,
                "name":         user.name or "",
                "avatar_url":   user.avatar_url,
                "bio":          user.bio or "",
                "public_repos": user.public_repos,
            }

        return await self._run(_fetch)


# ═══════════════════════════════════════════════════════════════════════════ #
# Singleton — name and type preserved; imported across the codebase            #
# ═══════════════════════════════════════════════════════════════════════════ #

github_service = GitHubService()
