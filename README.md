# 🔍 ReguSense

**B2B RegTech Intelligence Platform** — AI-powered political contradiction detection and legislative risk monitoring for Turkish Parliament (TBMM).

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![Gemini](https://img.shields.io/badge/AI-Google%20Gemini-orange)
![ChromaDB](https://img.shields.io/badge/Vector%20DB-ChromaDB-green)
![Streamlit](https://img.shields.io/badge/UI-Streamlit-red)

---

## 🎯 Overview

ReguSense monitors Turkish Grand National Assembly (TBMM) proceedings and detects:

- 🔄 **Political Contradictions** — When politicians contradict their previous statements
- ⚠️ **Legislative Risks** — New taxes, bans, and regulations before they become law
- 📊 **Trend Analysis** — Track political narratives across time

**Target Sectors:** Fintech, Energy, Construction, Banking

---

## ✨ Key Features

### 🧠 Contradiction Detection Engine
- Semantic search using RAG (Retrieval Augmented Generation)
- LLM-powered verification with Google Gemini
- Historical statement tracking per politician
- Confidence scoring and detailed explanations

### 📡 Live Mode
- Real-time speech-to-text transcription (Whisper)
- YouTube/live stream monitoring
- Automatic contradiction alerts during broadcasts

### 📄 Data Ingestion
- TBMM Commission transcript scraping
- General Assembly proceedings
- Twitter/X political statements
- PDF document processing

### 📊 Streamlit Dashboard
- Interactive contradiction search
- Speaker filtering with fuzzy matching
- PDF report generation
- Historical analysis

---

## 🏗️ Project Structure

```
regusense/
├── app.py                    # Streamlit Dashboard
├── main.py                   # CLI Pipeline Entry Point
│
├── intelligence/
│   ├── contradiction_engine.py  # Core contradiction detection
│   ├── gemini_analyzer.py       # Google Gemini AI integration
│   ├── live_engine.py           # Real-time transcription
│   └── risk_engine.py           # Risk scoring & analysis
│
├── memory/
│   └── vector_store.py          # ChromaDB vector storage
│
├── scrapers/
│   └── commission_scraper.py    # TBMM data collection
│
├── processors/
│   └── pdf_processor.py         # PDF-to-Text conversion
│
├── reporting/
│   └── pdf_generator.py         # Report generation
│
├── config/
│   └── settings.py              # Configuration management
│
├── data/                        # Data storage (gitignored)
│   ├── raw/                     # Raw downloaded files
│   ├── chromadb/                # Vector database
│   └── reports/                 # Generated reports
│
└── requirements.txt
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

# Install Playwright browsers
playwright install chromium
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required environment variables:
```env
GEMINI_API_KEY=your_google_gemini_api_key
```

### 3. Run the Application

**Streamlit Dashboard (Recommended):**
```bash
streamlit run app.py
```

**CLI Pipeline:**
```bash
python main.py --batch           # Batch analysis mode
python main.py --interactive     # Interactive mode
python main.py --live            # Live transcription mode
```

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| **Language** | Python 3.11+ |
| **AI/LLM** | Google Gemini API |
| **Vector DB** | ChromaDB |
| **Embeddings** | Sentence Transformers |
| **Speech-to-Text** | OpenAI Whisper |
| **Web Scraping** | Playwright, BeautifulSoup |
| **PDF Processing** | pdfplumber, pypdf |
| **Dashboard** | Streamlit |
| **Fuzzy Matching** | TheFuzz (Levenshtein) |
| **Reports** | FPDF2 |

---

## 📖 Usage Examples

### Detect Contradictions

```python
from memory.vector_store import PoliticalMemory
from intelligence.contradiction_engine import ContradictionDetector

memory = PoliticalMemory()
detector = ContradictionDetector(memory)

result = detector.detect(
    query="Enflasyon tek haneye düşecek",
    speaker="Mehmet Şimşek"
)

print(f"Contradiction: {result['is_contradiction']}")
print(f"Confidence: {result['confidence']}%")
```

### Ingest New Data

```python
# From JSON file
python main.py ingest --file statements.json

# From TBMM transcripts
python scrape_general_assembly.py
python ingest_archives.py
```

---

## 🔐 Security

- API keys stored in `.env` (never committed)
- Large data files excluded via `.gitignore`
- No sensitive data in version control

---

## 📄 License

Proprietary — All rights reserved.

---

## 👥 Contact

**ReguSense Team**  
For inquiries: [GitHub Issues](https://github.com/acarcay/regusense/issues)
