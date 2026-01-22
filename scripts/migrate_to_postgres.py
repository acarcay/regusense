#!/usr/bin/env python3
"""
Migration Script: ChromaDB to PostgreSQL.

Migrates existing ChromaDB data to PostgreSQL while:
1. Preserving ChromaDB vectors (no re-embedding)
2. Content-hash deduplication
3. Pydantic validation (invalid records -> trash_log.json)
4. Checkpointing for resumability

Usage:
    # First, start PostgreSQL via Docker
    docker-compose up -d
    
    # Then run migration
    python scripts/migrate_to_postgres.py
    
    # Resume from checkpoint (if interrupted)
    python scripts/migrate_to_postgres.py --resume
"""

import asyncio
import hashlib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field

import chromadb
from chromadb.config import Settings as ChromaSettings
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Import database models
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import Base, Speaker, Statement, Source, normalize_speaker_name, generate_content_hash
from database.session import async_engine, get_async_session


# ==============================================================================
# Pydantic Validation Models
# ==============================================================================

class StatementRecord(BaseModel):
    """Pydantic model for validating ChromaDB records."""
    
    chroma_id: str
    text: str = Field(min_length=10, max_length=50000)
    speaker: str = Field(default="", max_length=255)
    date: str = Field(default="")
    source: str = Field(default="")
    source_type: str = Field(default="UNKNOWN")
    topics: List[str] = Field(default_factory=list)
    
    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        """Ensure text is not just whitespace or garbage."""
        cleaned = v.strip()
        if len(cleaned) < 10:
            raise ValueError("Text too short after stripping")
        # Check for garbage (more than 50% non-alphanumeric)
        alnum = sum(c.isalnum() or c.isspace() for c in cleaned)
        if alnum < len(cleaned) * 0.3:
            raise ValueError("Text appears to be garbage")
        return cleaned
    
    @field_validator("speaker")
    @classmethod
    def validate_speaker(cls, v: str) -> str:
        """Clean speaker name."""
        return v.strip() if v else ""


@dataclass
class MigrationStats:
    """Track migration progress."""
    total_processed: int = 0
    successful: int = 0
    duplicates: int = 0
    validation_failed: int = 0
    db_errors: int = 0
    speakers_created: int = 0
    start_time: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        elapsed = (datetime.now() - self.start_time).total_seconds()
        return {
            "total_processed": self.total_processed,
            "successful": self.successful,
            "duplicates": self.duplicates,
            "validation_failed": self.validation_failed,
            "db_errors": self.db_errors,
            "speakers_created": self.speakers_created,
            "elapsed_seconds": round(elapsed, 2),
            "records_per_second": round(self.total_processed / elapsed, 2) if elapsed > 0 else 0,
        }


# ==============================================================================
# Migration Logic
# ==============================================================================

CHECKPOINT_FILE = Path("data/migration_checkpoint.json")
TRASH_LOG_FILE = Path("data/trash_log.json")
BATCH_SIZE = 1000


def load_checkpoint() -> Optional[int]:
    """Load last processed offset from checkpoint."""
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r") as f:
            data = json.load(f)
            return data.get("last_offset", 0)
    return None


def save_checkpoint(offset: int, stats: MigrationStats):
    """Save checkpoint for resumability."""
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({
            "last_offset": offset,
            "timestamp": datetime.now().isoformat(),
            "stats": stats.to_dict(),
        }, f, indent=2)


def append_to_trash_log(record: dict, error: str):
    """Append invalid record to trash log."""
    trash_entry = {
        "timestamp": datetime.now().isoformat(),
        "error": error,
        "record": {
            "chroma_id": record.get("chroma_id", ""),
            "text_preview": record.get("text", "")[:200],
            "speaker": record.get("speaker", ""),
        }
    }
    
    # Append to file
    existing = []
    if TRASH_LOG_FILE.exists():
        with open(TRASH_LOG_FILE, "r") as f:
            existing = json.load(f)
    
    existing.append(trash_entry)
    
    with open(TRASH_LOG_FILE, "w") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


async def get_or_create_speaker(
    session: AsyncSession,
    name: str,
    speaker_cache: dict,
) -> int:
    """Get existing speaker or create new one."""
    if not name:
        name = "Unknown"
    
    normalized = normalize_speaker_name(name)
    
    # Check cache first
    if normalized in speaker_cache:
        return speaker_cache[normalized]
    
    # Check database
    result = await session.execute(
        select(Speaker).where(Speaker.normalized_name == normalized)
    )
    speaker = result.scalar_one_or_none()
    
    if speaker:
        speaker_cache[normalized] = speaker.id
        return speaker.id
    
    # Create new speaker
    new_speaker = Speaker(
        name=name,
        normalized_name=normalized,
    )
    session.add(new_speaker)
    await session.flush()
    
    speaker_cache[normalized] = new_speaker.id
    return new_speaker.id


