"""
Fix script to repair Statement nodes with missing text/date.
"""

import asyncio
from sqlalchemy import select
from database.session import get_async_session
from database.models import Statement
from database import neo4j_client
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fix_data():
    logger.info("Starting data repair...")
    
    # 1. Find broken nodes in Neo4j
    cypher = """
    MATCH (s:Statement)
    WHERE s.text IS NULL OR s.date IS NULLOr s.date = 'None'
    RETURN s.pg_id as pg_id
    """
    
    # Wait, 'OR s.date IS NULLOr' typo in thought? corrected in code.
    cypher = """
    MATCH (s:Statement)
    WHERE s.text IS NULL OR s.date IS NULL OR s.date = 'None'
    RETURN s.pg_id as pg_id
    LIMIT 10000
    """
    
    results = await neo4j_client.run_query(cypher)
    logger.info(f"Found {len(results)} nodes with missing data")
    
    if not results:
        logger.info("No broken nodes found.")
        return

    broken_ids = [r['pg_id'] for r in results]
    
    # 2. Fetch data from Postgres
    async with get_async_session() as session:
        # Process in chunks
        chunk_size = 100
        for i in range(0, len(broken_ids), chunk_size):
            chunk_ids = broken_ids[i:i + chunk_size]
            
            query = select(Statement).where(Statement.id.in_(chunk_ids))
            pg_results = await session.execute(query)
            statements = pg_results.scalars().all()
            
            logger.info(f"Processing chunk {i}-{i+chunk_size} ({len(statements)} found in PG)")
            
            for stmt in statements:
                # Update Neo4j
                update_cypher = """
                MATCH (s:Statement {pg_id: $pg_id})
                SET s.text = $text,
                    s.date = $date
                """
                
                date_str = str(stmt.date)
                # Ensure date is standard format if needed
                
                await neo4j_client.run_write(update_cypher, {
                    "pg_id": stmt.id,
                    "text": stmt.text,
                    "date": date_str
                })
                
    logger.info("Repair complete!")

if __name__ == "__main__":
    asyncio.run(fix_data())
