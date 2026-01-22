"""
Sync PostgreSQL to Neo4j: ETL script to populate graph database.

Syncs:
1. Speakers → Politician nodes
2. Creates base Sector nodes
3. (Optional) Imports organization data from CSV
"""

import asyncio
import logging
from datetime import date

from sqlalchemy import select

from database.session import get_async_session
from database.models import Speaker
from database.graph_schema import SECTOR_DEFINITIONS
from database import neo4j_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def sync_sectors():
    """Create all sector nodes."""
    logger.info("Creating sector nodes...")
    
    for sector in SECTOR_DEFINITIONS:
        await neo4j_client.create_sector(
            code=sector.code,
            name=sector.name,
        )
    
    logger.info(f"Created {len(SECTOR_DEFINITIONS)} sector nodes")


async def sync_politicians():
    """Sync PostgreSQL speakers to Neo4j Politician nodes."""
    logger.info("Syncing politicians from PostgreSQL...")
    
    count = 0
    
    async with get_async_session() as session:
        result = await session.execute(select(Speaker))
        speakers = result.scalars().all()
        
        for speaker in speakers:
            await neo4j_client.create_politician(
                pg_id=speaker.id,
                name=speaker.name,
                normalized_name=speaker.normalized_name,
                party="",  # TODO: Add party data if available
            )
            count += 1
            
            if count % 100 == 0:
                logger.info(f"  Synced {count} politicians...")
    
    logger.info(f"Synced {count} politicians to Neo4j")
    return count


async def create_sample_organizations():
    """Create sample organization data for testing."""
    logger.info("Creating sample organizations...")
    
    # Sample Turkish construction/energy companies
    sample_orgs = [
        ("Cengiz Holding", "0015045618400017", "company", ["CONSTRUCTION", "ENERGY"]),
        ("Limak Holding", "0015045618400018", "company", ["CONSTRUCTION", "ENERGY"]),
        ("Kalyon Grup", "0015045618400019", "company", ["CONSTRUCTION"]),
        ("Kolin İnşaat", "0015045618400020", "company", ["CONSTRUCTION"]),
        ("MNG Holding", "0015045618400021", "company", ["CONSTRUCTION", "MINING"]),
    ]
    
    for name, mersis, org_type, sectors in sample_orgs:
        await neo4j_client.create_organization(
            name=name,
            mersis_no=mersis,
            org_type=org_type,
        )
        
        # Create OPERATES_IN relationships
        for sector_code in sectors:
            cypher = """
            MATCH (o:Organization {mersis_no: $mersis})
            MATCH (s:Sector {code: $sector_code})
            MERGE (o)-[r:OPERATES_IN]->(s)
            SET r.primary = $primary
            """
            await neo4j_client.run_write(cypher, {
                "mersis": mersis,
                "sector_code": sector_code,
                "primary": sector_code == sectors[0],
            })
    
    logger.info(f"Created {len(sample_orgs)} sample organizations")


async def create_sample_connections():
    """Create sample politician-organization connections for testing."""
    logger.info("Creating sample connections...")
    
    # This is sample data - in production, use real data sources
    # Format: (politician_name, org_mersis, connection_type, start_date, end_date)
    sample_connections = [
        # These are example connections - replace with real data
    ]
    
    for conn in sample_connections:
        pol_name, mersis, conn_type, start, end = conn
        
        # Find politician by name
        cypher = """
        MATCH (p:Politician)
        WHERE toLower(p.normalized_name) CONTAINS toLower($name)
        MATCH (o:Organization {mersis_no: $mersis})
        MERGE (p)-[r:CONNECTED_TO]->(o)
        SET r.type = $type,
            r.weight = $weight,
            r.start_date = $start,
            r.end_date = $end,
            r.last_verified = date()
        """
        weight = neo4j_client.get_connection_weight(conn_type)
        await neo4j_client.run_write(cypher, {
            "name": pol_name,
            "mersis": mersis,
            "type": conn_type,
            "weight": weight,
            "start": start,
            "end": end,
        })
    
    logger.info(f"Created {len(sample_connections)} connections")


async def run_full_sync():
    """Run full sync from PostgreSQL to Neo4j."""
    logger.info("=" * 60)
    logger.info("Starting PostgreSQL → Neo4j Sync")
    logger.info("=" * 60)
    
    try:
        # Step 1: Create sectors
        await sync_sectors()
        
        # Step 2: Sync politicians
        pol_count = await sync_politicians()
        
        # Step 3: Create sample organizations (for testing)
        await create_sample_organizations()
        
        # Step 4: Create sample connections (for testing)
        await create_sample_connections()
        
        logger.info("=" * 60)
        logger.info("Sync Complete!")
        logger.info(f"  Politicians: {pol_count}")
        logger.info(f"  Sectors: {len(SECTOR_DEFINITIONS)}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        raise
    finally:
        await neo4j_client.close_driver()


def main():
    """CLI entry point."""
    asyncio.run(run_full_sync())


if __name__ == "__main__":
    main()
