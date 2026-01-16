"""
Multi-Source Political Intelligence Ingestor.

Parses and ingests political statements from multiple sources:
- PDF: TBMM (Turkish Parliament) transcripts  
- JSON: Social media archives (X/Twitter)
- TXT/SRT: TV interview transcripts (Speech-to-Text outputs)

Each source type is tagged with metadata for filtering:
- TBMM_COMMISSION: Commission transcripts
- TBMM_GENERAL_ASSEMBLY: General assembly transcripts
- SOCIAL_MEDIA: Twitter/X archives
- TV_INTERVIEW: Processed TV interview transcripts

Usage:
    python ingest_archives.py                    # Ingest all files
    python ingest_archives.py --dry-run          # Parse without ingesting
    python ingest_archives.py --file path.pdf    # Ingest specific file
    python ingest_archives.py --source-type SOCIAL_MEDIA  # Set source type

Author: ReguSense Team
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings
from processors.pdf_processor import PDFProcessor
from memory.vector_store import PoliticalMemory

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class ParsedStatement:
    """A parsed statement with speaker attribution.
    
    Attributes:
        speaker: Name of the speaker (from transcript)
        text: The statement text
        page_number: Page where statement started
    """
    speaker: str
    text: str
    page_number: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for ingestion."""
        return {
            "text": self.text,
            "speaker": self.speaker,
            "page_number": self.page_number,
        }


def normalize_speaker_name(speaker: str) -> str:
    """
    Normalize speaker name for consistency in the database.
    
    Handles common inconsistencies:
    - Removes party group prefixes (e.g., "AK PARTİ GRUBU ADINA")
    - Removes location suffixes in parentheses (e.g., "(İstanbul)")
    - Normalizes whitespace
    - Handles Turkish characters correctly
    
    Args:
        speaker: Raw speaker name from transcript
        
    Returns:
        Normalized speaker name
        
    Examples:
        >>> normalize_speaker_name("AK PARTİ GRUBU ADINA MEHMET ŞİMŞEK (Gaziantep)")
        "MEHMET ŞİMŞEK"
        >>> normalize_speaker_name("İYİ PARTİ GRUBU ADINA METİN ERGUN (Muğla)")
        "METİN ERGUN"
    """
    if not speaker:
        return ""
    
    # Normalize whitespace
    speaker = " ".join(speaker.split())
    
    # Remove party group prefixes
    group_patterns = [
        r"^AK\s*PARTİ\s+GRUBU\s+ADINA\s+",
        r"^CHP\s+GRUBU\s+ADINA\s+",
        r"^MHP\s+GRUBU\s+ADINA\s+",
        r"^İYİ\s+PARTİ\s+GRUBU\s+ADINA\s+",
        r"^HDP\s+GRUBU\s+ADINA\s+",
        r"^DEM\s+PARTİ\s+GRUBU\s+ADINA\s+",
        r"^YENİ\s+YOL\s+GRUBU\s+ADINA\s+",
        r"^TBMM\s+BAŞKANI\s+",
        r"^BAŞKAN\s+",
        r"^KOMISYON\s+BAŞKANI\s+",
    ]
    
    for pattern in group_patterns:
        speaker = re.sub(pattern, "", speaker, flags=re.IGNORECASE)
    
    # Remove location in parentheses at the end
    speaker = re.sub(r"\s*\([^)]+\)\s*$", "", speaker)
    
    # Strip and clean up
    speaker = speaker.strip()
    
    return speaker


