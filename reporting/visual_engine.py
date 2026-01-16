"""
Visual Engine for Social Media Content Generation.

Generates:
1. Social media banners (1080x1350 for Instagram/Twitter)
2. Video scripts for Manim/FFmpeg (Reels/TikTok)

Features:
- Left panel: Eski Soz (Old Statement)
- Right panel: Yeni Soz (New Statement)
- Contradiction score visualization
- Branded with Poppins fonts

Author: ReguSense Team
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)


class Colors:
    """Brand color palette for social media content."""
    DARK_BG = (18, 18, 24)
    CARD_BG = (28, 28, 38)
    PRIMARY = (99, 102, 241)
    SECONDARY = (139, 92, 246)
    ACCENT = (236, 72, 153)
    DANGER = (239, 68, 68)
    WARNING = (251, 146, 60)
    SUCCESS = (34, 197, 94)
    TEXT_WHITE = (255, 255, 255)
    TEXT_GRAY = (156, 163, 175)
    TEXT_MUTED = (107, 114, 128)


class FontManager:
    """Manages Poppins font loading."""
    
    def __init__(self, fonts_dir: str = "assets/fonts"):
        self.fonts_dir = Path(fonts_dir)
        self._cache: dict[str, ImageFont.FreeTypeFont] = {}
    
    def get(self, style: str = "Regular", size: int = 24) -> ImageFont.FreeTypeFont:
        """Get font with caching."""
        key = f"{style}_{size}"
        if key not in self._cache:
            font_path = self.fonts_dir / f"Poppins-{style}.ttf"
            if not font_path.exists():
                logger.warning(f"Font not found: {font_path}")
                return ImageFont.load_default()
            self._cache[key] = ImageFont.truetype(str(font_path), size)
        return self._cache[key]
    
    def regular(self, size: int = 24) -> ImageFont.FreeTypeFont:
        return self.get("Regular", size)
    
    def bold(self, size: int = 24) -> ImageFont.FreeTypeFont:
        return self.get("SemiBold", size)


class SocialMediaBanner:
    """Generates 1080x1350 social media banners for contradiction visualization."""
    
    WIDTH = 1080
    HEIGHT = 1350
    PADDING = 60
    
    def __init__(self, fonts_dir: str = "assets/fonts", output_dir: str = "data/social"):
        self.fonts_dir = Path(fonts_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.fonts = FontManager(fonts_dir)
    
    def generate(
        self,
        evidence_1: dict,
        evidence_2: dict,
        speaker: str,
        score: int,
        contradiction_type: str = "",
    ) -> Path:
        """Generate social media banner."""
        img = Image.new("RGB", (self.WIDTH, self.HEIGHT), Colors.DARK_BG)
        draw = ImageDraw.Draw(img)
        
        y = self.PADDING
        y = self._draw_header(draw, y)
        y = self._draw_score(draw, img, y, score, contradiction_type)
        y = self._draw_evidence_panels(draw, y, evidence_1, evidence_2)
        self._draw_footer(draw, speaker)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"contradiction_{speaker.replace(' ', '_')[:20]}_{timestamp}.png"
        output_path = self.output_dir / filename
        
        img.save(output_path, "PNG", quality=95)
        logger.info(f"Generated banner: {output_path}")
        
        return output_path
    
    def _draw_header(self, draw: ImageDraw.Draw, y: int) -> int:
        font = self.fonts.bold(32)
        draw.text((self.PADDING, y), "REGUSENSE", fill=Colors.PRIMARY, font=font)
        
        font_small = self.fonts.regular(18)
        draw.text((self.PADDING, y + 40), "Siyasi Celiskli Tespiti", fill=Colors.TEXT_GRAY, font=font_small)
        
        return y + 100
    
    def _draw_score(self, draw: ImageDraw.Draw, img: Image.Image, y: int, score: int, contradiction_type: str) -> int:
        center_x = self.WIDTH // 2
        circle_radius = 80
        circle_y = y + 120
        
        self._draw_score_circle(draw, center_x, circle_y, circle_radius, score)
        
        font_score = self.fonts.bold(72)
        score_text = str(score)
        bbox = draw.textbbox((0, 0), score_text, font=font_score)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        draw.text(
            (center_x - text_width // 2, circle_y - text_height // 2 - 10),
            score_text, fill=Colors.TEXT_WHITE, font=font_score
        )
        
        font_small = self.fonts.regular(24)
        draw.text((center_x - 15, circle_y + 40), "/10", fill=Colors.TEXT_GRAY, font=font_small)
        
        if contradiction_type and contradiction_type != "NONE":
            type_labels = {
                "REVERSAL": "TAM TERSINE DONUS",
                "BROKEN_PROMISE": "KIRIK SOZ",
                "INCONSISTENCY": "TUTARSIZLIK",
                "PERSONA_SHIFT": "KARAKTER DEGISIMI",
            }
            label = type_labels.get(contradiction_type, contradiction_type)
            
            font_label = self.fonts.bold(20)
            bbox = draw.textbbox((0, 0), label, font=font_label)
            label_width = bbox[2] - bbox[0]
            
            draw.text((center_x - label_width // 2, circle_y + 100), label, fill=Colors.WARNING, font=font_label)
        
        return y + 280
    
    def _draw_score_circle(self, draw: ImageDraw.Draw, cx: int, cy: int, radius: int, score: int) -> None:
        if score >= 8:
            color = Colors.DANGER
        elif score >= 6:
            color = Colors.WARNING
        elif score >= 4:
            color = Colors.PRIMARY
        else:
            color = Colors.SUCCESS
        
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=Colors.CARD_BG, outline=color, width=4)
    
    def _draw_evidence_panels(self, draw: ImageDraw.Draw, y: int, evidence_1: dict, evidence_2: dict) -> int:
        panel_width = (self.WIDTH - self.PADDING * 3) // 2
        panel_height = 450
        
        left_x = self.PADDING
        self._draw_panel(draw, left_x, y, panel_width, panel_height, "ESKI SOZ", evidence_1.get("text", ""), evidence_1.get("date", ""), Colors.TEXT_GRAY)
        
        right_x = self.PADDING * 2 + panel_width
        self._draw_panel(draw, right_x, y, panel_width, panel_height, "YENI SOZ", evidence_2.get("text", ""), evidence_2.get("date", ""), Colors.DANGER)
        
        center_x = self.WIDTH // 2
        font_vs = self.fonts.bold(28)
        draw.text((center_x - 15, y + panel_height // 2 - 15), "VS", fill=Colors.ACCENT, font=font_vs)
        
        return y + panel_height + 40
    
    def _draw_panel(self, draw: ImageDraw.Draw, x: int, y: int, width: int, height: int, title: str, text: str, date: str, color: Tuple[int, int, int]) -> None:
        draw.rounded_rectangle([x, y, x + width, y + height], radius=16, fill=Colors.CARD_BG)
        
        font_title = self.fonts.bold(18)
        draw.text((x + 20, y + 20), title, fill=color, font=font_title)
        
        font_text = self.fonts.regular(18)
        wrapped = self._wrap_text(text, width - 50, font_text, draw)
        draw.text((x + 30, y + 60), wrapped[:400], fill=Colors.TEXT_WHITE, font=font_text)
        
        if date:
            font_date = self.fonts.regular(14)
            draw.text((x + 20, y + height - 40), f"Tarih: {date}", fill=Colors.TEXT_MUTED, font=font_date)
    
    def _wrap_text(self, text: str, max_width: int, font: ImageFont.FreeTypeFont, draw: ImageDraw.Draw) -> str:
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]
        
        if current_line:
            lines.append(" ".join(current_line))
        
        return "\n".join(lines[:8])
    
    def _draw_footer(self, draw: ImageDraw.Draw, speaker: str) -> None:
        footer_y = self.HEIGHT - 120
        center_x = self.WIDTH // 2
        
        font_speaker = self.fonts.bold(24)
        bbox = draw.textbbox((0, 0), speaker, font=font_speaker)
        speaker_width = bbox[2] - bbox[0]
        draw.text((center_x - speaker_width // 2, footer_y), speaker, fill=Colors.TEXT_WHITE, font=font_speaker)
        
        font_handle = self.fonts.regular(16)
        handle = "@regusense"
        bbox = draw.textbbox((0, 0), handle, font=font_handle)
        handle_width = bbox[2] - bbox[0]
        draw.text((center_x - handle_width // 2, footer_y + 35), handle, fill=Colors.PRIMARY, font=font_handle)
    
    def from_contradiction_result(self, result: dict) -> Path:
        """Generate banner from ContradictionResult.to_dict()."""
        evidence_1 = result.get("evidence_1") or {}
        evidence_2 = result.get("evidence_2") or {"text": result.get("new_statement", "")}
        
        if not evidence_1 and result.get("historical_matches"):
            match = result["historical_matches"][0]
            evidence_1 = {"text": match.get("text", ""), "date": match.get("date", "")}
        
        return self.generate(
            evidence_1=evidence_1,
            evidence_2=evidence_2,
            speaker=result.get("speaker", ""),
            score=result.get("contradiction_score", 0),
            contradiction_type=result.get("contradiction_type", ""),
        )


@dataclass
class VideoScene:
    """A single scene in the video."""
    duration: float
    text: str
    animation: str = "fade_in"
    position: str = "center"
    font_size: int = 48
    color: str = "#FFFFFF"


@dataclass
class VideoScript:
    """Video script for Manim/FFmpeg generation."""
    scenes: list[VideoScene] = field(default_factory=list)
    width: int = 1080
    height: int = 1920
    fps: int = 30
    background_color: str = "#121218"
    
    def add_scene(self, **kwargs) -> None:
        self.scenes.append(VideoScene(**kwargs))
    
    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "background": self.background_color,
            "scenes": [
                {
                    "duration": s.duration,
                    "text": s.text,
                    "animation": s.animation,
                    "position": s.position,
                    "font_size": s.font_size,
                    "color": s.color,
                }
                for s in self.scenes
            ],
        }
    
    def save(self, path: Path) -> None:
        """Save script as JSON."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
    
    def to_ffmpeg_commands(self, output_path: Path) -> list[str]:
        """Generate FFmpeg commands for video creation."""
        filter_parts = []
        
        for i, scene in enumerate(self.scenes):
            escaped_text = scene.text.replace("'", "\\'").replace(":", "\\:")
            start_time = sum(s.duration for s in self.scenes[:i])
            end_time = start_time + scene.duration
            
            filter_parts.append(
                f"drawtext=text='{escaped_text}':"
                f"fontsize={scene.font_size}:"
                f"fontcolor=white:"
                f"x=(w-text_w)/2:y=(h-text_h)/2:"
                f"enable='between(t,{start_time},{end_time})'"
            )
        
        total_duration = sum(s.duration for s in self.scenes)
        
        return [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c={self.background_color}:s={self.width}x{self.height}:d={total_duration}",
            "-vf", ",".join(filter_parts),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]


