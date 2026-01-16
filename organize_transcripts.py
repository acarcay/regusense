"""
Transcript Organizer - Organize PDFs by Commission and Date.

Organizes downloaded TBMM transcripts into a structured folder hierarchy:
    data/organized/
    ├── PLAN_BUTCE/
    │   ├── 2021/
    │   │   ├── 01-Ocak/
    │   │   ├── 02-Subat/
    │   │   └── ...
    │   ├── 2022/
    │   └── ...
    ├── ADALET/
    └── ...

Usage:
    python organize_transcripts.py                    # Organize all PDFs
    python organize_transcripts.py --dry-run          # Preview without moving
    python organize_transcripts.py --copy             # Copy instead of move

Author: ReguSense Team
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Turkish month names
TURKISH_MONTHS = {
    1: "01-Ocak",
    2: "02-Subat",
    3: "03-Mart",
    4: "04-Nisan",
    5: "05-Mayis",
    6: "06-Haziran",
    7: "07-Temmuz",
    8: "08-Agustos",
    9: "09-Eylul",
    10: "10-Ekim",
    11: "11-Kasim",
    12: "12-Aralik",
}

# Commission names for folder creation
COMMISSION_NAMES = {
    "PLAN_BUTCE": "Plan_ve_Butce",
    "SANAYI_ENERJI": "Sanayi_Enerji",
    "BAYINDIRLIK": "Bayindirlik_Imar",
    "DIJITAL_MECRALAR": "Dijital_Mecralar",
    "ADALET": "Adalet",
}


@dataclass
class TranscriptFile:
    """Represents a transcript PDF file."""
    path: Path
    date: Optional[datetime] = None
    commission: str = "UNKNOWN"
    transcript_id: str = ""
    
    @classmethod
    def from_path(cls, path: Path, manifest: Optional[dict] = None) -> "TranscriptFile":
        """Parse transcript info from filename or manifest."""
        filename = path.stem
        
        # Try to extract date from filename (YYYY-MM-DD_...)
        date_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})_", filename)
        date = None
        if date_match:
            try:
                year, month, day = date_match.groups()
                date = datetime(int(year), int(month), int(day))
            except ValueError:
                pass
        
        # Extract transcript ID
        id_match = re.search(r"_(\d{4,5})_", filename)
        transcript_id = id_match.group(1) if id_match else ""
        
        # Try to get commission from manifest
        commission = "UNKNOWN"
        if manifest and transcript_id in manifest:
            commission = manifest[transcript_id].get("commission", "UNKNOWN")
        
        return cls(
            path=path,
            date=date,
            commission=commission,
            transcript_id=transcript_id,
        )
    
    @property
    def year(self) -> str:
        """Get year as string."""
        return str(self.date.year) if self.date else "Unknown"
    
    @property
    def month_folder(self) -> str:
        """Get Turkish month folder name."""
        if self.date:
            return TURKISH_MONTHS.get(self.date.month, f"{self.date.month:02d}")
        return "Unknown"
    
    @property
    def commission_folder(self) -> str:
        """Get commission folder name."""
        return COMMISSION_NAMES.get(self.commission, self.commission)


class TranscriptOrganizer:
    """Organizes transcript PDFs into structured folders."""
    
    def __init__(
        self,
        source_dir: Path,
        target_dir: Path,
        manifest_path: Optional[Path] = None,
    ):
        """
        Initialize the organizer.
        
        Args:
            source_dir: Directory containing PDF files
            target_dir: Directory to organize files into
            manifest_path: Optional path to transcript manifest JSON
        """
        self.source_dir = Path(source_dir)
        self.target_dir = Path(target_dir)
        self.manifest = self._load_manifest(manifest_path)
        
    def _load_manifest(self, manifest_path: Optional[Path]) -> dict:
        """Load transcript manifest for commission mapping."""
        manifest = {}
        
        if manifest_path and manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                for item in data:
                    transcript_id = item.get("id", "")
                    if transcript_id:
                        manifest[transcript_id] = item
                logger.info(f"Loaded manifest with {len(manifest)} entries")
            except Exception as e:
                logger.warning(f"Failed to load manifest: {e}")
        
        return manifest
    
    def scan_files(self) -> list[TranscriptFile]:
        """Scan source directory for PDF files."""
        pdfs = list(self.source_dir.glob("*.pdf"))
        logger.info(f"Found {len(pdfs)} PDF files in {self.source_dir}")
        
        files = []
        for pdf_path in pdfs:
            tf = TranscriptFile.from_path(pdf_path, self.manifest)
            files.append(tf)
        
        return files
    
    def get_target_path(self, tf: TranscriptFile) -> Path:
        """Calculate target path for a transcript file."""
        # Structure: target_dir/Commission/Year/Month/filename.pdf
        return (
            self.target_dir
            / tf.commission_folder
            / tf.year
            / tf.month_folder
            / tf.path.name
        )
    
    def organize(
        self,
        dry_run: bool = False,
        copy_mode: bool = False,
    ) -> dict:
        """
        Organize all PDF files into structured folders.
        
        Args:
            dry_run: If True, preview without moving/copying
            copy_mode: If True, copy files instead of moving
            
        Returns:
            Statistics dictionary
        """
        files = self.scan_files()
        
        stats = {
            "total_files": len(files),
            "organized": 0,
            "skipped": 0,
            "errors": 0,
            "by_commission": {},
            "by_year": {},
        }
        
        for tf in files:
            target_path = self.get_target_path(tf)
            
            # Track statistics
            if tf.commission not in stats["by_commission"]:
                stats["by_commission"][tf.commission] = 0
            stats["by_commission"][tf.commission] += 1
            
            if tf.year not in stats["by_year"]:
                stats["by_year"][tf.year] = 0
            stats["by_year"][tf.year] += 1
            
            if dry_run:
                logger.debug(f"Would organize: {tf.path.name} -> {target_path}")
                stats["organized"] += 1
                continue
            
            try:
                # Create target directory
                target_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Check if already exists
                if target_path.exists():
                    logger.debug(f"Skipping (exists): {target_path.name}")
                    stats["skipped"] += 1
                    continue
                
                # Move or copy
                if copy_mode:
                    shutil.copy2(tf.path, target_path)
                    logger.debug(f"Copied: {tf.path.name}")
                else:
                    shutil.move(str(tf.path), str(target_path))
                    logger.debug(f"Moved: {tf.path.name}")
                
                stats["organized"] += 1
                
            except Exception as e:
                logger.error(f"Error organizing {tf.path.name}: {e}")
                stats["errors"] += 1
        
        return stats
    
    def print_tree(self, max_depth: int = 3) -> None:
        """Print folder structure preview."""
        files = self.scan_files()
        
        # Build tree structure
        tree = {}
        for tf in files:
            commission = tf.commission_folder
            year = tf.year
            month = tf.month_folder
            
            if commission not in tree:
                tree[commission] = {}
            if year not in tree[commission]:
                tree[commission][year] = {}
            if month not in tree[commission][year]:
                tree[commission][year][month] = 0
            tree[commission][year][month] += 1
        
        # Print tree
        print(f"\n📁 {self.target_dir}")
        for commission in sorted(tree.keys()):
            print(f"├── 📂 {commission}/")
            years = sorted(tree[commission].keys(), reverse=True)
            for i, year in enumerate(years):
                is_last_year = i == len(years) - 1
                prefix = "    └── " if is_last_year else "    ├── "
                print(f"{prefix}📂 {year}/")
                
                months = sorted(tree[commission][year].keys())
                for j, month in enumerate(months):
                    count = tree[commission][year][month]
                    is_last_month = j == len(months) - 1
                    inner_prefix = "        └── " if is_last_month else "        ├── "
                    if not is_last_year:
                        inner_prefix = "    │   └── " if is_last_month else "    │   ├── "
                    print(f"{inner_prefix}📄 {month}/ ({count} dosya)")


def main():
    parser = argparse.ArgumentParser(
        description="Organize TBMM transcripts by commission and date"
    )
    parser.add_argument(
        "--source", "-s",
        type=str,
        default="data/raw/contracts",
        help="Source directory with PDFs",
    )
    parser.add_argument(
        "--target", "-t",
        type=str,
        default="data/organized",
        help="Target directory for organized files",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Preview without moving/copying files",
    )
    parser.add_argument(
        "--copy", "-c",
        action="store_true",
        help="Copy files instead of moving",
    )
    parser.add_argument(
        "--tree",
        action="store_true",
        help="Show folder structure preview",
    )
    
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("  TBMM Transcript Organizer")
    print("=" * 60)
    print(f"  Source: {args.source}")
    print(f"  Target: {args.target}")
    print(f"  Mode: {'Dry Run' if args.dry_run else ('Copy' if args.copy else 'Move')}")
    print("=" * 60 + "\n")
    
    # Find manifest
    manifest_path = Path("data/processed/transcript_manifest.json")
    
    organizer = TranscriptOrganizer(
        source_dir=Path(args.source),
        target_dir=Path(args.target),
        manifest_path=manifest_path if manifest_path.exists() else None,
    )
    
    if args.tree:
        organizer.print_tree()
        return
    
    # Organize files
    stats = organizer.organize(
        dry_run=args.dry_run,
        copy_mode=args.copy,
    )
    
    # Print summary
    print("\n📊 Özet:")
    print(f"   Toplam dosya: {stats['total_files']}")
    print(f"   Organize edilen: {stats['organized']}")
    print(f"   Atlanan (mevcut): {stats['skipped']}")
    print(f"   Hata: {stats['errors']}")
    
    print("\n📂 Komisyonlara göre:")
    for commission, count in sorted(stats["by_commission"].items()):
        name = COMMISSION_NAMES.get(commission, commission)
        print(f"   {name}: {count} dosya")
    
    print("\n📅 Yıllara göre:")
    for year, count in sorted(stats["by_year"].items(), reverse=True):
        print(f"   {year}: {count} dosya")
    
    # Show tree preview after organizing
    if not args.dry_run:
        print("\n✅ Dosyalar organize edildi!")
        print(f"   Hedef klasör: {args.target}")
    
    organizer.print_tree()
    print()


if __name__ == "__main__":
    main()