class TranscriptParser:
    """Parser for structured TBMM transcript text.
    
    Handles the specific format of Turkish Parliament transcripts:
    - Speaker lines: UPPERCASE NAME with Turkish chars, followed by hyphen (-)
    - Noise: Headers, footers, page numbers, metadata
    - Continuation: Subsequent lines belong to current speaker
    
    Example:
        >>> parser = TranscriptParser()
        >>> statements = parser.parse(text)
        >>> for stmt in statements:
        ...     print(f"{stmt.speaker}: {stmt.text[:50]}...")
    """
    
    # Noise patterns to filter out
    NOISE_PATTERNS = [
        re.compile(r"T\s*B\s*M\s*M", re.IGNORECASE),
        re.compile(r"Tutanak\s+Hizmetleri", re.IGNORECASE),
        re.compile(r"Sayfa\s*:\s*\d+", re.IGNORECASE),
        re.compile(r"^\s*\d+\s*$"),  # Standalone numbers
        re.compile(r"İncelenmemiş\s+Tutanak", re.IGNORECASE),
        re.compile(r"^\s*-+\s*$"),  # Line of dashes
        re.compile(r"^Birleşim\s*:", re.IGNORECASE),
        re.compile(r"^Tarih\s*:", re.IGNORECASE),
        re.compile(r"^Oturum\s*:", re.IGNORECASE),
        re.compile(r"^\s*\*+\s*$"),  # Line of asterisks
        re.compile(r"^MADDE\s+\d+", re.IGNORECASE),  # Law article headings
    ]
    
    # Turkish uppercase characters for speaker detection
    TURKISH_UPPER = "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ"
    
    def __init__(self, min_statement_length: int = 20):
        """
        Initialize the parser.
        
        Args:
            min_statement_length: Minimum characters for valid statement
        """
        self.min_statement_length = min_statement_length
    
    def is_noise(self, line: str) -> bool:
        """
        Check if a line is noise (header, footer, page number, etc.).
        
        Args:
            line: Line to check
            
        Returns:
            True if line is noise and should be skipped
        """
        line = line.strip()
        
        # Empty lines are noise
        if not line:
            return True
        
        # Very short lines (< 3 chars) are usually noise
        if len(line) < 3:
            return True
        
        # Check against noise patterns
        for pattern in self.NOISE_PATTERNS:
            if pattern.search(line):
                return True
        
        return False
    
    def is_new_speaker(self, line: str) -> tuple[bool, str, str]:
        """
        Check if line indicates a new speaker.
        
        Speaker lines follow the pattern:
        "UPPERCASE NAME - text" or "UPPERCASE NAME -" (text on next line)
        
        Args:
            line: Line to check
            
        Returns:
            Tuple of (is_speaker, speaker_name, remaining_text)
        """
        line = line.strip()
        
        # Must contain a hyphen
        if " - " not in line and not line.endswith(" -"):
            return (False, "", "")
        
        # Split on first " - "
        if " - " in line:
            parts = line.split(" - ", 1)
            potential_speaker = parts[0].strip()
            remaining = parts[1].strip() if len(parts) > 1 else ""
        else:
            # Ends with " -"
            potential_speaker = line[:-2].strip()
            remaining = ""
        
        # Check if the speaker part is mostly uppercase
        if not potential_speaker:
            return (False, "", "")
        
        # Count uppercase letters (including Turkish chars)
        upper_count = sum(1 for c in potential_speaker if c in self.TURKISH_UPPER)
        letter_count = sum(1 for c in potential_speaker if c.isalpha())
        
        # At least 70% uppercase letters and minimum 3 letters
        if letter_count < 3:
            return (False, "", "")
        
        uppercase_ratio = upper_count / letter_count if letter_count > 0 else 0
        
        if uppercase_ratio >= 0.7:
            return (True, potential_speaker, remaining)
        
        return (False, "", "")
    
    def parse(self, text: str) -> list[ParsedStatement]:
        """
        Parse transcript text into speaker-attributed statements.
        
        Args:
            text: Full transcript text
            
        Returns:
            List of ParsedStatement objects
        """
        statements = []
        current_speaker = ""
        current_buffer = []
        current_page = 1
        
        lines = text.split("\n")
        
        for line in lines:
            # Skip noise lines
            if self.is_noise(line):
                continue
            
            # Check for new speaker
            is_speaker, speaker_name, remaining = self.is_new_speaker(line)
            
            if is_speaker:
                # Save previous speaker's statement
                if current_speaker and current_buffer:
                    full_text = " ".join(current_buffer).strip()
                    if len(full_text) >= self.min_statement_length:
                        statements.append(ParsedStatement(
                            speaker=current_speaker,
                            text=full_text,
                            page_number=current_page,
                        ))
                
                # Start new speaker
                current_speaker = speaker_name
                current_buffer = [remaining] if remaining else []
            else:
                # Continuation of current speaker's text
                if current_speaker:
                    current_buffer.append(line.strip())
                # If no current speaker, we might be in intro/header - skip
        
        # Don't forget the last speaker's statement
        if current_speaker and current_buffer:
            full_text = " ".join(current_buffer).strip()
            if len(full_text) >= self.min_statement_length:
                statements.append(ParsedStatement(
                    speaker=normalize_speaker_name(current_speaker),
                    text=full_text,
                    page_number=current_page,
                ))
        
        return statements
    
    def parse_pages(self, pages: list) -> list[ParsedStatement]:
        """
        Parse from a list of page objects.
        
        Args:
            pages: List of PageContent objects from PDFProcessor
            
        Returns:
            List of ParsedStatement objects with page numbers
        """
        statements = []
        current_speaker = ""
        current_buffer = []
        statement_start_page = 1
        
        for page in pages:
            page_num = page.page if hasattr(page, 'page') else 1
            text = page.text if hasattr(page, 'text') else str(page)
            lines = text.split("\n")
            
            for line in lines:
                if self.is_noise(line):
                    continue
                
                is_speaker, speaker_name, remaining = self.is_new_speaker(line)
                
                if is_speaker:
                    # Save previous
                    if current_speaker and current_buffer:
                        full_text = " ".join(current_buffer).strip()
                        if len(full_text) >= self.min_statement_length:
                            statements.append(ParsedStatement(
                                speaker=current_speaker,
                                text=full_text,
                                page_number=statement_start_page,
                            ))
                    
                    # Start new
                    current_speaker = speaker_name
                    current_buffer = [remaining] if remaining else []
                    statement_start_page = page_num
                else:
                    if current_speaker:
                        current_buffer.append(line.strip())
        
        # Final statement
        if current_speaker and current_buffer:
            full_text = " ".join(current_buffer).strip()
            if len(full_text) >= self.min_statement_length:
                statements.append(ParsedStatement(
                    speaker=normalize_speaker_name(current_speaker),
                    text=full_text,
                    page_number=statement_start_page,
                ))
        
        return statements


