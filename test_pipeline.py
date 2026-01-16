"""
End-to-End Test Pipeline for ReguSense.

This script demonstrates the full workflow:
1. Scrape data from multiple sources (Twitter, YouTube, Web)
2. Ingest into Vector Store & Knowledge Graph
3. Detect contradictions
4. Generate visual assets (Banner + Video Script)

Usage:
    python test_pipeline.py --speaker "Mehmet Şimşek"
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from scrapers.twitter_scraper import TwitterScraper
from scrapers.video_processor import VideoProcessor
from intelligence.contradiction_engine import ContradictionDetector
from reporting.visual_engine import generate_social_banner, generate_video_script
from core.deps import get_memory, get_analyzer, get_detector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("pipeline.log")
    ]
)
logger = logging.getLogger("TestPipeline")


async def run_pipeline(speaker_name: str, max_contradictions: int = 1):
    """Run the full data-to-content pipeline."""
    logger.info(f"🚀 Starting Pipeline for: {speaker_name}")
    
    # 1. Initialize Components
    memory = get_memory()
    analyzer = get_analyzer()
    detector = ContradictionDetector(memory, analyzer) # Uses new KG-based detector
    video_proc = VideoProcessor(whisper_model="base")
    
    # 2. Data Collection (Scraping)
    logger.info("--- PHASE 1: Data Collection ---")
    
    # A. Twitter
    logger.info("🐦 Scraping Twitter...")
    async with TwitterScraper() as twitter:
        # Note: In a real scenario, we might need to find the handle first.
        # Here we mock or assume a search capability.
        # For test, we will scrape a search query of the speaker
        pass
        # tweets = await twitter.scrape_search(f"from:{speaker_name}", max_tweets=20)
        # logger.info(f"Synced {len(tweets)} tweets.")

    # B. YouTube
    logger.info("📺 Scraping YouTube...")
    # Search and process top 2 videos
    # video_proc.search_and_process(f"{speaker_name} açıklama", max_results=2)
    # logger.info("YouTube processing complete.")
    
    # For demo purposes, we will rely on existing data + live analysis
    # or simulate a new statement to find contradiction against existing data.
    
    logger.info("--- PHASE 2: Detection & Analysis ---")
    
    # Simulate a "New Statement" to check against the collected memory
    # In a real loop, this would iterate over newly scraped items.
    
    # Let's say we just scraped this new statement:
    test_statement = "Enflasyonu düşürmek için büyümeden taviz vermeyeceğiz."
    logger.info(f"Analyzing new statement: '{test_statement}'")
    
    # Detect
    result = detector.detect(
        new_statement=test_statement,
        speaker=speaker_name
    )
    
    logger.info(f"Analysis Result: Score={result.contradiction_score}")
    
    if result.is_contradiction or result.contradiction_score >= 6:
        logger.info("🚨 Contradiction Detected!")
        
        # 3. Content Generation
        logger.info("--- PHASE 3: Content Generation ---")
        
        # Banner
        banner_path = generate_social_banner(result.to_dict())
        logger.info(f"✅ Banner generated: {banner_path}")
        
        # Video Script
        script, script_path = generate_video_script(result.to_dict())
        logger.info(f"✅ Video Script generated: {script_path}")
        
        return True
    else:
        logger.info("No significant contradiction found in this pass.")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReguSense End-to-End Pipeline")
    parser.add_argument("--speaker", type=str, default="Mehmet Şimşek", help="Politician name")
    args = parser.parse_args()
    
    try:
        asyncio.run(run_pipeline(args.speaker))
    except KeyboardInterrupt:
        logger.info("Pipeline stopped by user.")
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
