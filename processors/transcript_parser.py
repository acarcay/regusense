from __future__ import annotations
import re
from dataclasses import dataclass
from utils.text import normalize_speaker_name

@dataclass
class ParsedStatement:
    """A parsed statement with speaker attribution."""
    speaker: str
    text: str
    page_number: int = 0
    
    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "speaker": self.speaker,
            "page_number": self.page_number,
        }

class TranscriptParser:
    """Parser for structured TBMM transcript text."""
    
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
    
    TURKISH_UPPER = "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ"
    
    def __init__(self, min_statement_length: int = 20):
        self.min_statement_length = min_statement_length
    
    def is_noise(self, line: str) -> bool:
        line = line.strip()
        if not line: return True
        if len(line) < 3: return True
        for pattern in self.NOISE_PATTERNS:
            if pattern.search(line): return True
        return False
    
    def is_new_speaker(self, line: str) -> tuple[bool, str, str]:
        line = line.strip()
        if " - " not in line and not line.endswith(" -"):
            return (False, "", "")
            
        if " - " in line:
            parts = line.split(" - ", 1)
            potential_speaker = parts[0].strip()
            remaining = parts[1].strip() if len(parts) > 1 else ""
        else:
            potential_speaker = line[:-2].strip()
            remaining = ""
            
        if not potential_speaker:
            return (False, "", "")
            
        upper_count = sum(1 for c in potential_speaker if c in self.TURKISH_UPPER)
        letter_count = sum(1 for c in potential_speaker if c.isalpha())
        
        if letter_count < 3:
            return (False, "", "")
            
        uppercase_ratio = upper_count / letter_count if letter_count > 0 else 0
        if uppercase_ratio >= 0.7:
            return (True, potential_speaker, remaining)
        return (False, "", "")
    
    def parse_pages(self, pages: list) -> list[ParsedStatement]:
        statements = []
        current_speaker = ""
        current_buffer = []
        statement_start_page = 1
        
        for page in pages:
            page_num = page.page if hasattr(page, 'page') else 1
            text = page.text if hasattr(page, 'text') else str(page)
            lines = text.split("\n")
            
            for line in lines:
                if self.is_noise(line): continue
                is_speaker, speaker_name, remaining = self.is_new_speaker(line)
                
                if is_speaker:
                    if current_speaker and current_buffer:
                        full_text = " ".join(current_buffer).strip()
                        if len(full_text) >= self.min_statement_length:
                            statements.append(ParsedStatement(
                                speaker=normalize_speaker_name(current_speaker),
                                text=full_text,
                                page_number=statement_start_page,
                            ))
                    current_speaker = speaker_name
                    current_buffer = [remaining] if remaining else []
                    statement_start_page = page_num
                else:
                    if current_speaker:
                        current_buffer.append(line.strip())
                        
        if current_speaker and current_buffer:
            full_text = " ".join(current_buffer).strip()
            if len(full_text) >= self.min_statement_length:
                statements.append(ParsedStatement(
                    speaker=normalize_speaker_name(current_speaker),
                    text=full_text,
                    page_number=statement_start_page,
                ))
                
        return statements