class JSONParser:
    """Parser for social media JSON archives (X/Twitter).
    
    Expected JSON structure (Twitter archive format):
    [
        {
            "tweet": {..., "full_text": "...", "created_at": "...", ...},
            ...
        }
    ]
    
    Or simplified format:
    [
        {"text": "...", "date": "...", "speaker": "..."},
        ...
    ]
    
    Example:
        >>> parser = JSONParser()
        >>> statements = parser.parse_file("tweets.json", speaker="@politikan")
    """
    
    def __init__(self, min_statement_length: int = 20):
        self.min_statement_length = min_statement_length
    
    def parse_file(
        self, 
        filepath: Path, 
        speaker: str = "",
    ) -> list[ParsedStatement]:
        """
        Parse a JSON file into statements.
        
        Args:
            filepath: Path to JSON file
            speaker: Default speaker name (can be overridden by JSON data)
            
        Returns:
            List of ParsedStatement objects
        """
        statements = []
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Failed to parse JSON {filepath}: {e}")
            return statements
        
        # Handle list of tweets/statements
        if isinstance(data, list):
            for item in data:
                stmt = self._parse_item(item, speaker)
                if stmt and len(stmt.text) >= self.min_statement_length:
                    statements.append(stmt)
        
        # Handle single object with array field
        elif isinstance(data, dict):
            # Twitter archive format
            for key in ["tweets", "posts", "statements", "data"]:
                if key in data and isinstance(data[key], list):
                    for item in data[key]:
                        stmt = self._parse_item(item, speaker)
                        if stmt and len(stmt.text) >= self.min_statement_length:
                            statements.append(stmt)
                    break
        
        return statements
    
    def _parse_item(self, item: dict, default_speaker: str) -> Optional[ParsedStatement]:
        """Parse a single JSON item into a statement."""
        if not isinstance(item, dict):
            return None
        
        # Twitter format: item.tweet.full_text
        if "tweet" in item:
            tweet = item["tweet"]
            text = tweet.get("full_text", "")
            date = tweet.get("created_at", "")
        else:
            # Simplified format
            text = item.get("text", item.get("full_text", item.get("content", "")))
            date = item.get("date", item.get("created_at", item.get("timestamp", "")))
        
        if not text:
            return None
        
        speaker = item.get("speaker", item.get("user", item.get("author", default_speaker)))
        
        return ParsedStatement(
            speaker=str(speaker),
            text=text.strip(),
            page_number=0,  # Not applicable for social media
        )


