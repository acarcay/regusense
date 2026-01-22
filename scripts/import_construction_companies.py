"""
Import Construction Companies: Top inşaat firmaları ve yönetim kurulları.

Bu script:
1. Bilinen büyük inşaat firmalarını Neo4j'ye import eder
2. Yönetim kurulu üyelerini bağlar
3. İhale verilerini (varsa) ekler

Gerçek veri kaynakları:
- KİK (ekap.kik.gov.tr) - İhale sonuçları
- TSG (tsg.tuik.gov.tr) - Şirket yöneticileri
- TOBB - Ticaret Sicil

Şimdilik: Statik veri listesi (manuel araştırmayla doldurulacak)
"""

import asyncio
import logging
from typing import Optional
from dataclasses import dataclass
from datetime import date

from database import neo4j_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ConstructionCompany:
    """İnşaat firması verisi."""
    name: str
    mersis_no: str
    vergi_no: Optional[str] = None
    holding: Optional[str] = None  # Ana holding
    keywords: list[str] = None  # Alternatif isimler
    
    def __post_init__(self):
        if self.keywords is None:
            self.keywords = []


@dataclass
class BoardMember:
    """Yönetim kurulu üyesi."""
    company_mersis: str
    person_name: str
    position: str  # CEO, Board Chair, Board Member, etc.
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    weight: float = 0.9  # Board member default weight


# =============================================================================
# Top İnşaat Firmaları (Statik Liste)
# =============================================================================
# Kaynak: Kamu ihaleleri, ENR raporları, basın taraması
# NOT: MERSİS numaraları örnek/placeholder - gerçek verilerle değiştirilmeli

TOP_CONSTRUCTION_COMPANIES = [
    # Büyük 5 (Mega projeler)
    ConstructionCompany("Cengiz İnşaat", "0015000000000001", holding="Cengiz Holding", 
                        keywords=["cengiz", "cengiz holding", "cengiz inşaat"]),
    ConstructionCompany("Limak İnşaat", "0015000000000002", holding="Limak Holding",
                        keywords=["limak", "limak holding"]),
    ConstructionCompany("Kalyon İnşaat", "0015000000000003", holding="Kalyon Grup",
                        keywords=["kalyon", "kalyon grup"]),
    ConstructionCompany("Kolin İnşaat", "0015000000000004", holding="Kolin Grup",
                        keywords=["kolin", "kolin grup"]),
    ConstructionCompany("MNG Holding", "0015000000000005", 
                        keywords=["mng", "mng holding"]),
    
    # Orta Büyüklük (Top 20)
    ConstructionCompany("Yapı Merkezi", "0015000000000006", keywords=["yapı merkezi"]),
    ConstructionCompany("İÇDAŞ İnşaat", "0015000000000007", keywords=["içdaş"]),
    ConstructionCompany("Nurol İnşaat", "0015000000000008", keywords=["nurol"]),
    ConstructionCompany("Gülsan Holding", "0015000000000009", keywords=["gülsan"]),
    ConstructionCompany("Özdemir Holding", "0015000000000010", keywords=["özdemir"]),
    
    ConstructionCompany("STFA", "0015000000000011", keywords=["stfa"]),
    ConstructionCompany("Tekfen İnşaat", "0015000000000012", keywords=["tekfen"]),
    ConstructionCompany("Enka İnşaat", "0015000000000013", keywords=["enka"]),
    ConstructionCompany("Alarko Holding", "0015000000000014", keywords=["alarko"]),
    ConstructionCompany("Doğuş İnşaat", "0015000000000015", keywords=["doğuş"]),
    
    # KİK İhale Kazananları
    ConstructionCompany("Mapa İnşaat", "0015000000000016", keywords=["mapa"]),
    ConstructionCompany("Makyol İnşaat", "0015000000000017", keywords=["makyol"]),
    ConstructionCompany("Yüksel İnşaat", "0015000000000018", keywords=["yüksel"]),
    ConstructionCompany("Özka İnşaat", "0015000000000019", keywords=["özka"]),
    ConstructionCompany("Koç İnşaat", "0015000000000020", keywords=["koç inşaat"]),
]

# =============================================================================
# Yönetim Kurulu Üyeleri (Örnek)
# =============================================================================
# NOT: Gerçek veriler KKB, TSG veya basın taramasından çekilmeli

