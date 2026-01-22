"""
Debug specific ID 54387 reported by user as None.
"""

import asyncio
from sqlalchemy import select
from database.session import get_async_session
from database.models import Statement
from database import neo4j_client

async def debug():
    target_id = 54387
    print(f"Checking ID: {target_id}")

    # 1. Check Postgres
    async with get_async_session() as session:
        result = await session.execute(select(Statement).where(Statement.id == target_id))
        stmt = result.scalar_one_or_none()
        
        if stmt:
            print(f"PG Found:")
            print(f"  Text: {repr(stmt.text)}")
            print(f"  Date: {repr(stmt.date)}")
            print(f"  Speaker ID: {stmt.speaker_id}")
        else:
            print("PG: Not Found")

    # 2. Check Neo4j
    cypher = """
    MATCH (s:Statement {pg_id: $pg_id})
    RETURN s.pg_id as pg_id, s.text as text, s.date as date
    """
    results = await neo4j_client.run_query(cypher, {"pg_id": target_id})
    
    if results:
        for row in results:
            print("Neo4j Found:")
            print(f"  Text: {repr(row['text'])}")
            print(f"  Date: {repr(row['date'])}")
    else:
        print("Neo4j: Not Found")

if __name__ == "__main__":
    asyncio.run(debug())
