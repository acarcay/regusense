"""
YouTube Video Processor and Transcription Service.

Handles:
1. Fetching transcripts from YouTube videos (using youtube-transcript-api).
2. Fallback to audio download and Whisper transcription if no caption exists.
3. Ingesting transcripts into Vector Store with 'siyasi konuşma' tag.

Dependencies:
- youtube-transcript-api
- openai-whisper
- yt-dlp

Author: ReguSense Team
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import re

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import whisper

from core.logging import get_logger
from core.deps import get_memory
from scrapers.models import ScrapedStatement, SourceType

logger = get_logger(__name__)


@dataclass
class VideoMetadata:
    """Metadata for a processed video."""
    video_id: str
    title: str
    channel_name: str
    upload_date: str
    url: str
    duration: int = 0


@dataclass
class TranscriptSegment:
    """A segment of the transcript."""
    text: str
    start: float
    duration: float


class VideoProcessor:
    """
    Processes YouTube videos for transcription and storage.
    
    Optimized workflow:
    1. Try `youtube-transcript-api` (Fast, free).
    2. If failed, download audio via `yt-dlp`.
    3. Transcribe audio using `openai-whisper` (Local model).
    """
    
    def __init__(
        self,
        whisper_model: str = "base",  # tiny, base, small, medium, large
        memory: Optional[object] = None,
    ):
        """
        Initialize video processor.
        
        Args:
            whisper_model: Whisper model size (default: base for speed)
            memory: PoliticalMemory instance (optional, for ingestion)
        """
        self.whisper_model_name = whisper_model
        self._whisper_model = None
        self.memory = memory or get_memory()
        
        logger.info(f"VideoProcessor initialized (Whisper: {whisper_model})")

    def _load_whisper(self):
        """Lazy load Whisper model."""
        if self._whisper_model is None:
            logger.info(f"Loading Whisper model: {self.whisper_model_name}...")
            self._whisper_model = whisper.load_model(self.whisper_model_name)
            logger.info("Whisper model loaded.")

    def extract_video_id(self, url: str) -> Optional[str]:
        """Extract YouTube video ID from URL."""
        # Simple regex for standard and short URLs
        patterns = [
            r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
            r"(?:youtu\.be\/)([0-9A-Za-z_-]{11})",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def get_video_metadata(self, video_id: str) -> Optional[VideoMetadata]:
        """Fetch video metadata using yt-dlp."""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_id, download=False)
                parsed_date = datetime.strptime(info.get('upload_date', '20240101'), "%Y%m%d").strftime("%Y-%m-%d")
                
                return VideoMetadata(
                    video_id=video_id,
                    title=info.get('title', 'Unknown'),
                    channel_name=info.get('uploader', 'Unknown'),
                    upload_date=parsed_date,
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    duration=info.get('duration', 0)
                )
        except Exception as e:
            logger.error(f"Failed to get metadata for {video_id}: {e}")
            return None

    def get_transcript_api(self, video_id: str) -> Optional[List[TranscriptSegment]]:
        """Try fetching transcript via official API/scraping."""
        try:
            # Try Turkish first, then auto-generated
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            try:
                transcript = transcript_list.find_transcript(['tr', 'tr-TR'])
            except:
                # Fallback to auto-generated or any available
                transcript = transcript_list.find_manually_created_transcript()
            
            data = transcript.fetch()
            
            segments = [
                TranscriptSegment(
                    text=item['text'],
                    start=item['start'],
                    duration=item['duration']
                ) for item in data
            ]
            logger.info(f"Fetched transcript via API for {video_id} ({len(segments)} segments)")
            return segments
            
        except (TranscriptsDisabled, NoTranscriptFound):
            logger.info(f"No caption found via API for {video_id}. Fallback required.")
        except Exception as e:
            logger.warning(f"API transcript fetch failed for {video_id}: {e}")
            
        return None

    def transcribe_with_whisper(self, video_id: str) -> Optional[List[TranscriptSegment]]:
        """Download audio and transcribe with Whisper."""
        self._load_whisper()
        
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            output_template = str(temp_path / "%(id)s.%(ext)s")
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': output_template,
                'quiet': True,
            }
            
            try:
                logger.info(f"Downloading audio for {video_id}...")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                
                audio_file = list(temp_path.glob("*.mp3"))[0]
                
                logger.info(f"Transcribing audio with Whisper...")
                result = self._whisper_model.transcribe(str(audio_file), language="tr")
                
                segments = [
                    TranscriptSegment(
                        text=seg['text'].strip(),
                        start=seg['start'],
                        duration=seg['end'] - seg['start']
                    ) for seg in result['segments']
                ]
                
                logger.info(f"Whisper transcription complete ({len(segments)} segments)")
                return segments
                
            except Exception as e:
                logger.error(f"Whisper transcription failed for {video_id}: {e}")
                return None

    def process_video(self, url_or_id: str) -> bool:
        """
        Process a single video: fetch metadata, transcript, and ingest.
        
        Args:
            url_or_id: YouTube URL or Video ID
            
        Returns:
            True if successful
        """
        video_id = self.extract_video_id(url_or_id) or url_or_id
        if len(video_id) != 11:
            logger.error(f"Invalid video ID: {video_id}")
            return False
            
        logger.info(f"Processing video: {video_id}")
        
        # 1. Get Metadata
        meta = self.get_video_metadata(video_id)
        if not meta:
            logger.error(f"Could not fetch metadata for {video_id}")
            return False
            
        # 2. Get Transcript (API -> Whisper)
        segments = self.get_transcript_api(video_id)
        source_method = "API"
        
        if not segments:
            logger.info("Switching to Whisper fallback...")
            segments = self.transcribe_with_whisper(video_id)
            source_method = "WHISPER"
            
        if not segments:
            logger.error(f"Could not obtain transcript for {video_id}")
            return False
            
        # 3. Ingest into Vector Store
        full_text = " ".join([s.text for s in segments])
        
        # Create ScrapedStatement for ingestion
        statement = ScrapedStatement(
            text=full_text,
            speaker=meta.channel_name,  # Assuming channel is speaker (or extracted from title)
            source=meta.url,
            source_type=SourceType.YOUTUBE,
            date=meta.upload_date,
            context={
                "video_id": meta.video_id,
                "title": meta.title,
                "duration": meta.duration,
                "transcription_method": source_method
            }
        )
        
        # Use PoliticalMemory to update (we assume analyze_and_insert logic inside ingestion)
        # For direct insertion:
        self.memory.add_statement(
            text=statement.text,
            speaker=statement.speaker,
            source=statement.source,
            source_type=statement.source_type.value,
            date=statement.date,
            page_number=0 # Not applicable
        )
        
        logger.info(f"Successfully ingested video {video_id} ({source_method})")
        return True

    def search_and_process(self, query: str, max_results: int = 3):
        """Search YouTube and process top videos."""
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
            'default_search': 'ytsearch',
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
                
                if 'entries' in result:
                    for entry in result['entries']:
                        video_id = entry.get('id')
                        if video_id:
                            self.process_video(video_id)
                            
        except Exception as e:
            logger.error(f"Search failed: {e}")

# Singleton
_processor_instance = None

def get_video_processor() -> VideoProcessor:
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = VideoProcessor()
    return _processor_instance

if __name__ == "__main__":
    # Test
    import sys
    
    if len(sys.argv) > 1:
        target = sys.argv[1]
        proc = VideoProcessor()
        if "http" in target or len(target) == 11:
            proc.process_video(target)
        else:
            proc.search_and_process(target)
    else:
        print("Usage: python video_processor.py <video_url_or_search_query>")
