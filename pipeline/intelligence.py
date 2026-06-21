import logging
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from intelligence.cascade_processor import CascadeProcessor
from intelligence.entity_extractor import get_entity_extractor
from config.settings import settings

logger = logging.getLogger(__name__)

async def run_intelligence_pipeline(
    ekap_days: int = 30,
    hunter_max: Optional[int] = None,
    temporal_window: int = 15,
) -> dict:
    """
    Run the full intelligence pipeline: EKAP → Hunter → Temporal Analysis.
    
    This orchestrates all 4 modules:
    1. Stealth EKAP Scraper - Fetch recent tenders
    2. Hunter Scan - Find company mentions with intent classification
    3. Dynamic Ambiguity - Automatically handled by Hunter
    4. Temporal Conflict Analysis - Detect tender-advocacy timing correlations
    
    Args:
        ekap_days: Days to look back for EKAP tenders
        hunter_max: Max statements to scan (None = all)
        temporal_window: Days window for temporal conflict detection
        
    Returns:
        Summary dict with statistics from each stage
    """
    logger.info("=" * 70)
    logger.info("🚀 INTELLIGENCE PIPELINE STARTING")
    logger.info("=" * 70)
    
    from typing import Any
    summary: dict[str, Any] = {
        "ekap": {"success": False, "tenders_found": 0},
        "hunter": {"success": False, "matches": 0, "conflicts": 0},
        "temporal": {"success": False, "critical_conflicts": 0},
    }
    
    start_time = datetime.now()
    
    # Stage 1: EKAP Stealth Scraper
    logger.info("\n" + "=" * 50)
    logger.info("📋 STAGE 1: EKAP Stealth Scraper")
    logger.info("=" * 50)
    
    try:
        from scrapers.ekap_scraper import EkapScraper
        
        async with EkapScraper(headless=True) as scraper:
            result = await scraper.scrape_latest(days=ekap_days)
            summary["ekap"]["success"] = result.success
            summary["ekap"]["tenders_found"] = result.items_found
            logger.info(f"✅ EKAP: {result.items_found} tenders found in {result.duration_seconds:.1f}s")
    except Exception as e:
        logger.error(f"❌ EKAP stage failed: {e}")
    
    # Stage 2: Hunter Scan with Intent Classification
    logger.info("\n" + "=" * 50)
    logger.info("🎯 STAGE 2: Hunter Scan (Intent Classification)")
    logger.info("=" * 50)
    
    try:
        from scripts.hunter_scan import run_hunter_scan
        
        await run_hunter_scan(
            batch_size=1000,
            max_statements=hunter_max,
            create_pending_threshold=3,
        )
        summary["hunter"]["success"] = True
        logger.info("✅ Hunter scan complete")
    except Exception as e:
        logger.error(f"❌ Hunter stage failed: {e}")
    
    # Stage 3: Temporal Conflict Analysis
    logger.info("\n" + "=" * 50)
    logger.info("🔥 STAGE 3: Temporal Conflict Analysis")
    logger.info("=" * 50)
    
    try:
        from database import neo4j_client
        
        conflicts = await neo4j_client.find_all_temporal_conflicts(window_days=temporal_window)
        
        critical_count = sum(1 for c in conflicts if c.get("risk_level") == "CRITICAL")
        summary["temporal"]["success"] = True
        summary["temporal"]["conflicts_found"] = len(conflicts)
        summary["temporal"]["critical_conflicts"] = critical_count
        
        if critical_count > 0:
            logger.warning(f"🚨 {critical_count} CRITICAL temporal conflicts detected!")
            for c in conflicts[:5]:  # Show top 5
                if c.get("risk_level") == "CRITICAL":
                    logger.warning(
                        f"  🔥 {c.get('politician_name')} ({c.get('party')}) → "
                        f"{c.get('company_name')} ({c.get('days_difference')} days)"
                    )
        else:
            logger.info("✅ No critical temporal conflicts found")
            
    except Exception as e:
        logger.error(f"❌ Temporal analysis stage failed: {e}")
    
    # Summary
    duration = (datetime.now() - start_time).total_seconds()
    
    logger.info("\n" + "=" * 70)
    logger.info("📊 INTELLIGENCE PIPELINE COMPLETE")
    logger.info("=" * 70)
    logger.info(f"  Duration: {duration:.1f}s")
    logger.info(f"  EKAP Tenders: {summary['ekap']['tenders_found']}")
    logger.info(f"  Hunter Success: {summary['hunter']['success']}")
    logger.info(f"  Temporal Conflicts: {summary['temporal'].get('conflicts_found', 0)}")
    logger.info(f"  CRITICAL Risks: {summary['temporal']['critical_conflicts']}")
    logger.info("=" * 70)
    
    # Save summary
    summary["duration_seconds"] = duration
    summary["completed_at"] = datetime.now().isoformat()
    
    summary_path = settings.processed_dir / f"intelligence_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"📄 Summary saved: {summary_path}")
    
    return summary