SAMPLE_BOARD_MEMBERS = [
    # Cengiz Grup
    BoardMember("0015000000000001", "Mehmet Cengiz", "Board Chair", weight=1.0),
    
    # Limak
    BoardMember("0015000000000002", "Nihat Özdemir", "Board Chair", weight=1.0),
    
    # Kalyon
    BoardMember("0015000000000003", "Cemal Kalyoncu", "Board Chair", weight=1.0),
    
    # Kolin
    BoardMember("0015000000000004", "Naci Koloğlu", "Board Chair", weight=1.0),
]


# =============================================================================
# Import Functions
# =============================================================================

async def import_companies():
    """Import tüm inşaat firmalarını Neo4j'ye."""
    logger.info(f"Importing {len(TOP_CONSTRUCTION_COMPANIES)} construction companies...")
    
    for company in TOP_CONSTRUCTION_COMPANIES:
        # Create Organization node
        await neo4j_client.create_organization(
            name=company.name,
            mersis_no=company.mersis_no,
            vergi_no=company.vergi_no,
            org_type="company",
        )
        
        # Add keywords as property
        cypher = """
        MATCH (o:Organization {mersis_no: $mersis})
        SET o.keywords = $keywords,
            o.holding = $holding,
            o.sector = 'CONSTRUCTION'
        """
        await neo4j_client.run_write(cypher, {
            "mersis": company.mersis_no,
            "keywords": company.keywords,
            "holding": company.holding,
        })
        
        # Connect to Construction sector
        cypher = """
        MATCH (o:Organization {mersis_no: $mersis})
        MATCH (s:Sector {code: 'CONSTRUCTION'})
        MERGE (o)-[r:OPERATES_IN]->(s)
        SET r.primary = true
        """
        await neo4j_client.run_write(cypher, {"mersis": company.mersis_no})
    
    logger.info(f"Imported {len(TOP_CONSTRUCTION_COMPANIES)} companies")


async def import_board_members():
    """Import yönetim kurulu üyelerini."""
    logger.info(f"Importing {len(SAMPLE_BOARD_MEMBERS)} board members...")
    
    for member in SAMPLE_BOARD_MEMBERS:
        # Find or create person as potential politician connection
        # Note: In real system, this would link to existing Politicians
        cypher = """
        MERGE (p:Person {name: $name})
        SET p.normalized_name = toLower($name)
        
        WITH p
        MATCH (o:Organization {mersis_no: $mersis})
        MERGE (p)-[r:BOARD_MEMBER_OF]->(o)
        SET r.position = $position,
            r.weight = $weight,
            r.start_date = $start_date,
            r.end_date = $end_date
        """
        await neo4j_client.run_write(cypher, {
            "name": member.person_name,
            "mersis": member.company_mersis,
            "position": member.position,
            "weight": member.weight,
            "start_date": member.start_date,
            "end_date": member.end_date,
        })
    
    logger.info(f"Imported {len(SAMPLE_BOARD_MEMBERS)} board members")


async def create_construction_index():
    """Create index for faster company name search."""
    logger.info("Creating indexes...")
    
    indexes = [
        "CREATE INDEX org_keywords IF NOT EXISTS FOR (o:Organization) ON (o.keywords)",
        "CREATE INDEX org_sector IF NOT EXISTS FOR (o:Organization) ON (o.sector)",
        "CREATE FULLTEXT INDEX org_name_search IF NOT EXISTS FOR (o:Organization) ON EACH [o.name]",
    ]
    
    for idx in indexes:
        try:
            await neo4j_client.run_write(idx, {})
            logger.info(f"  Created index")
        except Exception as e:
            logger.warning(f"  Index may already exist: {e}")


async def run_import():
    """Full import process."""
    logger.info("=" * 60)
    logger.info("Construction Companies Import")
    logger.info("=" * 60)
    
    try:
        await import_companies()
        await import_board_members()
        await create_construction_index()
        
        # Verify
        result = await neo4j_client.run_query(
            "MATCH (o:Organization {sector: 'CONSTRUCTION'}) RETURN count(o) as count"
        )
        count = result[0]["count"] if result else 0
        
        logger.info("=" * 60)
        logger.info("Import Complete!")
        logger.info(f"  Construction Companies: {count}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Import failed: {e}")
        raise
    finally:
        await neo4j_client.close_driver()


def main():
    asyncio.run(run_import())


if __name__ == "__main__":
    main()
