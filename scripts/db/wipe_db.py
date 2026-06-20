import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from database.session import async_engine
from database.models import Base
from database.neo4j_client import get_driver
from sqlalchemy import text

async def wipe():
    print("PostgreSQL sıfırlanıyor...")
    async with async_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE;"))
        await conn.execute(text("CREATE SCHEMA public;"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO public;"))
        await conn.run_sync(Base.metadata.create_all)
    print("PostgreSQL temizlendi!")

    print("Neo4j sıfırlanıyor...")
    driver = await get_driver()
    async with driver.session() as session:
        await session.run("MATCH (n) DETACH DELETE n")
    print("Neo4j temizlendi!")
    
    await driver.close()

asyncio.run(wipe())
