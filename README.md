<div align="center">
  <h1>🧠 DevBrain AI</h1>
  <p><strong>AI-powered developer growth platform that actually knows your code</strong></p>

</div>

<br/>

## What's this

DevBrain connects to your GitHub, analyzes your repos, figures out what you're good at (and what you're not), and then helps you get better. It generates coding challenges targeting your weak spots, reviews your code like a senior engineer would, builds you a personalized study roadmap, and runs mock interviews — all backed by multi-agent AI that actually verifies its own output before showing it to you.

Not another chatbot wrapper. The agents write solutions, run them in a sandbox, check if the test cases pass, and only then present the challenge. Code review suggestions get syntax-checked before they reach you. Everything is deterministic where it matters, and AI where it helps.

---

## Features

### GitHub Skill Profiling
Connect your GitHub and DevBrain scans your public repos — languages, commit patterns, repo complexity, documentation quality. It builds a skill profile with scores across your tech stack. No self-assessment surveys, just data from your actual code.

- Deterministic scoring via `profile_engine` (not just LLM vibes)
- Caches results in Redis, persists to PostgreSQL
- Rate limited to 5 analyses/hour per user

### Adaptive Coding Challenges
DevBrain finds your weakest skill, maps it to a relevant DSA topic, and generates a challenge. But here's the thing — before you see the problem, the agent:

1. Searches the web (Tavily) for real competitive programming constraints
2. Generates solutions in Python, C++, and Java
3. Runs its own Python solution in a sandbox against its own test cases
4. Auto-aligns expected outputs if they're off
5. Retries up to 4 times if anything fails

You only see verified challenges. Each one comes with 3 MCQs covering ML, system design, or language internals. After you submit, you get AI-generated feedback comparing your approach to the reference solution.

### AI Code Review
Paste your code, pick a language, and get a structured review — not just "looks good" but actual line-by-line annotations, Big-O analysis, edge case detection, and improvement suggestions.

The review pipeline is:
1. **Pre-analysis**: AST parsing (Python) + linting
2. **LLM review**: Structured output with scores and annotations
3. **Reflection loop**: The agent re-reads its own review, runs sandbox checks on suggested improvements, and tags them ✅ VERIFIED or ⛔ SYNTAX ERROR
4. **SSE streaming**: Results stream to the frontend in real-time

Rate limited to 20 reviews/hour.

### Personalized Roadmap
Based on your GitHub analysis + a target role you pick (SDE Intern, Backend, Full Stack, DevOps, ML/AI, etc.), DevBrain generates a 6-week study plan. The structure is deterministic — the engine picks topics and projects based on your skill gaps. LLM only polishes the copy.

Supports 9+ target roles. Tracks completion as you go.

### Mock Interviews
Two modes:

- **DSA mode**: Starts at Hard, adapts based on your scores. Score ≥7 → harder questions, ≤4 → easier. 4 rounds per session, then you get a scorecard.
- **Resume mode**: Upload your resume (PDF), and it asks project-specific behavioral questions based on what it extracts.

Each answer gets scored 1-10 with feedback. The final report breaks down strengths and areas to work on.

### Resource Finder
Search for learning resources on any topic. Uses a RAG pipeline — ChromaDB semantic search first, falls back to Tavily web search. Results get ranked by source quality (official docs > GitHub repos > tutorials > random blogs) and relevance. Comes with 20 curated seed resources you can load.

### Progress Analytics
Dashboard with:
- Activity heatmap (GitHub-style)
- Skill trend charts (7-day and 30-day deltas)
- Current streak across challenges, reviews, and interviews
- Exam readiness scores per skill
- Weekly digest with action items

All computed from live DB data, not stale caches.

---

## Tech Stack

### Backend
| What | Why |
|------|-----|
| **FastAPI** + Uvicorn | Async API, typed, fast |
| **LangGraph 0.2** | Multi-agent orchestration with conditional edges and reflection loops |
| **Groq API** (Llama 3.3 70B) | Primary LLM, with Llama 3.1 8B as fallback when rate-limited |
| **PostgreSQL 16** + asyncpg | Primary data store, JSONB columns, UUID PKs |
| **Redis 7** | Caching (skill profiles, dashboards) + rate limiting |
| **ChromaDB 1.5** | Vector store for resource RAG and code review indexing |
| **Tavily** | Web search for resources and challenge sourcing |
| **SQLAlchemy 2.0** | Async ORM with Alembic migrations |
| **Docker** | Sandbox execution for C++ (gcc:13) and Java (eclipse-temurin:21) |
| **PyPDF2** | Resume text extraction for interview mode |
| **sentence-transformers** | Embeddings for ChromaDB |

