"""
Direct Cypher Cleanup for Hitap prefixes.
"""
import asyncio
from database import neo4j_client
import logging

logging.basicConfig(level=logging.INFO)

async def clean_hitap():
    # User provided query
    cypher = """
    MATCH (s:Statement)-[r:MENTIONED_BY]->(o:Organization)
    WHERE s.text CONTAINS "Sayın " + r.matched_keyword 
       OR s.text CONTAINS "Başkan " + r.matched_keyword
       OR s.text CONTAINS r.matched_keyword + " Bey"
       OR s.text CONTAINS "VEKİLİ " + r.matched_keyword
       OR s.text CONTAINS "BAŞKAN " + r.matched_keyword
       OR s.text CONTAINS "SAYIN " + r.matched_keyword
    DELETE r
    RETURN count(r) as deleted
    """
    
    result = await neo4j_client.run_write(cypher)
    print(f"Deleted {result} hitap-based relationships.")

if __name__ == "__main__":
    asyncio.run(clean_hitap())
