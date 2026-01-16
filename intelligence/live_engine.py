"""
Live Speech-to-Text Engine for Real-Time Contradiction Detection.

Provides classes for:
- YouTube audio extraction via yt-dlp
- Microphone audio capture via sounddevice
- Speech-to-text transcription via OpenAI Whisper
- Chunk-based processing for near real-time performance

Usage:
    from intelligence.live_engine import LiveProcessor
    
    processor = LiveProcessor()
    for chunk in processor.stream_youtube("https://youtube.com/..."):
        print(f"[{chunk.timestamp}] {chunk.text}")

Author: ReguSense Team
"""

from __future__ import annotations

import logging
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Generator, Optional
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure logging
logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class TranscriptChunk:
    """A chunk of transcribed speech.
    
    Attributes:
        text: Transcribed text
        timestamp: Start time of the chunk
        duration: Duration of the chunk in seconds
        confidence: Transcription confidence (0-1)
        speaker: Detected speaker (if any)
    """
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    duration: float = 0.0
    confidence: float = 0.0
    speaker: str = ""
    
    def __str__(self) -> str:
        return f"[{self.timestamp.strftime('%H:%M:%S')}] {self.text}"


@dataclass
class LiveSession:
    """Represents an active live transcription session.
    
    Attributes:
        session_id: Unique session identifier
        source: Source URL or "MICROPHONE"
        speaker: Speaker name (for contradiction detection)
        started_at: Session start time
        chunks: List of transcribed chunks
        is_active: Whether the session is actively processing
    """
    session_id: str
    source: str
    speaker: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    chunks: list[TranscriptChunk] = field(default_factory=list)
    is_active: bool = True
    total_text: str = ""
    
    def add_chunk(self, chunk: TranscriptChunk) -> None:
        """Add a new chunk to the session."""
        self.chunks.append(chunk)
        self.total_text += " " + chunk.text
    
    def get_recent_sentences(self, count: int = 2) -> str:
        """Get the last N sentences from the session."""
        sentences = re.split(r'[.!?]+', self.total_text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        return '. '.join(sentences[-count:]) if sentences else ""


# =============================================================================
# Whisper Transcriber
# =============================================================================

class WhisperTranscriber:
    """Speech-to-text transcription using OpenAI Whisper.
    
    Uses the Whisper model for Turkish speech recognition.
    Optimized for near real-time performance with chunk-based processing.
    
    Example:
        >>> transcriber = WhisperTranscriber(model_size="base")
        >>> result = transcriber.transcribe_file("audio.wav")
        >>> print(result.text)
    """
    
    def __init__(
        self,
        model_size: str = "base",
        language: str = "tr",
        device: Optional[str] = None,
    ):
        """
        Initialize the Whisper transcriber.
        
        Args:
            model_size: Whisper model size (tiny, base, small, medium, large)
            language: Target language code (default: Turkish)
            device: Device to use (cuda, cpu, mps). Auto-detected if None.
        """
        self.model_size = model_size
        self.language = language
        self.device = device
        self._model = None
        self._whisper = None
        
    def _load_model(self):
        """Lazy load the Whisper model."""
        if self._model is None:
            try:
                import whisper
                self._whisper = whisper
                logger.info(f"Loading Whisper model: {self.model_size}")
                self._model = whisper.load_model(
                    self.model_size,
                    device=self.device,
                )
                logger.info(f"Whisper model loaded on device: {self._model.device}")
            except ImportError:
                raise ImportError(
                    "OpenAI Whisper not installed. Run: pip install openai-whisper"
                )
    
    def transcribe_file(self, audio_path: str | Path) -> TranscriptChunk:
        """
        Transcribe an audio file.
        
        Args:
            audio_path: Path to audio file (WAV, MP3, etc.)
            
        Returns:
            TranscriptChunk with transcribed text
        """
        self._load_model()
        
        start_time = time.time()
        result = self._model.transcribe(
            str(audio_path),
            language=self.language,
            fp16=False,  # Disable FP16 for CPU compatibility
        )
        duration = time.time() - start_time
        
        return TranscriptChunk(
            text=result.get("text", "").strip(),
            duration=duration,
            confidence=0.9,  # Whisper doesn't provide confidence scores directly
        )
    
    def transcribe_audio_data(self, audio_data, sample_rate: int = 16000) -> TranscriptChunk:
        """
        Transcribe raw audio data (numpy array).
        
        Args:
            audio_data: Audio as numpy array (float32, mono)
            sample_rate: Sample rate of the audio
            
        Returns:
            TranscriptChunk with transcribed text
        """
        self._load_model()
        
        import numpy as np
        
        # Normalize audio
        audio_data = audio_data.astype(np.float32)
        if audio_data.max() > 1.0:
            audio_data = audio_data / 32768.0
        
        start_time = time.time()
        result = self._model.transcribe(
            audio_data,
            language=self.language,
            fp16=False,
        )
        duration = time.time() - start_time
        
        return TranscriptChunk(
            text=result.get("text", "").strip(),
            duration=duration,
            confidence=0.9,
        )


# =============================================================================
# Audio Source Processors
# =============================================================================

class YouTubeAudioExtractor:
    """Extract audio from YouTube videos using yt-dlp.
    
    Supports:
    - Live streams (chunked extraction)
    - VOD videos (full or chunked extraction)
    
    Uses TemporaryDirectory for automatic cleanup of audio files.
    
    Example:
        >>> extractor = YouTubeAudioExtractor()
        >>> for chunk_path in extractor.stream_audio("https://youtube.com/watch?v=..."):
        ...     process_audio(chunk_path)
    """
    
    def __init__(
        self,
        chunk_duration: int = 20,
        temp_dir: Optional[str] = None,
    ):
        """
        Initialize the YouTube audio extractor.
        
        Args:
            chunk_duration: Duration of each audio chunk in seconds
            temp_dir: Temporary directory for audio files (auto-cleaned if None)
        """
        self.chunk_duration = chunk_duration
        self._temp_dir_obj: Optional[tempfile.TemporaryDirectory] = None
        
        # Use provided dir or create auto-cleaning temp dir
        if temp_dir:
            self.temp_dir = temp_dir
        else:
            self._temp_dir_obj = tempfile.TemporaryDirectory(prefix="regusense_audio_")
            self.temp_dir = self._temp_dir_obj.name
        
        self._audio_files: list[Path] = []  # Track files for cleanup
        self._check_dependencies()
    
    def _check_dependencies(self):
        """Check that yt-dlp and ffmpeg are available."""
        try:
            subprocess.run(
                ["yt-dlp", "--version"],
                capture_output=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("yt-dlp not found. Run: pip install yt-dlp")
        
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("ffmpeg not found. Install from: https://ffmpeg.org/")
    
    def get_video_info(self, url: str) -> dict:
        """Get video metadata including title and channel."""
        try:
            result = subprocess.run(
                [
                    "yt-dlp",
                    "--dump-json",
                    "--no-download",
                    url,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            import json
            return json.loads(result.stdout)
        except Exception as e:
            logger.error(f"Failed to get video info: {e}")
            return {}
    
    def download_full_audio(self, url: str, output_path: Optional[str] = None) -> Path:
        """
        Download full audio from a YouTube video.
        
        Args:
            url: YouTube video URL
            output_path: Optional output path (auto-generated if None)
            
        Returns:
            Path to downloaded audio file
        """
        if output_path is None:
            output_path = Path(self.temp_dir) / f"yt_audio_{int(time.time())}.wav"
        else:
            output_path = Path(output_path)
        
        logger.info(f"Downloading audio from: {url}")
        
        subprocess.run(
            [
                "yt-dlp",
                "-x",  # Extract audio
                "--audio-format", "wav",
                "--audio-quality", "0",
                "-o", str(output_path.with_suffix("")),  # yt-dlp adds extension
                url,
            ],
            check=True,
            capture_output=True,
        )
        
        # Find the actual output file (yt-dlp may add extension)
        actual_path = output_path.with_suffix(".wav")
        if not actual_path.exists():
            # Try without extension change
            for f in output_path.parent.glob(f"{output_path.stem}*"):
                if f.suffix in [".wav", ".mp3", ".m4a"]:
                    return f
        
        return actual_path
    
    def stream_audio_chunks(
        self,
        url: str,
        stop_event: Optional[threading.Event] = None,
    ) -> Generator[Path, None, None]:
        """
        Stream audio in chunks from a YouTube video/live stream.
        
        Args:
            url: YouTube video URL
            stop_event: Optional threading event to stop streaming
            
        Yields:
            Paths to audio chunk files
        """
        # Download full audio first (for VOD)
        # For true live streaming, we would need more complex ffmpeg piping
        audio_path = self.download_full_audio(url)
        
        # Split into chunks using ffmpeg
        chunk_num = 0
        offset = 0
        
        while True:
            if stop_event and stop_event.is_set():
                break
            
            chunk_path = Path(self.temp_dir) / f"chunk_{chunk_num}.wav"
            
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",  # Overwrite
                    "-ss", str(offset),
                    "-t", str(self.chunk_duration),
                    "-i", str(audio_path),
                    "-ar", "16000",  # Whisper prefers 16kHz
                    "-ac", "1",  # Mono
                    str(chunk_path),
                ],
                capture_output=True,
            )
            
            if not chunk_path.exists() or chunk_path.stat().st_size < 1000:
                break  # No more audio
            
            yield chunk_path
            
            # Track file for cleanup and move to next chunk
            self._audio_files.append(chunk_path)
            chunk_num += 1
            offset += self.chunk_duration
        
        # Clean up all files
        self.cleanup()
    
    def cleanup(self) -> None:
        """Clean up all temporary audio files."""
        # Clean tracked files
        for filepath in self._audio_files:
            try:
                if filepath.exists():
                    filepath.unlink()
            except OSError as e:
                logger.debug(f"Failed to delete temp file {filepath}: {e}")
        self._audio_files.clear()
        
        # If using auto-cleaning temp dir, it cleans itself on __del__
        logger.debug("Audio files cleaned up")
    
    def __del__(self):
        """Cleanup on garbage collection."""
        try:
            self.cleanup()
            if self._temp_dir_obj:
                self._temp_dir_obj.cleanup()
        except Exception:
            pass  # Ignore errors during cleanup


class MicrophoneCapture:
    """Capture audio from microphone for real-time transcription.
    
    Uses sounddevice for cross-platform microphone access.
    
    Example:
        >>> mic = MicrophoneCapture()
        >>> for chunk in mic.stream():
        ...     transcribe(chunk)
    """
    
    def __init__(
        self,
        chunk_duration: float = 5.0,
        sample_rate: int = 16000,
        device: Optional[int] = None,
    ):
        """
        Initialize microphone capture.
        
        Args:
            chunk_duration: Duration of each audio chunk in seconds
            sample_rate: Audio sample rate
            device: Input device index (None for default)
        """
        self.chunk_duration = chunk_duration
        self.sample_rate = sample_rate
        self.device = device
        self._check_dependencies()
    
    def _check_dependencies(self):
        """Check that sounddevice is available."""
        try:
            import sounddevice
            self._sd = sounddevice
        except ImportError:
            raise ImportError(
                "sounddevice not installed. Run: pip install sounddevice"
            )
    
    def stream(
        self,
        stop_event: Optional[threading.Event] = None,
    ) -> Generator[tuple, None, None]:
        """
        Stream audio chunks from microphone.
        
        Args:
            stop_event: Threading event to stop streaming
            
        Yields:
            Tuple of (audio_data, sample_rate)
        """
        import numpy as np
        
        chunk_samples = int(self.chunk_duration * self.sample_rate)
        
        logger.info("Starting microphone capture...")
        
        while True:
            if stop_event and stop_event.is_set():
                break
            
            try:
                audio_data = self._sd.rec(
                    chunk_samples,
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype=np.float32,
                    device=self.device,
                )
                self._sd.wait()
                
                yield audio_data.flatten(), self.sample_rate
                
            except Exception as e:
                logger.error(f"Microphone capture error: {e}")
                time.sleep(1)


# =============================================================================
# Live Processor (Main Class)
# =============================================================================

class LiveProcessor:
    """Main class for live speech processing and transcription.
    
    Combines audio capture (YouTube or Microphone) with Whisper transcription
    for real-time speech-to-text conversion.
    
    Example:
        >>> processor = LiveProcessor()
        >>> session = processor.start_youtube_session(
        ...     "https://youtube.com/watch?v=...",
        ...     speaker="Bakan X"
        ... )
        >>> for chunk in processor.stream_transcripts():
        ...     print(chunk.text)
    """
    
    def __init__(
        self,
        whisper_model: str = "base",
        chunk_duration: int = 20,
        on_chunk_callback: Optional[Callable[[TranscriptChunk], None]] = None,
    ):
        """
        Initialize the live processor.
        
        Args:
            whisper_model: Whisper model size
            chunk_duration: Audio chunk duration in seconds
            on_chunk_callback: Optional callback for each transcribed chunk
        """
        self.whisper_model = whisper_model
        self.chunk_duration = chunk_duration
        self.on_chunk_callback = on_chunk_callback
        
        self._transcriber: Optional[WhisperTranscriber] = None
        self._youtube_extractor: Optional[YouTubeAudioExtractor] = None
        self._mic_capture: Optional[MicrophoneCapture] = None
        
        self._current_session: Optional[LiveSession] = None
        self._stop_event = threading.Event()
        self._transcript_queue: queue.Queue = queue.Queue()
        self._processing_thread: Optional[threading.Thread] = None
    
    @property
    def transcriber(self) -> WhisperTranscriber:
        """Lazy-load transcriber."""
        if self._transcriber is None:
            self._transcriber = WhisperTranscriber(model_size=self.whisper_model)
        return self._transcriber
    
    @property
    def youtube_extractor(self) -> YouTubeAudioExtractor:
        """Lazy-load YouTube extractor."""
        if self._youtube_extractor is None:
            self._youtube_extractor = YouTubeAudioExtractor(
                chunk_duration=self.chunk_duration
            )
        return self._youtube_extractor
    
    @property
    def mic_capture(self) -> MicrophoneCapture:
        """Lazy-load microphone capture."""
        if self._mic_capture is None:
            self._mic_capture = MicrophoneCapture(
                chunk_duration=self.chunk_duration
            )
        return self._mic_capture
    
    def get_youtube_speaker(self, url: str) -> str:
        """
        Try to extract speaker name from YouTube video title/channel.
        
        Args:
            url: YouTube URL
            
        Returns:
            Detected speaker name or empty string
        """
        info = self.youtube_extractor.get_video_info(url)
        title = info.get("title", "")
        channel = info.get("channel", "")
        
        # Common patterns in Turkish political videos
        # e.g., "Bakan X Açıkladı", "X Milletvekili Konuşması"
        patterns = [
            r"(Bakan\s+[\w\s]+)",
            r"([\w\s]+\s+Bakanı)",
            r"([\w\s]+\s+Milletvekili)",
            r"^([\w\s]+)\s*[-–]\s*",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return channel or ""
    
    def start_youtube_session(
        self,
        url: str,
        speaker: str = "",
    ) -> LiveSession:
        """
        Start a new live transcription session from YouTube.
        
        Args:
            url: YouTube video URL
            speaker: Optional speaker name (auto-detected if empty)
            
        Returns:
            LiveSession object
        """
        # Auto-detect speaker if not provided
        if not speaker:
            speaker = self.get_youtube_speaker(url)
        
        session_id = f"yt_{int(time.time())}"
        self._current_session = LiveSession(
            session_id=session_id,
            source=url,
            speaker=speaker,
        )
        
        logger.info(f"Started YouTube session: {session_id} (Speaker: {speaker})")
        return self._current_session
    
    def start_microphone_session(self, speaker: str = "") -> LiveSession:
        """
        Start a new live transcription session from microphone.
        
        Args:
            speaker: Speaker name
            
        Returns:
            LiveSession object
        """
        session_id = f"mic_{int(time.time())}"
        self._current_session = LiveSession(
            session_id=session_id,
            source="MICROPHONE",
            speaker=speaker,
        )
        
        logger.info(f"Started microphone session: {session_id}")
        return self._current_session
    
    def stream_youtube(
        self,
        url: str,
        speaker: str = "",
    ) -> Generator[TranscriptChunk, None, None]:
        """
        Stream transcriptions from a YouTube video.
        
        Args:
            url: YouTube video URL
            speaker: Optional speaker name
            
        Yields:
            TranscriptChunk objects as they are processed
        """
        session = self.start_youtube_session(url, speaker)
        self._stop_event.clear()
        
        for audio_chunk_path in self.youtube_extractor.stream_audio_chunks(
            url,
            stop_event=self._stop_event,
        ):
            try:
                chunk = self.transcriber.transcribe_file(audio_chunk_path)
                chunk.speaker = session.speaker
                
                if chunk.text:  # Only yield non-empty chunks
                    session.add_chunk(chunk)
                    
                    if self.on_chunk_callback:
                        self.on_chunk_callback(chunk)
                    
                    yield chunk
                
                # Clean up audio chunk
                try:
                    audio_chunk_path.unlink()
                except:
                    pass
                    
            except Exception as e:
                logger.error(f"Transcription error: {e}")
        
        session.is_active = False
    
    def stream_microphone(
        self,
        speaker: str = "",
    ) -> Generator[TranscriptChunk, None, None]:
        """
        Stream transcriptions from microphone.
        
        Args:
            speaker: Speaker name
            
        Yields:
            TranscriptChunk objects as they are processed
        """
        session = self.start_microphone_session(speaker)
        self._stop_event.clear()
        
        for audio_data, sample_rate in self.mic_capture.stream(
            stop_event=self._stop_event,
        ):
            try:
                chunk = self.transcriber.transcribe_audio_data(audio_data, sample_rate)
                chunk.speaker = session.speaker
                
                if chunk.text:
                    session.add_chunk(chunk)
                    
                    if self.on_chunk_callback:
                        self.on_chunk_callback(chunk)
                    
                    yield chunk
                    
            except Exception as e:
                logger.error(f"Transcription error: {e}")
        
        session.is_active = False
    
    def stop(self):
        """Stop the current live session."""
        self._stop_event.set()
        if self._current_session:
            self._current_session.is_active = False
        logger.info("Live session stopped")
    
    @property
    def current_session(self) -> Optional[LiveSession]:
        """Get the current active session."""
        return self._current_session


# =============================================================================
# Utility Functions
# =============================================================================

def test_whisper_availability() -> bool:
    """Test if Whisper is available and working."""
    try:
        import whisper
        return True
    except ImportError:
        return False


def test_youtube_availability() -> bool:
    """Test if yt-dlp is available."""
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
        return True
    except:
        return False


def test_ffmpeg_availability() -> bool:
    """Test if ffmpeg is available."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except:
        return False


if __name__ == "__main__":
    # Test the live engine
    print("Testing Live Engine Dependencies...")
    print(f"  Whisper: {'✅' if test_whisper_availability() else '❌'}")
    print(f"  yt-dlp:  {'✅' if test_youtube_availability() else '❌'}")
    print(f"  ffmpeg:  {'✅' if test_ffmpeg_availability() else '❌'}")