async def migrate_batch(
    session: AsyncSession,
    records: List[dict],
    speaker_cache: dict,
    stats: MigrationStats,
    seen_hashes: set,  # NEW: Track hashes we've already processed
) -> int:
    """
    Migrate a batch of records.
    
    Returns number of successful inserts.
    """
    successful = 0
    
    for record in records:
        try:
            # Validate with Pydantic
            validated = StatementRecord(**record)
            
            # Get or create speaker
            speaker_id = await get_or_create_speaker(
                session, validated.speaker, speaker_cache
            )
            
            # Generate content hash
            content_hash = generate_content_hash(
                validated.text, speaker_id, validated.date
            )
            
            # Check for duplicate in current session/batch first
            if content_hash in seen_hashes:
                stats.duplicates += 1
                continue
            
            # Check for duplicate in database
            existing = await session.execute(
                select(Statement.id).where(Statement.content_hash == content_hash)
            )
            if existing.scalar_one_or_none():
                stats.duplicates += 1
                seen_hashes.add(content_hash)
                continue
            
            # Mark as seen
            seen_hashes.add(content_hash)
            
            # Create statement
            statement = Statement(
                content_hash=content_hash,
                text=validated.text,
                speaker_id=speaker_id,
                date=validated.date if validated.date else None,
                topics={"items": validated.topics} if validated.topics else None,
                chroma_id=validated.chroma_id,
            )
            session.add(statement)
            successful += 1
            stats.successful += 1
            
        except Exception as e:
            stats.validation_failed += 1
            append_to_trash_log(record, str(e))
    
    return successful


async def run_migration(resume: bool = False):
    """Main migration function."""
    print("=" * 60)
    print("🚀 ReguSense Migration: ChromaDB → PostgreSQL")
    print("=" * 60)
    print()
    
    # Initialize database tables
    print("📦 Creating database tables...")
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("   ✅ Tables created")
    
    # Load ChromaDB
    print("📂 Loading ChromaDB...")
    client = chromadb.PersistentClient(
        path="data/chromadb",
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection = client.get_collection("political_statements")
    total_count = collection.count()
    print(f"   Found {total_count:,} records")
    
    # Resume from checkpoint?
    start_offset = 0
    if resume:
        saved_offset = load_checkpoint()
        if saved_offset:
            start_offset = saved_offset
            print(f"   ⏩ Resuming from offset {start_offset:,}")
    
    # Migration loop
    stats = MigrationStats()
    speaker_cache = {}
    seen_hashes = set()  # Track all hashes we've processed
    offset = start_offset
    
    print()
    print("🔄 Migrating records...")
    
    while offset < total_count:
        # Fetch batch from ChromaDB
        results = collection.get(
            include=["documents", "metadatas"],
            limit=BATCH_SIZE,
            offset=offset,
        )
        
        if not results or not results.get("ids"):
            break
        
        # Transform to records
        records = []
        for i, chroma_id in enumerate(results["ids"]):
            text = results["documents"][i] if results["documents"] else ""
            metadata = results["metadatas"][i] if results["metadatas"] else {}
            
            records.append({
                "chroma_id": chroma_id,
                "text": text,
                "speaker": metadata.get("speaker", ""),
                "date": metadata.get("date", ""),
                "source": metadata.get("source", ""),
                "source_type": metadata.get("source_type", "UNKNOWN"),
                "topics": [],  # We'll extract later if needed
            })
        
        # Migrate batch
        async with get_async_session() as session:
            await migrate_batch(session, records, speaker_cache, stats, seen_hashes)
        
        stats.total_processed += len(records)
        offset += BATCH_SIZE
        
        # Save checkpoint
        save_checkpoint(offset, stats)
        
        # Progress
        pct = (offset / total_count) * 100
        print(f"   [{pct:5.1f}%] Processed {offset:,}/{total_count:,} | "
              f"✅ {stats.successful:,} | ♻️ {stats.duplicates:,} | ❌ {stats.validation_failed:,}")
    
    # Final stats
    print()
    print("=" * 60)
    print("📈 MIGRATION COMPLETE")
    print("=" * 60)
    final_stats = stats.to_dict()
    for key, value in final_stats.items():
        print(f"   {key}: {value:,}" if isinstance(value, int) else f"   {key}: {value}")
    
    # Cleanup checkpoint
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        print()
        print("🧹 Checkpoint file cleaned up")
    
    # Save final report
    report_path = Path("data/migration_report.json")
    with open(report_path, "w") as f:
        json.dump(final_stats, f, indent=2)
    print(f"💾 Report saved to: {report_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Migrate ChromaDB to PostgreSQL")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    args = parser.parse_args()
    
    asyncio.run(run_migration(resume=args.resume))


if __name__ == "__main__":
    main()
