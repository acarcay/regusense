"""
PDF Report Generator for ReguSense Intelligence Reports.

Generates professional, branded PDF reports from JSON analysis data.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fpdf import FPDF

logger = logging.getLogger(__name__)


# === Color Palette ===
class Colors:
    """Brand color palette for ReguSense reports."""
    
    # Primary colors
    PRIMARY = (30, 58, 138)      # Deep blue
    SECONDARY = (59, 130, 246)  # Lighter blue
    
    # Risk level colors
    HIGH = (220, 38, 38)        # Red
    MEDIUM = (249, 115, 22)     # Orange
    LOW = (234, 179, 8)         # Yellow
    NOISE = (156, 163, 175)     # Gray
    
    # Text colors
    TEXT_DARK = (31, 41, 55)
    TEXT_LIGHT = (107, 114, 128)
    TEXT_WHITE = (255, 255, 255)
    
    # Background colors
    BG_LIGHT = (249, 250, 251)
    BG_CARD = (255, 255, 255)
    BG_SNIPPET = (243, 244, 246)
    
    # Accent
    ACCENT = (16, 185, 129)     # Green for highlights


class ReportGenerator:
    """
    Professional PDF Report Generator for ReguSense.
    
    Creates branded intelligence reports with:
    - Cover page with summary statistics
    - Sector-based grouping of findings
    - Risk cards with level badges
    - Actionable insights and evidence snippets
    """
    
    # Page dimensions (A4)
    PAGE_WIDTH = 210
    PAGE_HEIGHT = 297
    MARGIN = 15
    CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN
    
    def __init__(
        self,
        fonts_dir: str = "assets/fonts",
        output_dir: str = "data/reports",
    ):
        """
        Initialize the report generator.
        
        Args:
            fonts_dir: Directory containing Poppins font files
            output_dir: Directory for generated PDF reports
        """
        self.fonts_dir = Path(fonts_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.pdf: Optional[FPDF] = None
        self.report_data: dict = {}
        
    def _init_pdf(self) -> None:
        """Initialize PDF with fonts and settings."""
        self.pdf = FPDF()
        self.pdf.set_auto_page_break(auto=True, margin=20)
        
        # Register custom fonts
        semibold_path = self.fonts_dir / "Poppins-SemiBold.ttf"
        regular_path = self.fonts_dir / "Poppins-Regular.ttf"
        
        if semibold_path.exists():
            self.pdf.add_font("Poppins", "B", str(semibold_path))
            logger.info("Registered Poppins-SemiBold font")
        else:
            logger.warning(f"Font not found: {semibold_path}")
            
        if regular_path.exists():
            self.pdf.add_font("Poppins", "", str(regular_path))
            logger.info("Registered Poppins-Regular font")
        else:
            logger.warning(f"Font not found: {regular_path}")
    
    def _set_font(self, style: str = "", size: int = 10) -> None:
        """Set font with fallback to Helvetica if Poppins not available."""
        try:
            self.pdf.set_font("Poppins", style, size)
        except Exception:
            self.pdf.set_font("Helvetica", style, size)
    
    def _set_text_color(self, color: tuple) -> None:
        """Set text color from RGB tuple."""
        self.pdf.set_text_color(*color)
    
    def _set_fill_color(self, color: tuple) -> None:
        """Set fill color from RGB tuple."""
        self.pdf.set_fill_color(*color)
    
    def _set_draw_color(self, color: tuple) -> None:
        """Set draw color from RGB tuple."""
        self.pdf.set_draw_color(*color)
    
    def _get_risk_color(self, level: str) -> tuple:
        """Get color for risk level."""
        level_colors = {
            "HIGH": Colors.HIGH,
            "MEDIUM": Colors.MEDIUM,
            "LOW": Colors.LOW,
            "NOISE": Colors.NOISE,
        }
        return level_colors.get(level.upper(), Colors.NOISE)
    
    def create_cover_page(self) -> None:
        """Create the report cover page with summary."""
        self.pdf.add_page()
        
        # === Background gradient effect (header area) ===
        self._set_fill_color(Colors.PRIMARY)
        self.pdf.rect(0, 0, self.PAGE_WIDTH, 100, "F")
        
        # === Brand Logo/Title ===
        self._set_text_color(Colors.TEXT_WHITE)
        self._set_font("B", 36)
        self.pdf.set_xy(self.MARGIN, 25)
        self.pdf.cell(self.CONTENT_WIDTH, 15, "ReguSense", align="C")
        
        # Subtitle
        self._set_font("", 14)
        self.pdf.set_xy(self.MARGIN, 45)
        self.pdf.cell(self.CONTENT_WIDTH, 8, "Yasama Riski Istihbarat Raporu", align="C")
        
        # Date
        self._set_font("", 10)
        self.pdf.set_xy(self.MARGIN, 58)
        date_str = datetime.now().strftime("%d.%m.%Y")
        self.pdf.cell(self.CONTENT_WIDTH, 6, date_str, align="C")
        
        # === CONFIDENTIAL watermark ===
        self._set_text_color((200, 200, 200))
        self._set_font("B", 48)
        self.pdf.set_xy(self.MARGIN, 85)
        self.pdf.cell(self.CONTENT_WIDTH, 20, "GIZLI", align="C")
        
        # === Summary Statistics Box ===
        summary = self.report_data.get("summary", {})
        
        # Box background
        box_y = 130
        self._set_fill_color(Colors.BG_LIGHT)
        self._set_draw_color(Colors.SECONDARY)
        self.pdf.set_line_width(0.5)
        self.pdf.rect(self.MARGIN, box_y, self.CONTENT_WIDTH, 60, "DF")
        
        # Title
        self._set_text_color(Colors.PRIMARY)
        self._set_font("B", 14)
        self.pdf.set_xy(self.MARGIN + 5, box_y + 5)
        self.pdf.cell(self.CONTENT_WIDTH - 10, 8, "Yonetici Ozeti", align="L")
        
        # Stats grid
        stats = [
            ("Analiz Edilen", str(summary.get("total_analyzed", 0))),
            ("Gercek Risk", str(summary.get("genuine_risks", 0))),
            ("Filtrelenen", str(summary.get("noise_filtered", 0))),
            ("Yuksek Oncelik", str(summary.get("high_priority", 0))),
        ]
        
        col_width = (self.CONTENT_WIDTH - 20) / 4
        start_x = self.MARGIN + 10
        stat_y = box_y + 22
        
        for i, (label, value) in enumerate(stats):
            x = start_x + i * col_width
            
            # Value (large)
            self._set_text_color(Colors.PRIMARY)
            self._set_font("B", 24)
            self.pdf.set_xy(x, stat_y)
            self.pdf.cell(col_width, 12, value, align="C")
            
            # Label (small)
            self._set_text_color(Colors.TEXT_LIGHT)
            self._set_font("", 9)
            self.pdf.set_xy(x, stat_y + 14)
            self.pdf.cell(col_width, 6, label, align="C")
        
        # === High Priority Alert Box (if any) ===
        high_priority = summary.get("high_priority", 0)
        if high_priority > 0:
            alert_y = 205
            self._set_fill_color(Colors.HIGH)
            self.pdf.rect(self.MARGIN, alert_y, self.CONTENT_WIDTH, 30, "F")
            
            self._set_text_color(Colors.TEXT_WHITE)
            self._set_font("B", 12)
            self.pdf.set_xy(self.MARGIN + 10, alert_y + 5)
            self.pdf.cell(self.CONTENT_WIDTH - 20, 8, f"! {high_priority} YUKSEK ONCELIKLI UYARI", align="L")
            
            self._set_font("", 10)
            self.pdf.set_xy(self.MARGIN + 10, alert_y + 15)
            self.pdf.cell(self.CONTENT_WIDTH - 20, 8, "Kritik yasama riskleri icin acil ilgi gerekiyor.", align="L")
        
        # === Footer ===
        self._set_text_color(Colors.TEXT_LIGHT)
        self._set_font("", 8)
        self.pdf.set_xy(self.MARGIN, self.PAGE_HEIGHT - 25)
        self.pdf.cell(self.CONTENT_WIDTH, 5, "Bu rapor ReguSense AI tarafindan otomatik olusturulmustur.", align="C")
        self.pdf.set_xy(self.MARGIN, self.PAGE_HEIGHT - 18)
        self.pdf.cell(self.CONTENT_WIDTH, 5, "(c) 2025 ReguSense. Tum haklari saklidir.", align="C")
    
    def add_sector_section(self, sector: str, risks: list) -> None:
        """
        Add a section for a specific sector with its risks.
        
        Args:
            sector: Sector name (e.g., "CRYPTO", "FINTECH")
            risks: List of risk dictionaries for this sector
        """
        self.pdf.add_page()
        
        # === Sector Header ===
        self._set_fill_color(Colors.PRIMARY)
        self.pdf.rect(0, 0, self.PAGE_WIDTH, 35, "F")
        
        self._set_text_color(Colors.TEXT_WHITE)
        self._set_font("B", 20)
        self.pdf.set_xy(self.MARGIN, 10)
        self.pdf.cell(self.CONTENT_WIDTH, 12, f"Sektor: {sector}", align="L")
        
        # Risk count
        self._set_font("", 11)
        self.pdf.set_xy(self.MARGIN, 22)
        self.pdf.cell(self.CONTENT_WIDTH, 6, f"{len(risks)} risk tespit edildi", align="L")
        
        # === Risk Cards ===
        y_pos = 45
        
        for i, risk in enumerate(risks):
            # Check if we need a new page
            if y_pos > self.PAGE_HEIGHT - 80:
                self.pdf.add_page()
                y_pos = 20
            
            card_height = self._draw_risk_card(risk, y_pos)
            y_pos += card_height + 10
    
    def _draw_risk_card(self, risk: dict, y_start: float) -> float:
        """
        Draw a risk card with badge, summary, insight, and snippet.
        
        Args:
            risk: Risk dictionary
            y_start: Starting Y position
            
        Returns:
            Height of the drawn card
        """
        x = self.MARGIN
        y = y_start
        card_width = self.CONTENT_WIDTH
        
        # === Card Background ===
        self._set_fill_color(Colors.BG_CARD)
        self._set_draw_color((229, 231, 235))  # Light gray border
        self.pdf.set_line_width(0.3)
        
        # We'll draw the background after calculating height
        content_start_y = y
        
        # === Risk Level Badge ===
        level = risk.get("risk_level", "LOW").upper()
        badge_color = self._get_risk_color(level)
        
        badge_width = 25
        badge_height = 8
        self._set_fill_color(badge_color)
        self.pdf.rect(x + 5, y + 5, badge_width, badge_height, "F")
        
        self._set_text_color(Colors.TEXT_WHITE)
        self._set_font("B", 8)
        self.pdf.set_xy(x + 5, y + 6)
        self.pdf.cell(badge_width, 6, level, align="C")
        
        # Page number
        self._set_text_color(Colors.TEXT_LIGHT)
        self._set_font("", 8)
        page_num = risk.get("page_number", "?")
        self.pdf.set_xy(x + card_width - 40, y + 6)
        self.pdf.cell(35, 6, f"Page {page_num}", align="R")
        
        y += 18
        
        # === Summary (Bold) ===
        self._set_text_color(Colors.TEXT_DARK)
        self._set_font("B", 10)
        self.pdf.set_xy(x + 5, y)
        
        summary_text = risk.get("summary", "No summary available.")
        # Truncate if too long
        if len(summary_text) > 300:
            summary_text = summary_text[:297] + "..."
        
        self.pdf.multi_cell(card_width - 10, 5, summary_text, align="L")
        y = self.pdf.get_y() + 3
        
        # === Speaker Info (if available) ===
        speaker = risk.get("speaker_identified", "")
        if speaker and speaker != "Bilinmiyor":
            self._set_text_color(Colors.ACCENT)
            self._set_font("", 8)
            self.pdf.set_xy(x + 5, y)
            self.pdf.cell(card_width - 10, 4, f"Konusmaci: {speaker}", align="L")
            y += 6
        
        # === Executive Analysis Grid ===
        business_impact = risk.get("business_impact", "")
        tone = risk.get("tone_analysis", "")
        likelihood = risk.get("likelihood", "")
        compliance = risk.get("compliance_difficulty", "")
        
        # Only show grid if we have executive fields
        if any([business_impact, tone, likelihood, compliance]):
            # Draw a subtle background for the executive section
            exec_start_y = y
            self._set_fill_color((248, 250, 252))  # Very light blue-gray
            
            # Business Impact (most important - full width)
            if business_impact:
                self._set_text_color(Colors.PRIMARY)
                self._set_font("B", 8)
                self.pdf.set_xy(x + 5, y)
                self.pdf.cell(card_width - 10, 4, "IS ETKISI:", align="L")
                y += 5
                
                self._set_text_color(Colors.TEXT_DARK)
                self._set_font("", 8)
                self.pdf.set_xy(x + 5, y)
                # Truncate if too long
                if len(business_impact) > 400:
                    business_impact = business_impact[:397] + "..."
                self.pdf.multi_cell(card_width - 10, 4, business_impact, align="L")
                y = self.pdf.get_y() + 3
            
            # Metrics row: Tone | Likelihood | Compliance
            if tone or likelihood or compliance:
                metrics_y = y
                col_width = (card_width - 15) / 3
                
                # Tone Analysis
                if tone:
                    tone_color = Colors.HIGH if tone == "Hostile" else (Colors.MEDIUM if tone == "Neutral" else Colors.LOW)
                    self._set_fill_color(tone_color)
                    self.pdf.rect(x + 5, metrics_y, col_width - 5, 10, "F")
                    self._set_text_color(Colors.TEXT_WHITE)
                    self._set_font("B", 7)
                    self.pdf.set_xy(x + 5, metrics_y + 1)
                    self.pdf.cell(col_width - 5, 4, "TON", align="C")
                    self._set_font("", 7)
                    self.pdf.set_xy(x + 5, metrics_y + 5)
                    self.pdf.cell(col_width - 5, 4, tone, align="C")
                
                # Likelihood
                if likelihood:
                    like_color = Colors.HIGH if likelihood.lower() == "high" else Colors.LOW
                    self._set_fill_color(like_color)
                    self.pdf.rect(x + 5 + col_width, metrics_y, col_width - 5, 10, "F")
                    self._set_text_color(Colors.TEXT_WHITE)
                    self._set_font("B", 7)
                    self.pdf.set_xy(x + 5 + col_width, metrics_y + 1)
                    self.pdf.cell(col_width - 5, 4, "OLASILIK", align="C")
                    self._set_font("", 7)
                    self.pdf.set_xy(x + 5 + col_width, metrics_y + 5)
                    self.pdf.cell(col_width - 5, 4, likelihood, align="C")
                
                # Compliance Difficulty
                if compliance:
                    comp_color = Colors.HIGH if compliance.lower() == "hard" else (Colors.MEDIUM if compliance.lower() == "medium" else Colors.LOW)
                    self._set_fill_color(comp_color)
                    self.pdf.rect(x + 5 + col_width * 2, metrics_y, col_width - 5, 10, "F")
                    self._set_text_color(Colors.TEXT_WHITE)
                    self._set_font("B", 7)
                    self.pdf.set_xy(x + 5 + col_width * 2, metrics_y + 1)
                    self.pdf.cell(col_width - 5, 4, "UYUM", align="C")
                    self._set_font("", 7)
                    self.pdf.set_xy(x + 5 + col_width * 2, metrics_y + 5)
                    self.pdf.cell(col_width - 5, 4, compliance, align="C")
                
                y = metrics_y + 13
        
        # === Actionable Insight (in gray box) ===
        insight = risk.get("actionable_insight", "")
        if insight:
            insight_start_y = y
            self._set_fill_color(Colors.BG_SNIPPET)
            
            # Calculate insight height
            self._set_font("", 9)
            insight_lines = self.pdf.multi_cell(
                card_width - 20, 5, insight, 
                align="L", dry_run=True, output="LINES"
            )
            insight_height = len(insight_lines) * 5 + 8
            
            self.pdf.rect(x + 5, y, card_width - 10, insight_height, "F")
            
            self._set_text_color(Colors.ACCENT)
            self._set_font("B", 8)
            self.pdf.set_xy(x + 8, y + 2)
            self.pdf.cell(50, 4, "EYLEM ONERISI", align="L")
            
            self._set_text_color(Colors.TEXT_DARK)
            self._set_font("", 9)
            self.pdf.set_xy(x + 8, y + 7)
            self.pdf.multi_cell(card_width - 20, 5, insight, align="L")
            y = self.pdf.get_y() + 5
        
        # === Snippet (monospace, evidence) ===
        snippet = risk.get("snippet", "")
        if snippet:
            self._set_text_color(Colors.TEXT_LIGHT)
            self._set_font("", 8)
            self.pdf.set_xy(x + 5, y)
            self.pdf.cell(50, 4, "Kaynak Kanit:", align="L")
            y += 5
            
            # Truncate snippet
            if len(snippet) > 250:
                snippet = snippet[:247] + "..."
            
            self._set_fill_color(Colors.BG_SNIPPET)
            
            # Use Poppins for Turkish character support (smaller size for code-like appearance)
            self._set_font("", 7)
            
            self._set_text_color(Colors.TEXT_DARK)
            self.pdf.set_xy(x + 5, y)
            self.pdf.multi_cell(card_width - 10, 4, snippet.strip(), align="L")
            y = self.pdf.get_y() + 3
        
        # Calculate total card height
        card_height = y - content_start_y + 5
        
        # Draw card border
        self._set_draw_color((229, 231, 235))
        self.pdf.rect(x, content_start_y, card_width, card_height, "D")
        
        # Left accent bar based on risk level
        self._set_fill_color(badge_color)
        self.pdf.rect(x, content_start_y, 3, card_height, "F")
        
        return card_height
    
    def add_footer(self) -> None:
        """Add footer to all pages."""
        for i in range(1, self.pdf.page_no() + 1):
            self.pdf.page = i
            self._set_text_color(Colors.TEXT_LIGHT)
            self._set_font("", 8)
            self.pdf.set_xy(self.MARGIN, self.PAGE_HEIGHT - 12)
            self.pdf.cell(self.CONTENT_WIDTH / 2, 5, "ReguSense Intelligence Report", align="L")
            self.pdf.set_xy(self.MARGIN + self.CONTENT_WIDTH / 2, self.PAGE_HEIGHT - 12)
            self.pdf.cell(self.CONTENT_WIDTH / 2, 5, f"Page {i} of {self.pdf.page_no()}", align="R")
    
    def generate_report(self, json_path: str) -> str:
        """
        Generate a PDF report from JSON analysis data.
        
        Args:
            json_path: Path to the JSON report file
            
        Returns:
            Path to the generated PDF file
        """
        # Load JSON data
        with open(json_path, "r", encoding="utf-8") as f:
            self.report_data = json.load(f)
        
        logger.info(f"Loaded report data from {json_path}")
        
        # Initialize PDF
        self._init_pdf()
        
        # Create cover page
        self.create_cover_page()
        
        # Group risks by sector
        verified_risks = self.report_data.get("verified_risks", [])
        sectors: dict[str, list] = {}
        
        for risk in verified_risks:
            sector = risk.get("sector", "UNKNOWN")
            if sector not in sectors:
                sectors[sector] = []
            sectors[sector].append(risk)
        
        # Sort sectors and risks
        for sector in sorted(sectors.keys()):
            # Sort by risk level (HIGH > MEDIUM > LOW > NOISE)
            level_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "NOISE": 3}
            sector_risks = sorted(
                sectors[sector],
                key=lambda r: level_order.get(r.get("risk_level", "LOW").upper(), 3)
            )
            self.add_sector_section(sector, sector_risks)
        
        # Add footers
        self.add_footer()
        
        # Generate output filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = self.output_dir / f"intelligence_report_{timestamp}.pdf"
        
        # Save PDF
        self.pdf.output(str(output_path))
        logger.info(f"PDF report generated: {output_path}")
        
        return str(output_path)
    
    @staticmethod
    def get_latest_json_report(data_dir: str = "data/processed") -> Optional[str]:
        """
        Get the path to the most recent JSON report.
        
        Args:
            data_dir: Directory containing JSON reports
            
        Returns:
            Path to the latest JSON file, or None if not found
        """
        data_path = Path(data_dir)
        if not data_path.exists():
            return None
        
        json_files = list(data_path.glob("report_*.json"))
        if not json_files:
            return None
        
        # Sort by modification time
        latest = max(json_files, key=lambda p: p.stat().st_mtime)
        return str(latest)


def generate_report(
    json_path: Optional[str] = None,
    fonts_dir: str = "assets/fonts",
    output_dir: str = "data/reports",
) -> str:
    """
    Convenience function to generate a PDF report.
    
    Args:
        json_path: Path to JSON report (or auto-detect latest)
        fonts_dir: Directory containing font files
        output_dir: Directory for output PDF
        
    Returns:
        Path to generated PDF file
    """
    generator = ReportGenerator(fonts_dir=fonts_dir, output_dir=output_dir)
    
    if json_path is None:
        json_path = generator.get_latest_json_report()
        if json_path is None:
            raise FileNotFoundError("No JSON report found in data/processed/")
    
    return generator.generate_report(json_path)


# === CLI Entry Point ===
if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    try:
        # Get JSON path from args or auto-detect
        json_path = sys.argv[1] if len(sys.argv) > 1 else None
        pdf_path = generate_report(json_path)
        print(f"\n✅ PDF report generated: {pdf_path}")
    except Exception as e:
        print(f"\n❌ Error generating report: {e}")
        sys.exit(1)
