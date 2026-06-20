import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from database.session import async_engine
from database.models import SpeakerRole
from sqlalchemy import delete
from database.neo4j_client import run_write

async def cleanup():
    async with async_engine.begin() as conn:
        await conn.execute(delete(SpeakerRole).where(SpeakerRole.term_name == "28. Dönem"))
    await run_write("MATCH (p)-[r:SERVED_IN {term_name: '28. Dönem'}]->(party) DELETE r")
    print("Temizlendi!")

asyncio.run(cleanup())
