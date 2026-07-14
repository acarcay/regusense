# 🔍 ReguSense

**B2B RegTech Intelligence Platform** — AI-powered political contradiction detection, legislative risk monitoring, and temporal conflict analysis for the Turkish Parliament (TBMM).

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![Gemini](https://img.shields.io/badge/AI-Google%20Gemini-orange)
![LangGraph](https://img.shields.io/badge/Agents-LangGraph-purple)
![Neo4j](https://img.shields.io/badge/GraphDB-Neo4j-blue)
![ChromaDB](https://img.shields.io/badge/Vector%20DB-ChromaDB-green)
![PostgreSQL](https://img.shields.io/badge/RDBMS-PostgreSQL-blue)

---

## 🎯 Overview

ReguSense monitors Turkish Grand National Assembly (TBMM) proceedings, public procurement data (EKAP), and political statements to detect:

- 🔄 **Political Contradictions** — When politicians contradict their previous statements
- 🕵️ **Temporal Conflicts (Hunter Scan)** — Correlations between political advocacy and public tenders
- ⚠️ **Legislative Risks** — New taxes, bans, and regulations before they become law
- 🔗 **Conflict of Interest** — Politician–organization connections via Neo4j graph queries

**Target Sectors:** Fintech, Energy, Construction, Banking, Political Strategy (PoliTech)

---

## ✨ Key Features

### 🤖 Multi-Agent Analysis (LangGraph)
A multi-agent workflow (`agents/`) that analyzes political statements end to end:

```
Watchdog → Archivist → Investigator → (Analyst ⟳ Searcher) → Editor → Human Approval
```

| Agent | Role |
|---|---|
| **Watchdog** | Scores newsworthiness; filters routine/procedural content |
| **Archivist** | Queries ChromaDB (semantic) and PostgreSQL (structured) for prior statements |
| **Investigator** | Queries **Neo4j** for politician–organization conflict-of-interest links with temporal decay scoring |
| **Searcher** | External web search (Tavily) when internal evidence is thin |
| **Analyst** | Gemini LLM reasoning over the full evidence chain; loops back to Searcher if needed |
| **Editor** | Formats the final contradiction report (markdown + tweet draft) |
| **Human Approval** | Human-in-the-loop checkpoint before publishing |

### 🧠 Intelligence & Contradiction Engine
- Semantic search with ChromaDB (RAG — `paraphrase-multilingual-MiniLM-L12-v2`).
- LLM-powered verification and intent classification via Google Gemini 2.0 Flash.
- Temporal conflict detection: `ADVOCATED` ↔ tender award date correlation (±15 day window).
- Weighted conflict scoring with exponential temporal decay (`half_life = 5 years`).

### 📡 Data Collection & Live Mode
- Stealth EKAP scraper for public procurement monitoring.
- TBMM Commission transcript scraping with custom parsers for 5-year historical archives.
- Real-time speech-to-text transcription (Whisper) for YouTube/live stream monitoring.
- Wikidata integration via SPARQL.

### 📊 Interfaces
- **Streamlit Dashboard** (`streamlit_app.py`): Interactive contradiction search, fuzzy matching, and trend analysis.
- **FastAPI Backend** (`app/main.py`): Async REST APIs; all `/api/v1/*` routes require `X-API-Key`.
- **CLI Tool** (`main.py`): Command-line interface for batch processing and pipeline execution.

---

## 🏗️ Project Structure

```
regusense/
├── streamlit_app.py          # Streamlit Dashboard entry point
├── main.py                   # CLI entry point
├── agents/                   # LangGraph multi-agent workflow
│   ├── graph.py              #   Graph definition & runner
│   ├── state.py              #   Shared AgentState TypedDict
│   └── nodes/                #   watchdog / archivist / investigator /
│                             #   searcher / analyst / editor / human_approval
├── app/                      # FastAPI application factory (app.main:app)
├── api/                      # Route handlers & schemas
├── config/                   # Single Settings class (config/settings.py)
├── core/                     # Deps, logging, compat shims
├── database/                 # PostgreSQL session + Neo4j client
├── intelligence/             # Contradiction engine, Gemini analyzer, sector classifier
├── memory/                   # ChromaDB vector store (PoliticalMemory)
├── pipeline/                 # Intelligence pipeline (EKAP → Hunter → Temporal)
├── scrapers/                 # EKAP and TBMM data collection
├── processors/               # Document and PDF processing
├── reporting/                # Insight Card PDF generation
├── workers/                  # Celery tasks + APScheduler
├── scripts/                  # One-off utilities (ingest, inspect, e2e)
├── tests/                    # Unit tests (pytest)
├── .env.example              # Environment template — copy to .env to get started
└── docker-compose.yml        # Full stack: PostgreSQL, Redis, Neo4j, API, Scheduler
```

---

## 🚀 Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/acarcay/regusense.git
cd regusense

python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env — fill in REGUSENSE_GEMINI_API_KEY, REGUSENSE_DATABASE_URL,
# REGUSENSE_NEO4J_PASSWORD, and REGUSENSE_API_AUTH_KEY
```

> **Note:** Docker Compose will **fail fast** if `POSTGRES_PASSWORD` or `NEO4J_PASSWORD` are missing from `.env`. This is intentional — no hardcoded fallback passwords.

### 3. Start Infrastructure (Docker)

```bash
docker compose up -d postgres redis neo4j
```

### 4. Run the Application

**Streamlit Dashboard:**
```bash
streamlit run streamlit_app.py
```

**Multi-Agent Analysis (LangGraph — Watchdog → Investigator → … → Human Approval):**
```bash
python main.py --agent --query "Enflasyon tek haneye düşecek" --speaker "Mehmet Şimşek"
```

**Full Intelligence Scan (EKAP + Hunter + Temporal Analysis):**
```bash
python main.py --intelligence-scan --ekap-days 30
```

**Interactive Contradiction Check (ChromaDB + Gemini, no LangGraph):**
```bash
python main.py --query "Enflasyon tek haneye düşecek" --speaker "Mehmet Şimşek"
```

**Run as API server:**
```bash
uvicorn app.main:app --reload
```

---

## ⏰ Autonomous Scheduler

The scheduler (`workers/scheduler.py`) runs three nightly jobs via APScheduler:

| Time | Job |
|---|---|
| 01:00 | EKAP Scraper — public tender data |
| 02:00 | Resmi Gazete Scraper — appointments & tenders |
| 03:00 | Intelligence Pipeline — Hunter + Temporal Analysis |

Start with: `docker compose up scheduler`

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| **Language** | Python 3.11+ |
| **Multi-Agent** | LangGraph, LangChain |
| **AI/LLM** | Google Gemini 2.0 Flash |
| **Graph DB** | Neo4j — politician–org conflict graph |
| **Vector DB** | ChromaDB — semantic RAG |
| **Relational DB** | PostgreSQL, asyncpg, SQLAlchemy |
| **Task Queue** | Celery, Redis |
| **API Framework** | FastAPI, Uvicorn |
| **Web Scraping** | Playwright (Stealth), BeautifulSoup |
| **Speech-to-Text** | OpenAI Whisper |
| **Dashboard** | Streamlit |

---

## 🔐 Security & Operations

- All secrets in `.env` (never committed). `.env.example` is the tracked template.
- REST API protected by `X-API-Key` — set `REGUSENSE_API_AUTH_KEY` in `.env`. Constant-time comparison; empty key disables auth with a loud warning (dev only).
- CORS restricted to explicitly configured origins (`REGUSENSE_CORS_ORIGINS`); `["*"]` + credentials is invalid per spec and not used.
- Docker Compose fails fast on missing `POSTGRES_PASSWORD` / `NEO4J_PASSWORD`.
- CI (GitHub Actions) runs `ruff` lint gate (critical rules) + unit tests on every push and pull request.
- Structured JSON logging to `data/logs/`.

---

## 📄 License

Proprietary — All rights reserved.

---

## 👥 Contact

**ReguSense Team**  
For inquiries: [GitHub Issues](https://github.com/acarcay/regusense/issues)
