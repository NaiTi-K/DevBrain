<div align="center">

# 🧠 DevBrain AI

**AI-powered developer growth platform that actually knows your code**

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat&logo=next.js&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2-FF6B6B?style=flat)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=flat&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=flat&logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Sandbox-2496ED?style=flat&logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=flat)

</div>

---

## What is DevBrain?

DevBrain connects to your GitHub, analyzes your repositories, identifies what you're strong at and where you fall short, and then actively helps you improve. It generates coding challenges targeting your weak spots, reviews your code with the depth of a senior engineer, builds a personalized study roadmap, and runs adaptive mock interviews — all powered by a multi-agent AI system that verifies its own output before surfacing it to you.

This is not a ChatGPT wrapper. The agents write solutions, execute them in an isolated sandbox, validate test cases, and only then present the challenge. Code review suggestions are syntax-checked before they reach you. Skill scoring is fully deterministic and reproducible. Everything is personalized to your actual GitHub history.

---

## Features

### GitHub Skill Profiling
DevBrain scans your public repositories — languages, commit patterns, repo complexity, documentation quality, CI/CD presence — and builds a scored skill profile across your entire tech stack. No self-assessment surveys, just data from your actual code.

- Deterministic scoring via `profile_engine` — reproducible results, not LLM-generated scores that drift
- Framework detection from dependency files (22 npm packages, 22 pip packages, and more)
- Cyclomatic complexity analysis via Python AST
- Results cached in Redis (24h TTL) and persisted to PostgreSQL
- Rate limited to 5 analyses per hour per user

### Adaptive Coding Challenges
DevBrain identifies your weakest skill, maps it to a relevant DSA topic, and generates a challenge. Before you see the problem, the agent completes a full self-verification loop:

1. Searches the web (Tavily) for real competitive programming constraints
2. Generates solutions in Python, C++, and Java
3. Runs its own Python solution in a Docker sandbox against its own test cases
4. Auto-aligns expected outputs if there is a format mismatch
5. Retries up to 4 times with error-grounded correction prompts if anything fails

You only see challenges where the reference solution actually passes all test cases. Each challenge includes 3 MCQs covering ML, system design, or language internals, plus AI-generated feedback comparing your approach to the reference solution after submission.

### AI Code Review
Paste your code, select a language, and receive a structured review — line-by-line annotations, Big-O analysis, edge case detection, and concrete improvement suggestions.

The review pipeline:
1. **Pre-analysis** — AST parsing (Python) + linting for style issues and unused imports
2. **LLM review** — structured output with scores, annotations, and improvement suggestions
3. **Reflection loop** — the agent re-reads its own review, runs sandbox checks on each suggested improvement, and tags them `✅ VERIFIED` or `⛔ SYNTAX ERROR`
4. **SSE streaming** — results stream to the frontend in real time

Rate limited to 20 reviews per hour.

### Personalized Roadmap
Based on your GitHub analysis and a target role you select (SDE Intern, Backend, Full Stack, DevOps, ML/AI, and more), DevBrain generates a structured 6-week study plan. Topic selection and ordering are deterministic — driven by your actual skill gaps. The LLM only polishes the prose.

Supports 9+ target roles. Tracks per-week completion as you progress.

### Mock Interviews

**DSA Mode** — Starts at Hard difficulty. Adapts based on your scores: ≥7 moves to harder questions, ≤4 drops to easier ones. 3 rounds per session, followed by a detailed scorecard.

**Resume Mode** — Upload your resume (PDF), and DevBrain asks project-specific behavioral questions derived from what it extracts. 4 rounds, adaptive follow-up depth, scorecard at the end.

Each answer is scored 1–10 with targeted feedback. Sessions are persisted in PostgreSQL so you can resume across browser sessions.

### Resource Finder
Search for learning resources on any topic via a RAG pipeline — ChromaDB semantic search first (all-MiniLM-L6-v2 embeddings, cosine similarity), falling back to Tavily web search. Results are ranked by source quality (official docs > GitHub repos > tutorials > general blogs) and composite relevance score. Ships with 20 curated seed resources.

### Progress Analytics
- Activity heatmap (GitHub-style, last 30 days)
- Skill trend charts (7-day and 30-day deltas against daily snapshots)
- Streak tracking across challenges, reviews, and interviews
- Exam readiness scores per skill
- Weekly digest with deterministic action items

All metrics are computed from live database queries — no stale caches for analytics.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Next.js 14 Frontend                   │
│  Dashboard │ Challenges │ Review │ Interview │ Roadmap   │
└──────────────────────┬──────────────────────────────────┘
                       │ REST + SSE
┌──────────────────────▼──────────────────────────────────┐
│                    FastAPI Backend                        │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │              LangGraph Orchestrator               │   │
│  │                                                   │   │
│  │  ┌──────────┐  ┌───────────┐  ┌───────────────┐  │   │
│  │  │  GitHub  │  │ Challenge │  │  Code Review  │  │   │
│  │  │ Analyzer │  │   Agent   │  │  + Reflector  │  │   │
│  │  └──────────┘  └───────────┘  └───────────────┘  │   │
│  │  ┌──────────┐  ┌───────────┐  ┌───────────────┐  │   │
│  │  │  Roadmap │  │ Interview │  │   Resource    │  │   │
│  │  │  Agent   │  │   Agent   │  │  Agent (RAG)  │  │   │
│  │  └──────────┘  └───────────┘  └───────────────┘  │   │
│  │  ┌──────────┐                                     │   │
│  │  │ Progress │                                     │   │
│  │  │  Agent   │                                     │   │
│  │  └──────────┘                                     │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  ┌──────────┐  ┌─────────┐  ┌──────────┐  ┌─────────┐  │
│  │ Groq API │  │ Tavily  │  │ ChromaDB │  │ Docker  │  │
│  │  (LLM)   │  │(Search) │  │ (Vector) │  │Sandbox  │  │
│  └──────────┘  └─────────┘  └──────────┘  └─────────┘  │
└────────┬──────────────────────────────┬─────────────────┘
         │                              │
    ┌────▼────┐                    ┌────▼────┐
    │PostgreSQL│                   │  Redis  │
    │   16    │                    │    7    │
    └─────────┘                    └─────────┘