class VideoScriptGenerator:
    """Generates video scripts from contradiction results."""
    
    def __init__(self, output_dir: str = "data/videos"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate(self, evidence_1: dict, evidence_2: dict, speaker: str, score: int, contradiction_type: str = "") -> VideoScript:
        """Generate video script from contradiction data."""
        script = VideoScript()
        
        script.add_scene(duration=2.0, text=speaker, animation="fade_in", font_size=56, color="#FFFFFF")
        
        date_1 = evidence_1.get("date", "Gecmis")
        script.add_scene(duration=1.5, text=f"Tarih: {date_1}", animation="slide_left", font_size=32, color="#9CA3AF")
        
        text_1 = evidence_1.get("text", "")[:150]
        script.add_scene(duration=4.0, text=f'"{text_1}"', animation="fade_in", font_size=36, color="#FFFFFF")
        
        script.add_scene(duration=1.5, text="...", animation="fade_in", font_size=48, color="#6366F1")
        
        date_2 = evidence_2.get("date", "Bugun")
        script.add_scene(duration=1.5, text=f"Tarih: {date_2}", animation="slide_left", font_size=32, color="#9CA3AF")
        
        text_2 = evidence_2.get("text", "")[:150]
        script.add_scene(duration=4.0, text=f'"{text_2}"', animation="fade_in", font_size=36, color="#EF4444")
        
        type_labels = {
            "REVERSAL": "TAM TERSINE DONUS",
            "BROKEN_PROMISE": "KIRIK SOZ",
            "INCONSISTENCY": "TUTARSIZLIK",
        }
        label = type_labels.get(contradiction_type, "CELISKI")
        script.add_scene(duration=3.0, text=f"{label}\n\nSkor: {score}/10", animation="zoom", font_size=48, color="#EC4899")
        
        script.add_scene(duration=2.0, text="@regusense", animation="fade_in", font_size=32, color="#6366F1")
        
        return script
    
    def from_contradiction_result(self, result: dict) -> Tuple[VideoScript, Path]:
        """Generate video script from ContradictionResult."""
        evidence_1 = result.get("evidence_1") or {}
        evidence_2 = result.get("evidence_2") or {"text": result.get("new_statement", "")}
        
        if not evidence_1 and result.get("historical_matches"):
            match = result["historical_matches"][0]
            evidence_1 = {"text": match.get("text", ""), "date": match.get("date", "")}
        
        script = self.generate(
            evidence_1=evidence_1,
            evidence_2=evidence_2,
            speaker=result.get("speaker", ""),
            score=result.get("contradiction_score", 0),
            contradiction_type=result.get("contradiction_type", ""),
        )
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        speaker_slug = result.get("speaker", "").replace(" ", "_")[:20]
        json_path = self.output_dir / f"video_script_{speaker_slug}_{timestamp}.json"
        script.save(json_path)
        
        logger.info(f"Generated video script: {json_path}")
        
        return script, json_path


def generate_social_banner(result: dict, fonts_dir: str = "assets/fonts", output_dir: str = "data/social") -> Path:
    """Generate social media banner from contradiction result."""
    generator = SocialMediaBanner(fonts_dir, output_dir)
    return generator.from_contradiction_result(result)


def generate_video_script(result: dict, output_dir: str = "data/videos") -> Tuple[VideoScript, Path]:
    """Generate video script from contradiction result."""
    generator = VideoScriptGenerator(output_dir)
    return generator.from_contradiction_result(result)


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    sample_result = {
        "speaker": "Mehmet Simsek",
        "contradiction_score": 8,
        "contradiction_type": "BROKEN_PROMISE",
        "evidence_1": {
            "text": "Enflasyon 2024 yili sonunda kesinlikle tek haneye dusecek.",
            "date": "2023-06-15",
        },
        "evidence_2": {
            "text": "Enflasyonla mucadele zaman aliyor. Sabirli olmamiz gerekiyor.",
            "date": "2024-12-10",
        },
    }
    
    banner_path = generate_social_banner(sample_result)
    print(f"Banner generated: {banner_path}")
    
    script, script_path = generate_video_script(sample_result)
    print(f"Video script generated: {script_path}")
    print(f"Total duration: {sum(s.duration for s in script.scenes):.1f}s")
