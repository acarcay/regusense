import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from database.session import async_engine
from sqlalchemy import text

async def alter():
    async with async_engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE statements ADD COLUMN raw_speaker_name VARCHAR(255);"))
        except Exception as e: print(e)
        
        try:
            await conn.execute(text("ALTER TABLE statements ADD COLUMN raw_document_id INTEGER REFERENCES raw_documents(id);"))
        except Exception as e: print(e)
        
        try:
            await conn.execute(text("ALTER TABLE statements ALTER COLUMN speaker_id DROP NOT NULL;"))
        except Exception as e: print(e)
        
    print("Altered!")

asyncio.run(alter())
