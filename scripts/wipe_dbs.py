import asyncio
import os
import shutil
from pathlib import Path
from database.postgres_client import engine
from database.models import Base
from database.neo4j_client import run_write

async def wipe_all():
    print("Wiping PostgreSQL...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("PostgreSQL wiped and recreated.")
    
    print("Wiping Neo4j...")
    await run_write("MATCH (n) DETACH DELETE n", {})
    print("Neo4j wiped.")
    
    print("Wiping ChromaDB...")
    chroma_path = Path("data/chromadb")
    if chroma_path.exists():
        shutil.rmtree(chroma_path)
    print("ChromaDB wiped.")

if __name__ == "__main__":
    asyncio.run(wipe_all())
