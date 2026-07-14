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
- 🕵️ **Temporal Conflicts (Hunter Scan)** — Detecting correlations between political advocacy and public tenders (e.g., criticizing a company then awarding them a tender)
- ⚠️ **Legislative Risks** — New taxes, bans, and regulations before they become law
- 📊 **Trend Analysis** — Track political narratives across time

**Target Sectors:** Fintech, Energy, Construction, Banking, Political Strategy (PoliTech)

---

## ✨ Key Features

### 🤖 Multi-Agent Analysis (LangGraph)
A multi-agent workflow (`agents/`) that analyzes political statements end to end:
- **Watchdog**: Scores newsworthiness and filters routine/procedural content.
- **Archivist**: Queries internal databases (PostgreSQL, ChromaDB) for prior statements.
- **Searcher**: Performs external web search when internal evidence is thin.
- **Analyst**: LLM reasoning over the evidence chain (loops back to Searcher if needed).
- **Editor**: Formats the final contradiction report.
- **Human Approval**: Human-in-the-loop checkpoint before publishing.

### 🧠 Intelligence & Contradiction Engine
- Semantic search using RAG (Retrieval Augmented Generation) with ChromaDB.
- LLM-powered verification and intent classification with Google Gemini 2.0.
- Temporal Conflict Analysis using Neo4j to find relationships between politicians, statements, and awarded companies.

### 📡 Data Collection & Live Mode
- Stealth EKAP Scraper for public procurement monitoring.
- TBMM Commission transcript scraping with custom parsers for 5-year historical archives.
- Real-time speech-to-text transcription (Whisper) for YouTube/live stream monitoring.
- Wikidata integration via SPARQL.

### 📊 Interfaces
- **Streamlit Dashboard**: Interactive contradiction search, fuzzy matching, and trend analysis.
- **FastAPI Backend**: Async REST APIs for system integrations.
- **CLI Tool**: Powerful command-line interface for batch processing and pipeline execution.

---

## 🏗️ Project Structure

```
regusense/
├── streamlit_app.py          # Streamlit Dashboard
├── agents/                   # LangGraph multi-agent workflow (Watchdog → … → Human Approval)
├── main.py                   # CLI Pipeline Entry Point
├── api/                      # FastAPI endpoints
├── core/                     # Core business logic
├── config/                   # Configuration management
├── data/                     # Raw files, vector DB, reports
├── intelligence/             # Agent graph, Gemini analyzer, contradiction engine
├── memory/                   # ChromaDB vector storage
├── scrapers/                 # EKAP and TBMM data collection
├── processors/               # Document and PDF processing
├── reporting/                # Insight Card PDF generation
├── database/                 # PostgreSQL and Neo4j clients
├── workers/                  # Celery background tasks
└── tests/                    # Pytest test suites
```

---

## 🚀 Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/acarcay/regusense.git
cd regusense

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers for scrapers
playwright install chromium
```

### 2. Configure Environment

Copy the example environment file and add your credentials:
```bash
cp .env.example .env
```
Ensure you set up your `GEMINI_API_KEY`, PostgreSQL URI, and Neo4j credentials in the `.env` file.

### 3. Run the Application

**Run Multi-Agent Analysis on a statement:**
```bash
python main.py --agent --query "Enflasyon tek haneye düşecek" --speaker "Mehmet Şimşek"
```

**Run Full Intelligence Scan (EKAP + Hunter + Temporal Analysis):**
```bash
python main.py --intelligence-scan --ekap-days 30
```

**Streamlit Dashboard:**
```bash
streamlit run streamlit_app.py
```

**Interactive Contradiction Check:**
```bash
python main.py --query "Enflasyon tek haneye düşecek" --speaker "Mehmet Şimşek"
```

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| **Language** | Python 3.11+ |
| **Multi-Agent** | LangGraph, LangChain |
| **AI/LLM** | Google Gemini API |
| **Graph DB** | Neo4j (Temporal Analysis) |
| **Vector DB** | ChromaDB (RAG) |
| **Relational DB** | PostgreSQL, asyncpg, SQLAlchemy |
| **Task Queue** | Celery, Redis |
| **API Framework** | FastAPI, Uvicorn |
| **Web Scraping** | Playwright (Stealth), BeautifulSoup |
| **Speech-to-Text**| OpenAI Whisper |
| **Dashboard** | Streamlit |

---

## 🔐 Security & Operations

- API keys and DB credentials securely stored in `.env` (never committed).
- REST API protected by `X-API-Key` authentication — set `REGUSENSE_API_AUTH_KEY` in `.env`.
- CORS restricted to explicitly configured origins (`REGUSENSE_CORS_ORIGINS`).
- Asynchronous data processing via Celery and Redis to prevent blocking.
- Configured structured logging (`data/logs/`) for system observability.
- CI (GitHub Actions) runs lint + unit tests on every push and pull request.

---

## 📄 License

Proprietary — All rights reserved.

---

## 👥 Contact

**ReguSense Team**  
For inquiries: [GitHub Issues](https://github.com/acarcay/regusense/issues)