```

### How the agents work

The orchestrator classifies incoming intent via keyword matching and routes to the appropriate agent. Most agents follow a linear pattern: gather context → call LLM → return result.

Two agents are more complex:

**Challenge Agent** runs a self-verification loop. After the LLM generates a challenge, the agent executes the reference solution in a Docker sandbox, compares outputs against expected test cases, auto-corrects format mismatches, and retries up to 4 times with error-specific correction prompts before surfacing the problem.

**Code Review Agent** uses a reflection loop. After generating a review, a dedicated reflector node syntax-checks and benchmarks each suggested improvement. Results below a quality threshold loop back for another review pass. Users only see suggestions tagged as verified or explicitly flagged as containing a syntax error.

---

## Tech Stack

### Backend

| Component | Technology | Reason |
|-----------|------------|--------|
| API framework | FastAPI + Uvicorn | Async-native, Pydantic validation, auto-generated docs |
| Agent orchestration | LangGraph 0.2 | State machines with conditional edges and reflection loops |
| LLM | Groq API — Llama 3.3 70B | 10–50x faster inference than OpenAI; falls back to Llama 3.1 8B |
| Database | PostgreSQL 16 + asyncpg | JSONB columns, UUID PKs, async driver |
| Caching + rate limiting | Redis 7 | Sub-millisecond cache reads, atomic INCR + EXPIRE pipelines |
| Vector store | ChromaDB 1.5 | Embedded, no infra overhead, native sentence-transformer support |
| Web search | Tavily | Challenge sourcing and resource fallback |
| ORM | SQLAlchemy 2.0 | Async sessions, typed mapped columns |
| Code sandbox | Docker | Isolated execution for Python, C++ (gcc:13), Java (eclipse-temurin:21) |
| Embeddings | sentence-transformers | all-MiniLM-L6-v2, 384 dimensions, CPU-friendly |
| Resume parsing | PyPDF2 | Text extraction for interview mode |

### Frontend

| Component | Technology | Reason |
|-----------|------------|--------|
| Framework | Next.js 14 (App Router) | SSR, file-based routing, modern React patterns |
| Language | TypeScript + React 18 | Type safety across the full frontend |
| Editor | Monaco Editor | VS Code engine in-browser — syntax highlighting, autocomplete |
| Charts | Recharts | Radar, line, and bar charts with minimal boilerplate |
| Styling | Tailwind CSS 3.4 | Utility-first, co-located with markup |
| Icons | Lucide React | Consistent, lightweight icon set |

### Infrastructure

| Component | Technology |
|-----------|------------|
| Local dev | Docker Compose (PostgreSQL + Redis) |
| CI/CD | GitHub Actions — backend tests, ruff linting, frontend build |
| Code sandbox | Docker — python:3.12-alpine, gcc:13, eclipse-temurin:21-jdk |

---

## Running Locally

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker Desktop
- API keys: Groq, GitHub OAuth app, Tavily

### 1. Clone and configure

```bash
git clone https://github.com/NaiTi-K/DevBrain.git
cd DevBrain
cp backend/.env.example backend/.env
```

Edit `backend/.env`:

```env
DATABASE_URL=postgresql+asyncpg://devbrain_user:devbrain_pass@localhost:5432/devbrain_db
REDIS_URL=redis://localhost:6379/0
XAI_API_KEY=your_groq_api_key
GITHUB_CLIENT_ID=your_github_oauth_client_id
GITHUB_CLIENT_SECRET=your_github_oauth_client_secret
TAVILY_API_KEY=your_tavily_api_key
JWT_SECRET_KEY=pick_something_random_and_long
FRONTEND_URL=http://localhost:3000
```

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

### 2. Start the databases

```bash
docker compose up -d postgres redis
```

### 3. Pull sandbox images

```bash
docker pull python:3.12-alpine
docker pull gcc:13
docker pull eclipse-temurin:21-jdk
```

### 4. Start the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

API docs at [http://localhost:8000/docs](http://localhost:8000/docs).

### 5. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

App at [http://localhost:3000](http://localhost:3000).

### 6. Seed resources (optional)

```bash
curl -X POST http://localhost:8000/resources/seed
```

---

## Project Scale

| Metric | Count |
|--------|-------|
| Backend (Python) | ~15,000 lines across 30+ files |
| Frontend (TypeScript/React) | ~5,000 lines across 15+ files |
| Autonomous AI agents | 8 |
| API endpoints | 24 |
| Database models | 9 |
| Languages supported in sandbox | 3 (Python, C++, Java) |

---

## Contributors

<table>
  <tr>
    <td align="center">
      <a href="https://github.com/NaiTi-K">
        <img src="https://github.com/NaiTi-K.png" width="80px" alt="Naitik Agrawal"/><br/>
        <sub><b>Naitik Agrawal</b></sub>
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/NileshGoyal237">
        <img src="https://github.com/NileshGoyal237.png" width="80px" alt="Nilesh Goyal"/><br/>
        <sub><b>Nilesh Goyal</b></sub>
      </a>
    </td>
  </tr>
</table>

---

<div align="center">
  <sub>Built with purpose. Every feature ships only after the agent verifies it works.</sub>
</div>