### Frontend
| What | Why |
|------|-----|
| **Next.js 14** (App Router) | SSR, file-based routing |
| **React 18** + TypeScript | Type safety |
| **Tailwind CSS 3.4** | Styling |
| **Monaco Editor** | VS Code-like code editor in the browser |
| **Recharts** | Radar charts, line charts, bar charts for analytics |
| **Lucide React** | Icons |

### Infrastructure
| What | Why |
|------|-----|
| **Docker Compose** | PostgreSQL + Redis in containers |
| **GitHub Actions** | CI/CD — backend tests, ruff linting, frontend build |

---

## Running Locally

### Prerequisites

- **Python 3.11+**
- **Node.js 20+**
- **Docker Desktop** (for PostgreSQL, Redis, and the code sandbox)
- **API Keys**: Groq, GitHub OAuth app, Tavily

### 1. Clone and configure

```bash
git clone https://github.com/NileshGoyal237/DevBrain.git
cd DevBrain
```

Set up environment variables:

```bash
# Backend
cp backend/.env.example backend/.env
```

Edit `backend/.env` and fill in your keys:

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

Wait a few seconds for the healthchecks to pass. You can verify with `docker ps`.

### 3. Pull sandbox images (for code execution)

The challenge system runs user code inside Docker containers. Pull these once:

```bash
docker pull python:3.12-alpine
docker pull gcc:13
docker pull eclipse-temurin:21-jdk
```

### 4. Start the backend

```bash
cd backend

# Create a virtual environment (first time only)
python -m venv .venv

# Activate it
# Windows:
.venv\Scripts\activate
# Mac/Linux:
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn main:app --reload --port 8000
```

The API docs are at [http://localhost:8000/docs](http://localhost:8000/docs).

### 5. Start the frontend

Open a new terminal:

```bash
cd frontend

npm install
npm run dev
```

App is at [http://localhost:3000](http://localhost:3000).

### 6. Seed resources (optional)

To populate the resource finder with curated learning materials:

```bash
curl -X POST http://localhost:8000/resources/seed
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Next.js Frontend                      │
│  Dashboard │ Challenges │ Review │ Interview │ Roadmap   │
└──────────────────────┬──────────────────────────────────┘
                       │ REST + SSE
┌──────────────────────▼──────────────────────────────────┐
│                  FastAPI Backend                         │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │           LangGraph Orchestrator                 │    │
│  │                                                  │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │    │
│  │  │ GitHub   │ │Challenge │ │ Code Review      │ │    │
│  │  │ Analyzer │ │ Agent    │ │ Agent + Reflector│ │    │
│  │  └──────────┘ └──────────┘ └──────────────────┘ │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │    │
│  │  │ Roadmap  │ │Interview │ │ Resource Agent   │ │    │
│  │  │ Agent    │ │ Agent    │ │ (RAG)            │ │    │
│  │  └──────────┘ └──────────┘ └──────────────────┘ │    │
│  │  ┌──────────┐                                    │    │
│  │  │ Progress │                                    │    │
│  │  │ Agent    │                                    │    │
│  │  └──────────┘                                    │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │ Groq API │ │ Tavily   │ │ ChromaDB │ │ Sandbox   │  │
│  │ (LLM)    │ │ (Search) │ │ (Vector) │ │ (Docker)  │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────┘  │
└────────┬────────────────────────────┬───────────────────┘
         │                            │
    ┌────▼────┐                  ┌────▼────┐
    │PostgreSQL│                  │  Redis  │
    │   16    │                  │    7    │
    └─────────┘                  └─────────┘
```

### How the agents work

The orchestrator receives a request, classifies the intent, and routes to the right agent. Most agents follow a simple pattern: gather context → call LLM → return result. Two agents are more interesting:

**Challenge Agent** has a self-verification loop. After the LLM generates a challenge, the agent runs the reference solution in a Docker sandbox, compares outputs against expected test cases, and auto-corrects mismatches. It retries up to 4 times before giving up.

**Code Review Agent** uses a reflection loop. After generating a review, a reflector node runs sandbox checks on the suggested improvements and re-scores the review. If quality is below threshold, it loops back for another pass.


---


