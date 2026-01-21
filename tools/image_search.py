"""
Image Search Tool using DuckDuckGo.
Fetches high-quality images for speaker profiles.
"""

import logging
from typing import Optional
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

def get_speaker_image(query: str) -> Optional[str]:
    """
    Search for a speaker's image.
    Returns the URL of the first result or None.
    """
    try:
        # Append "portre" or "siyasetçi" to get better results
        search_query = f"{query} siyasetçi portre high resolution"
        
        with DDGS() as ddgs:
            results = list(ddgs.images(
                search_query,
                max_results=1,
                safesearch='off'
            ))
            
            if results:
                image_url = results[0].get('image')
                logger.info(f"Found image for {query}: {image_url}")
                return image_url
                
    except Exception as e:
        logger.error(f"Image search failed for {query}: {e}")
        
    return None

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(get_speaker_image("Mehmet Şimşek"))
