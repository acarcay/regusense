# ReguSense

**B2B RegTech Intelligence Platform** - Monitor Turkish Grand National Assembly (TBMM) Commission Transcripts to detect legislative risks for corporate clients.

## Overview

ReguSense monitors TBMM Commission Transcripts to identify potential legislative risks (new taxes, bans, regulations) for Fintech, Energy, and Construction sectors before they become law.

## Tech Stack

- **Language:** Python 3.11+
- **Scraping:** Playwright (dynamic JS pages) & BeautifulSoup
- **PDF Processing:** pdfplumber / pypdf
- **AI Analysis:** Google Gemini API
- **Data Format:** JSON (internal) & PDF (client reporting)

## Project Structure

```
regusense/
├── scrapers/           # Data fetching modules
├── processors/         # PDF-to-Text conversion
├── intelligence/       # Risk keyword matching & Gemini AI
├── reporting/          # Alert generators (Email/PDF)
├── data/raw/contracts/ # Downloaded PDFs
└── config/             # Configuration management
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Run the commission scraper
python -m scrapers.commission_scraper
```

## License

Proprietary - All rights reserved.
