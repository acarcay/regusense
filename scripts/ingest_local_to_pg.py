import argparse
import asyncio
import logging
from pathlib import Path
import re
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.session import get_async_session
from database.models import RawDocument, DocumentType, DocumentStatus, Statement, Speaker, generate_content_hash
from processors.pdf_processor import PDFProcessor
from processors.transcript_parser import TranscriptParser
from sqlalchemy import select

from core.logging_config import setup_logging
setup_logging(level="INFO")
logger = logging.getLogger(__name__)

def extract_date_from_filename(filename: str) -> str:
    # Try YYYY-MM-DD
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", filename)
    if match:
        return match.group(1)
    
    # Try DDMMYYYY
    match = re.search(r"(\d{2})(\d{2})(\d{4})_Tarihli", filename)
    if match:
        day, month, year = match.groups()
        return f"{year}-{month}-{day}"
    
    return datetime.now().strftime("%Y-%m-%d")

async def process_directory(directory: str, limit: int = None):
    dir_path = Path(directory)
    if not dir_path.exists() or not dir_path.is_dir():
        logger.error(f"Directory not found: {dir_path}")
        return
    
    pdf_files = list(dir_path.glob("*.pdf"))
    if not pdf_files:
        logger.warning(f"No PDF files found in {dir_path}")
        return
        
    if limit:
        pdf_files = pdf_files[:limit]
        
    logger.info(f"Found {len(pdf_files)} PDF files. Starting ingestion to PostgreSQL...")
    
    processor = PDFProcessor(min_text_length=10)
    
    success_count = 0
    duplicate_count = 0
    error_count = 0
    
    async with get_async_session() as db:
        for idx, pdf_path in enumerate(pdf_files, 1):
            try:
                logger.info(f"[{idx}/{len(pdf_files)}] Processing: {pdf_path.name}")
                
                # Extract pages using PDFProcessor
                pages = processor.extract_text(pdf_path)
                
                if not pages:
                    logger.warning(f"Extracted text is empty for {pdf_path.name}")
                    error_count += 1
                    continue
                    
                # Parse statements
                t_parser = TranscriptParser()
                parsed_statements = t_parser.parse_pages(pages)
                
                if not parsed_statements:
                    logger.warning(f"No valid statements found in {pdf_path.name}")
                    error_count += 1
                    continue
                
                # Combine full text just for RawDocument record
                raw_text = "\n\n".join(p.text for p in pages)
                content_hash = RawDocument.compute_hash(raw_text)
                
                # Check for duplicates
                result = await db.execute(
                    select(RawDocument).where(RawDocument.content_hash == content_hash)
                )
                existing_doc = result.scalar_one_or_none()
                
                if existing_doc:
                    logger.info(f"  -> Skipping. Already exists with status: {existing_doc.processing_status}")
                    duplicate_count += 1
                    continue
                
                # Create RawDocument
                doc_date = extract_date_from_filename(pdf_path.name)
                
                doc = RawDocument(
                    doc_type=DocumentType.TBMM_TRANSCRIPT.value,
                    title=pdf_path.stem,
                    file_path=str(pdf_path),
                    raw_text=raw_text,
                    content_hash=content_hash,
                    date=doc_date,
                    processing_status=DocumentStatus.PENDING.value,
                    created_at=datetime.utcnow() # Fix asyncpg offset-naive issue
                )
                
                db.add(doc)
                await db.flush()  # To get doc.id
                
                # Insert statements and speakers
                seen_hashes = set()
                for stmt in parsed_statements:
                    # 1. Get or create speaker
                    result = await db.execute(
                        select(Speaker).where(Speaker.normalized_name == stmt.speaker)
                    )
                    speaker_obj = result.scalar_one_or_none()
                    
                    if not speaker_obj:
                        speaker_obj = Speaker(
                            name=stmt.speaker,
                            normalized_name=stmt.speaker,
                        )
                        db.add(speaker_obj)
                        await db.flush()
                        
                    # 2. Insert Statement
                    stmt_hash = generate_content_hash(stmt.text, speaker_obj.id, doc_date)
                    
                    if stmt_hash in seen_hashes:
                        continue
                    seen_hashes.add(stmt_hash)
                    
                    # Check duplicate statement in DB
                    res = await db.execute(select(Statement.id).where(Statement.content_hash == stmt_hash))
                    if res.scalar_one_or_none():
                        continue
                        
                    db_stmt = Statement(
                        content_hash=stmt_hash,
                        text=stmt.text,
                        speaker_id=speaker_obj.id,
                        raw_document_id=doc.id,
                        raw_speaker_name=stmt.speaker,
                        date=doc_date,
                        page_number=stmt.page_number,
                    )
                    db.add(db_stmt)
                
                await db.flush()
                success_count += 1
                logger.info(f"  -> Added {len(parsed_statements)} statements to database as PENDING.")
                
                await db.commit()
                logger.info(f"  -> Committed {pdf_path.name} to DB.")
                
            except Exception as e:
                await db.rollback() # Fix PendingRollbackError
                logger.error(f"Error processing {pdf_path.name}: {e}")
                error_count += 1
        
    logger.info("="*50)
    logger.info("INGESTION COMPLETE")
    logger.info(f"Successfully added : {success_count}")
    logger.info(f"Skipped duplicates : {duplicate_count}")
    logger.info(f"Errors             : {error_count}")
    logger.info("="*50)
    if success_count > 0:
        logger.info("You can now run 'python main.py --agent-pipeline' to process these files.")

def main():
    parser = argparse.ArgumentParser(description="Ingest local PDF files into PostgreSQL RawDocument table for Agent Pipeline")
    parser.add_argument("--dir", "-d", type=str, default="data/raw/contracts", help="Directory containing PDF files")
    parser.add_argument("--limit", "-l", type=int, default=None, help="Limit number of files to process (for testing)")
    
    args = parser.parse_args()
    
    asyncio.run(process_directory(args.dir, args.limit))

if __name__ == "__main__":
    main()