class SRTParser:
    """Parser for SRT/TXT speech-to-text transcripts.
    
    Handles:
    - SRT subtitle format (timecodes + text)
    - Plain TXT transcripts (speaker: text format)
    
    Example:
        >>> parser = SRTParser()
        >>> statements = parser.parse_file("interview.srt", speaker="Politician")
    """
    
    # SRT timestamp pattern: 00:00:00,000 --> 00:00:00,000
    SRT_TIMESTAMP = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}$")
    # Speaker pattern: SPEAKER: text or Speaker - text
    SPEAKER_PATTERN = re.compile(r"^([A-ZÇĞİÖŞÜa-zçğıöşü\s]+)\s*[-:]\s*(.+)$")
    
    def __init__(self, min_statement_length: int = 20):
        self.min_statement_length = min_statement_length
    
    def parse_file(
        self, 
        filepath: Path, 
        speaker: str = "",
    ) -> list[ParsedStatement]:
        """
        Parse an SRT or TXT file into statements.
        
        Args:
            filepath: Path to file
            speaker: Default speaker name
            
        Returns:
            List of ParsedStatement objects
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            # Try with latin-1 encoding
            with open(filepath, "r", encoding="latin-1") as f:
                content = f.read()
        
        # Detect format
        if self.SRT_TIMESTAMP.search(content):
            return self._parse_srt(content, speaker)
        else:
            return self._parse_txt(content, speaker)
    
    def _parse_srt(self, content: str, default_speaker: str) -> list[ParsedStatement]:
        """Parse SRT subtitle format."""
        statements = []
        lines = content.split("\n")
        
        current_text_lines = []
        
        for line in lines:
            line = line.strip()
            
            # Skip empty lines, numbers, and timestamps
            if not line or line.isdigit() or self.SRT_TIMESTAMP.match(line):
                continue
            
            # Check for speaker annotation in subtitle
            speaker_match = self.SPEAKER_PATTERN.match(line)
            if speaker_match:
                # Save previous text
                if current_text_lines:
                    text = " ".join(current_text_lines).strip()
                    if len(text) >= self.min_statement_length:
                        statements.append(ParsedStatement(
                            speaker=default_speaker,
                            text=text,
                            page_number=0,
                        ))
                    current_text_lines = []
                
                # New speaker
                default_speaker = speaker_match.group(1).strip()
                remaining = speaker_match.group(2).strip()
                if remaining:
                    current_text_lines.append(remaining)
            else:
                current_text_lines.append(line)
        
        # Final statement
        if current_text_lines:
            text = " ".join(current_text_lines).strip()
            if len(text) >= self.min_statement_length:
                statements.append(ParsedStatement(
                    speaker=default_speaker,
                    text=text,
                    page_number=0,
                ))
        
        return statements
    
    def _parse_txt(self, content: str, default_speaker: str) -> list[ParsedStatement]:
        """Parse plain text format."""
        statements = []
        current_speaker = default_speaker
        current_lines = []
        
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            
            # Check for speaker change
            speaker_match = self.SPEAKER_PATTERN.match(line)
            if speaker_match:
                # Save previous
                if current_lines:
                    text = " ".join(current_lines).strip()
                    if len(text) >= self.min_statement_length:
                        statements.append(ParsedStatement(
                            speaker=current_speaker,
                            text=text,
                            page_number=0,
                        ))
                    current_lines = []
                
                current_speaker = speaker_match.group(1).strip()
                remaining = speaker_match.group(2).strip()
                if remaining:
                    current_lines.append(remaining)
            else:
                current_lines.append(line)
        
        # Final
        if current_lines:
            text = " ".join(current_lines).strip()
            if len(text) >= self.min_statement_length:
                statements.append(ParsedStatement(
                    speaker=current_speaker,
                    text=text,
                    page_number=0,
                ))
        
        return statements


# Source type constants
SOURCE_TYPES = {
    "TBMM_COMMISSION": "TBMM Komisyon Tutanağı",
    "TBMM_GENERAL_ASSEMBLY": "TBMM Genel Kurul Tutanağı",
    "SOCIAL_MEDIA": "Sosyal Medya (X/Twitter)",
    "TV_INTERVIEW": "TV Röportajı",
    "NEWS": "Haber/Basın",
    "UNKNOWN": "Bilinmeyen",
}


class MultiSourceIngestor:
    """Ingest political statements from multiple sources into PoliticalMemory.
    
    Handles:
    - PDF: TBMM transcripts using PDFProcessor
    - JSON: Social media archives (X/Twitter)
    - TXT/SRT: TV interview transcripts
    - Batch ingestion into ChromaDB via PoliticalMemory
    
    Example:
        >>> ingestor = MultiSourceIngestor()
        >>> stats = ingestor.ingest_all()
        >>> print(f"Ingested {stats['total_statements']} statements")
    """
    
    def __init__(
        self,
        data_dir: str | Path = "data/raw/contracts",
        memory: Optional[PoliticalMemory] = None,
        default_source_type: str = "TBMM_COMMISSION",
    ):
        """
        Initialize the multi-source ingestor.
        
        Args:
            data_dir: Directory containing source files (PDF, JSON, TXT, SRT)
            memory: Optional PoliticalMemory instance (creates new if None)
            default_source_type: Default source type for files without explicit type
        """
        self.data_dir = Path(data_dir)
        self.memory = memory
        self.default_source_type = default_source_type
        
        # Parsers for different formats
        self.transcript_parser = TranscriptParser()
        self.json_parser = JSONParser()
        self.srt_parser = SRTParser()
        self.processor = PDFProcessor()
    
    def _get_memory(self) -> PoliticalMemory:
        """Lazy initialization of PoliticalMemory."""
        if self.memory is None:
            self.memory = PoliticalMemory()
        return self.memory
    
    def extract_date_from_filename(self, filename: str) -> str:
        """
        Extract date from filename.
        
        Expected formats:
        - YYYY-MM-DD_...
        - ...DDMMYYYY_Tarihli...
        - Twitter date in filename
        
        Args:
            filename: Filename
            
        Returns:
            ISO date string or today's date
        """
        # Try YYYY-MM-DD at start
        match = re.match(r"^(\d{4}-\d{2}-\d{2})", filename)
        if match:
            return match.group(1)
        
        # Try DDMMYYYY_Tarihli pattern
        match = re.search(r"(\d{2})(\d{2})(\d{4})_Tarihli", filename)
        if match:
            day, month, year = match.groups()
            return f"{year}-{month}-{day}"
        
        # Fallback to today
        return datetime.now().strftime("%Y-%m-%d")
    
    def detect_source_type(self, filepath: Path) -> str:
        """
        Auto-detect source type from filename or path.
        
        Args:
            filepath: Path to file
            
        Returns:
            Source type constant
        """
        filename_lower = filepath.name.lower()
        path_str = str(filepath).lower()
        
        # Check filename patterns
        if "tweet" in filename_lower or "twitter" in filename_lower:
            return "SOCIAL_MEDIA"
        if "interview" in filename_lower or "roport" in filename_lower:
            return "TV_INTERVIEW"
        if "genel_kurul" in path_str or "general_assembly" in path_str:
            return "TBMM_GENERAL_ASSEMBLY"
        
        # Check extension defaults
        if filepath.suffix.lower() in [".json"]:
            return "SOCIAL_MEDIA"
        if filepath.suffix.lower() in [".srt"]:
            return "TV_INTERVIEW"
        
        return self.default_source_type
    
    def ingest_file(
        self,
        filepath: Path,
        dry_run: bool = False,
        source_type: Optional[str] = None,
        speaker: str = "",
    ) -> dict:
        """
        Ingest a single file (PDF, JSON, TXT, or SRT).
        
        Args:
            filepath: Path to file
            dry_run: If True, parse but don't ingest
            source_type: Override source type (auto-detected if None)
            speaker: Default speaker for files without speaker info
            
        Returns:
            Dict with ingestion stats
        """
        logger.info(f"Processing: {filepath.name}")
        
        # Detect source type if not specified
        if source_type is None:
            source_type = self.detect_source_type(filepath)
        
        stats = {
            "file": filepath.name,
            "file_type": filepath.suffix.lower(),
            "source_type": source_type,
            "pages": 0,
            "statements_parsed": 0,
            "statements_ingested": 0,
            "speakers": set(),
        }
        
        try:
            extension = filepath.suffix.lower()
            
            # Parse based on file type
            if extension == ".pdf":
                statements = self._parse_pdf(filepath, stats)
            elif extension == ".json":
                statements = self.json_parser.parse_file(filepath, speaker=speaker)
            elif extension in [".txt", ".srt"]:
                statements = self.srt_parser.parse_file(filepath, speaker=speaker)
            else:
                logger.warning(f"Unsupported file type: {extension}")
                return stats
            
            stats["statements_parsed"] = len(statements)
            
            if not statements:
                logger.warning(f"No statements parsed from {filepath.name}")
                return stats
            
            # Collect unique speakers
            for stmt in statements:
                stats["speakers"].add(stmt.speaker)
            
            logger.info(f"  Parsed {len(statements)} statements from {len(stats['speakers'])} speakers")
            
            if dry_run:
                # Just print sample
                for stmt in statements[:3]:
                    print(f"  [{stmt.speaker}]: {stmt.text[:80]}...")
                if len(statements) > 3:
                    print(f"  ... and {len(statements) - 3} more")
                return stats
            
            # Prepare for ingestion with source_type and session_id
            date = self.extract_date_from_filename(filepath.name)
            session_id = self.extract_session_id(filepath.name)
            items = []
            
            for stmt in statements:
                items.append({
                    "text": stmt.text,
                    "speaker": stmt.speaker,
                    "date": date,
                    "source": filepath.name,
                    "source_type": source_type,
                    "session_id": session_id,
                    "topic": SOURCE_TYPES.get(source_type, ""),
                    "page": stmt.page_number,
                })
            
            # Batch ingest
            memory = self._get_memory()
            ids = memory.ingest_batch(items)
            stats["statements_ingested"] = len(ids)
            
            logger.info(f"  Ingested {len(ids)} statements into memory (type: {source_type})")
            
        except Exception as e:
            logger.error(f"Error processing {filepath.name}: {e}")
            stats["error"] = str(e)
        
        return stats
    
    def extract_session_id(self, filename: str) -> str:
        """
        Extract session ID from filename.
        
        Expected patterns:
        - ..._2641_... -> Session 2641
        - Dönem_28_Yasama_3_... -> Dönem 28, Yasama Yılı 3
        
        Args:
            filename: Filename
            
        Returns:
            Session ID string or empty
        """
        # Pattern 1: Simple session number (e.g., 2641 from commission transcripts)
        match = re.search(r"_(\d{4})_\d{8}_", filename)
        if match:
            return f"Oturum {match.group(1)}"
        
        # Pattern 2: Dönem and Yasama
        match = re.search(r"Dönem[_\s]*(\d+)[_\s]*Yasama[_\s]*(\d+)", filename, re.IGNORECASE)
        if match:
            return f"Dönem {match.group(1)}, Yasama Yılı {match.group(2)}"
        
        return ""
    
    def _parse_pdf(self, filepath: Path, stats: dict) -> list[ParsedStatement]:
        """Parse PDF file into statements."""
        pages = self.processor.extract_text(filepath)
        stats["pages"] = len(pages)
        
        if not pages:
            return []
        
        return self.transcript_parser.parse_pages(pages)
    
    def ingest_all(
        self, 
        dry_run: bool = False,
        source_type: Optional[str] = None,
    ) -> dict:
        """
        Ingest all supported files in the data directory.
        
        Supports: PDF, JSON, TXT, SRT
        
        Args:
            dry_run: If True, parse but don't ingest
            source_type: Override source type for all files
            
        Returns:
            Aggregated stats dictionary
        """
        # Find all supported files
        supported_extensions = ["*.pdf", "*.json", "*.txt", "*.srt"]
        all_files = []
        
        for ext in supported_extensions:
            all_files.extend(self.data_dir.glob(ext))
        
        if not all_files:
            logger.warning(f"No supported files found in {self.data_dir}")
            return {"files_processed": 0}
        
        logger.info(f"Found {len(all_files)} files in {self.data_dir}")
        
        total_stats = {
            "files_processed": 0,
            "files_by_type": {},
            "total_pages": 0,
            "total_statements_parsed": 0,
            "total_statements_ingested": 0,
            "all_speakers": set(),
            "source_types": {},
            "errors": [],
        }
        
        for filepath in sorted(all_files):
            stats = self.ingest_file(filepath, dry_run=dry_run, source_type=source_type)
            
            total_stats["files_processed"] += 1
            total_stats["total_pages"] += stats.get("pages", 0)
            total_stats["total_statements_parsed"] += stats.get("statements_parsed", 0)
            total_stats["total_statements_ingested"] += stats.get("statements_ingested", 0)
            total_stats["all_speakers"].update(stats.get("speakers", set()))
            
            # Track by file type
            file_type = stats.get("file_type", "unknown")
            total_stats["files_by_type"][file_type] = total_stats["files_by_type"].get(file_type, 0) + 1
            
            # Track by source type
            src_type = stats.get("source_type", "UNKNOWN")
            total_stats["source_types"][src_type] = total_stats["source_types"].get(src_type, 0) + 1
            
            if "error" in stats:
                total_stats["errors"].append(stats["error"])
        
        return total_stats


# Backward compatibility alias
ArchiveIngestor = MultiSourceIngestor


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Ingest TBMM transcript archives into PoliticalMemory"
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        help="Specific PDF file to ingest",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Parse without ingesting (preview mode)",
    )
    parser.add_argument(
        "--dir", "-d",
        type=str,
        default="data/raw/contracts",
        help="Directory containing PDF files",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show memory stats after ingestion",
    )
    
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("  TBMM Transcript Archive Ingestor")
    print("=" * 60)
    print(f"  Mode: {'Dry Run (Preview)' if args.dry_run else 'Full Ingestion'}")
    print("=" * 60 + "\n")
    
    ingestor = ArchiveIngestor(pdf_dir=args.dir)
    
    if args.file:
        # Single file
        pdf_path = Path(args.file)
        if not pdf_path.exists():
            print(f"❌ File not found: {args.file}")
            return
        
        stats = ingestor.ingest_file(pdf_path, dry_run=args.dry_run)
        print(f"\n📊 Results:")
        print(f"   Pages: {stats.get('pages', 0)}")
        print(f"   Statements parsed: {stats.get('statements_parsed', 0)}")
        print(f"   Statements ingested: {stats.get('statements_ingested', 0)}")
        print(f"   Unique speakers: {len(stats.get('speakers', set()))}")
    else:
        # All files
        stats = ingestor.ingest_all(dry_run=args.dry_run)
        print(f"\n📊 Summary:")
        print(f"   Files processed: {stats['files_processed']}")
        print(f"   Total pages: {stats['total_pages']}")
        print(f"   Statements parsed: {stats['total_statements_parsed']}")
        print(f"   Statements ingested: {stats['total_statements_ingested']}")
        print(f"   Unique speakers: {len(stats['all_speakers'])}")
        
        if stats["errors"]:
            print(f"\n⚠️  Errors: {len(stats['errors'])}")
            for err in stats["errors"][:5]:
                print(f"   - {err}")
    
    if args.stats and not args.dry_run:
        memory = ingestor._get_memory()
        print(f"\n📦 Memory Stats:")
        print(f"   Total documents: {memory.count()}")
    
    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    main()
