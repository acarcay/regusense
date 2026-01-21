"""
Visual Engine using Playwright and HTML/CSS.
Generates premium social media banners and video scripts.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from playwright.async_api import async_playwright

from tools.image_search import get_speaker_image
from intelligence.contradiction_engine import ContradictionResult

logger = logging.getLogger(__name__)

# Constants
ASSETS_DIR = Path("assets")
TEMPLATES_DIR = ASSETS_DIR / "templates"
OUTPUT_DIR = Path("data/social")
VIDEO_DIR = Path("data/videos")

@dataclass
class VideoScene:
    """A single scene in the video."""
    duration: float
    text: str = ""
    animation: str = "fade_in"  # fade_in, zoom_in, slide_left
    position: str = "center"     # center, top, bottom
    font_size: int = 48
    color: str = "#FFFFFF"

@dataclass
class VideoScript:
    """Video script definition."""
    width: int
    height: int
    fps: int
    background_color: str
    scenes: List[VideoScene] = field(default_factory=list)

    def add_scene(self, **kwargs):
        self.scenes.append(VideoScene(**kwargs))

    def to_json(self, path: Path):
        data = {
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "background": self.background_color,
            "scenes": [vars(s) for s in self.scenes]
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def to_ffmpeg_commands(self, output_file: Path) -> List[str]:
        """
        Generate FFmpeg commands to render this script.
        Simple implementation: creates a color background and overlay text.
        For production, this would use complex filters.
        """
        # This is specific to the 'render_video.py' tool implementation.
        # It creates a command list that python `subprocess` can execute.
        
        # 1. Create simple color background video
        # 2. Add text using drawtext filter (simplified)
        
        total_duration = sum(s.duration for s in self.scenes)
        
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite
            "-f", "lavfi",
            "-i", f"color=c={self.background_color}:s={self.width}x{self.height}:d={total_duration}",
            "-vf", "format=yuv420p",  # Ensure compatibility
            str(output_file)
        ]
        return cmd


class HTMLBannerGenerator:
    """Generates banners using HTML/CSS and Playwright (Async)."""

    def __init__(self, output_dir: str = str(OUTPUT_DIR)):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.template_path = TEMPLATES_DIR / "banner.html"

    def _load_template(self) -> str:
        if not self.template_path.exists():
            raise FileNotFoundError(f"Template not found: {self.template_path}")
        return self.template_path.read_text(encoding="utf-8")

    async def generate(self, result: Dict[str, Any]) -> Path:
        """
        Generate a banner from contradiction result.
        
        Args:
            result: Dictionary from ContradictionResult.to_dict()
            
        Returns:
            Path to generated PNG file.
        """
        speaker = result.get("speaker", "Bilinmiyor")
        score = result.get("contradiction_score", 0)
        
        # Determine file name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_speaker = "".join(c for c in speaker if c.isalnum() or c in (' ', '_')).replace(' ', '_')
        filename = f"contradiction_{safe_speaker}_{timestamp}.png"
        output_path = self.output_dir / filename

        # Fetch image
        try:
            photo_url = get_speaker_image(speaker) or "https://ui-avatars.com/api/?name=Unknown&background=random"
        except Exception as e:
            logger.error(f"Failed to fetch image: {e}")
            photo_url = "https://ui-avatars.com/api/?name=Unknown&background=random"

        # Prepare context for template
        ev1 = result.get("evidence_1") or {}
        ev2 = result.get("evidence_2") or {}
        
        # Format dates
        date1 = ev1.get("date", "Tarihsiz")
        date2 = ev2.get("date", "Bugün")

        # Load HTML
        html_content = self._load_template()
        
        # Replace placeholders
        # Note: Using python format strings would require escaping all CSS braces in HTML loop.
        # Instead, we'll use simple string replace for safety and simplicity with existing CSS.
        replacements = {
            "{speaker}": speaker,
            "{photo_url}": photo_url,
            "{score}": str(score),
            "{contradiction_type}": result.get("contradiction_type", "ÇELİŞKİ"),
            "{date_1}": str(date1),
            "{text_1}": ev1.get("text", "")[:200] + "..." if len(ev1.get("text", "")) > 200 else ev1.get("text", ""),
            "{date_2}": str(date2),
            "{text_2}": result.get("new_statement", "")[:200] + "..."
        }
        
        for key, value in replacements.items():
            html_content = html_content.replace(key, str(value))

        # Render with Playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={"width": 1080, "height": 1350})
            await page.set_content(html_content)
            
            # Wait for image to load (if using network image)
            # Or just wait a bit for fonts/rendering
            await page.wait_for_timeout(1000) 
            
            await page.screenshot(path=str(output_path))
            await browser.close()

        logger.info(f"Generated banner: {output_path}")
        return output_path


class VideoScriptGenerator:
    """Generates video scripts for social media."""

    def __init__(self, output_dir: str = str(VIDEO_DIR)):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def from_contradiction_result(self, result: Dict[str, Any]) -> Tuple[VideoScript, Path]:
        """Create a video script from a contradiction result."""
        script = VideoScript(
            width=1080,
            height=1920,
            fps=30,
            background_color="#121218"
        )

        speaker = result.get("speaker", "")
        # score = result.get("contradiction_score", 0)

        # Intro Scene
        script.add_scene(
            duration=2.0,
            text=f"⚠️ {speaker}\nÇelişki Analizi",
            animation="fade_in",
            font_size=60,
            color="#ef4444"
        )
        
        # Old Statement
        ev1 = result.get("evidence_1", {})
        text1 = ev1.get("text", "")[:100] + "..."
        date1 = ev1.get("date", "")
        
        script.add_scene(
            duration=4.0,
            text=f"ESKİ ({date1}):\n\n\"{text1}\"",
            animation="slide_left",
            font_size=40,
            color="#cccccc"
        )

        # New Statement
        text2 = result.get("new_statement", "")[:100] + "..."
        
        script.add_scene(
            duration=4.0,
            text=f"YENİ (Bugün):\n\n\"{text2}\"",
            animation="zoom_in",
            font_size=40,
            color="#ffffff"
        )
        
        # Conclusion
        script.add_scene(
            duration=3.0,
            text="Detaylar için:\n@regusense",
            animation="fade_in",
            font_size=48
        )

        # Save JSON
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_speaker = "".join(c for c in speaker if c.isalnum() or c in (' ', '_')).replace(' ', '_')
        filename = f"video_script_{safe_speaker}_{timestamp}.json"
        
        output_path = self.output_dir / filename
        script.to_json(output_path)
        
        logger.info(f"Generated video script: {output_path}")
        return script, output_path


# Convenience Functions
def generate_social_banner(result: Dict[str, Any]) -> Path:
    generator = HTMLBannerGenerator()
    return generator.generate(result)

def generate_video_script(result: Dict[str, Any], output_dir: str = "data/videos") -> Tuple[VideoScript, Path]:
    generator = VideoScriptGenerator(output_dir)
    return generator.from_contradiction_result(result)
