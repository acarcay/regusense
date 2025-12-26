"""
PDF Processor Module.

Extracts text from PDF transcripts with page number tracking and
header/footer removal for clean text analysis.

Author: ReguSense Team
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)


@dataclass
class PageContent:
    """
    Represents extracted text content from a single PDF page.

    Attributes:
        page: Page number (1-indexed)
        text: Cleaned text content from the page
        raw_text: Original text before cleaning (for debugging)
    """

    page: int
    text: str
    raw_text: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary format for serialization."""
        return {"page": self.page, "text": self.text}


class PDFProcessor:
    """
    PDF text extraction processor using pdfplumber.

    Handles TBMM transcript PDFs, extracting text page by page with
    automatic header/footer removal and page number tracking.

    Example:
        processor = PDFProcessor()
        pages = processor.extract_text("data/raw/contracts/transcript.pdf")
        for page in pages:
            print(f"Page {page.page}: {page.text[:100]}...")
    """

    # Common headers/footers to remove from TBMM transcripts
    HEADER_PATTERNS = [
        r"TBMM\s+Tutanak\s+Hizmetleri",
        r"Türkiye\s+Büyük\s+Millet\s+Meclisi",
        r"İhtisas\s+Komisyonu\s+Tutanağı",
        r"Adalet\s+Komisyonu",
        r"^\s*-\s*\d+\s*-\s*$",  # Page number format: "- 1 -"
    ]

    FOOTER_PATTERNS = [
        r"^\s*\d+\s*$",  # Standalone page numbers
        r"Sayfa\s*:\s*\d+",  # "Sayfa: 1" format
        r"^\s*-\s*\d+\s*-\s*$",  # Page number format: "- 1 -"
    ]

    def __init__(
        self,
        remove_headers: bool = True,
        remove_footers: bool = True,
        min_text_length: int = 50,
    ) -> None:
        """
        Initialize the PDF processor.

        Args:
            remove_headers: Whether to remove detected headers
            remove_footers: Whether to remove detected footers
            min_text_length: Minimum text length per page to include
        """
        self.remove_headers = remove_headers
        self.remove_footers = remove_footers
        self.min_text_length = min_text_length

        # Compile regex patterns for efficiency
        self._header_patterns = [
            re.compile(p, re.IGNORECASE | re.MULTILINE)
            for p in self.HEADER_PATTERNS
        ]
        self._footer_patterns = [
            re.compile(p, re.IGNORECASE | re.MULTILINE)
            for p in self.FOOTER_PATTERNS
        ]

    def _clean_text(self, text: str) -> str:
        """
        Clean extracted text by removing headers, footers, and normalizing whitespace.

        Args:
            text: Raw text extracted from PDF page

        Returns:
            Cleaned text with headers/footers removed
        """
        if not text:
            return ""

        cleaned = text

        # Remove headers if enabled
        if self.remove_headers:
            for pattern in self._header_patterns:
                cleaned = pattern.sub("", cleaned)

        # Remove footers if enabled
        if self.remove_footers:
            for pattern in self._footer_patterns:
                cleaned = pattern.sub("", cleaned)

        # Normalize whitespace
        # Replace multiple spaces with single space
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        # Replace multiple newlines with double newline (paragraph break)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        # Strip leading/trailing whitespace
        cleaned = cleaned.strip()

        return cleaned

    def extract_text(self, pdf_path: str | Path) -> list[PageContent]:
        """
        Extract text from all pages of a PDF file.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            List of PageContent objects with page numbers and cleaned text

        Raises:
            FileNotFoundError: If PDF file doesn't exist
            Exception: If PDF processing fails
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        logger.info(f"Processing PDF: {pdf_path}")
        pages: list[PageContent] = []

        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                logger.info(f"PDF has {total_pages} pages")

                for i, page in enumerate(pdf.pages, start=1):
                    raw_text = page.extract_text() or ""
                    cleaned_text = self._clean_text(raw_text)

                    # Only include pages with meaningful content
                    if len(cleaned_text) >= self.min_text_length:
                        page_content = PageContent(
                            page=i,
                            text=cleaned_text,
                            raw_text=raw_text,
                        )
                        pages.append(page_content)
                        logger.debug(
                            f"Page {i}: {len(cleaned_text)} chars extracted"
                        )
                    else:
                        logger.debug(
                            f"Page {i}: Skipped (only {len(cleaned_text)} chars)"
                        )

        except Exception as e:
            logger.error(f"Failed to process PDF: {e}")
            raise

        logger.info(
            f"Extracted text from {len(pages)}/{total_pages} pages "
            f"(skipped {total_pages - len(pages)} empty/short pages)"
        )

        return pages

    def extract_text_as_dicts(self, pdf_path: str | Path) -> list[dict]:
        """
        Extract text and return as list of dictionaries.

        This is a convenience method that returns the data in the format
        specified in the requirements: [{'page': 1, 'text': '...'}, ...]

        Args:
            pdf_path: Path to the PDF file

        Returns:
            List of dictionaries with 'page' and 'text' keys
        """
        pages = self.extract_text(pdf_path)
        return [p.to_dict() for p in pages]

    def get_full_text(self, pdf_path: str | Path) -> str:
        """
        Extract and concatenate all text from a PDF.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            Single string with all page text concatenated
        """
        pages = self.extract_text(pdf_path)
        return "\n\n".join(f"[Page {p.page}]\n{p.text}" for p in pages)

    def get_page_count(self, pdf_path: str | Path) -> int:
        """
        Get the total number of pages in a PDF.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            Number of pages in the PDF
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        with pdfplumber.open(pdf_path) as pdf:
            return len(pdf.pages)


# Module-level convenience function
def process_pdf(pdf_path: str | Path) -> list[dict]:
    """
    Convenience function to process a PDF and return page content.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        List of dictionaries with 'page' and 'text' keys
    """
    processor = PDFProcessor()
    return processor.extract_text_as_dicts(pdf_path)
