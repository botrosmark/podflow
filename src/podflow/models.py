"""Pydantic models for podflow."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EpisodeStatus(str, Enum):
    detected = "detected"
    downloading = "downloading"
    transcribing = "transcribing"
    storing = "storing"
    complete = "complete"
    error = "error"


class PodcastConfig(BaseModel):
    name: str
    slug: str
    rss_url: str
    category: str
    hosts: list[str] = Field(default_factory=list)
    priority: int = 2
    enabled: bool = True


class Episode(BaseModel):
    id: Optional[int] = None
    podcast_slug: str
    podcast_name: str
    title: str
    published_date: Optional[datetime] = None
    audio_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    description: Optional[str] = None
    episode_number: Optional[str] = None
    guests: list[str] = Field(default_factory=list)
    rss_guid: str
    status: EpisodeStatus = EpisodeStatus.detected
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    audio_local_path: Optional[str] = None
    transcript_local_path: Optional[str] = None
    drive_file_id: Optional[str] = None
    drive_url: Optional[str] = None
    assemblyai_transcript_id: Optional[str] = None
    # Future analysis fields
    summary: Optional[str] = None
    key_quotes: Optional[list[str]] = None
    themes: Optional[list[str]] = None
    content_brief: Optional[str] = None


class TranscriptSegment(BaseModel):
    speaker: str
    text: str
    start_ms: int
    end_ms: int


class Transcript(BaseModel):
    episode_id: int
    raw_text: str
    segments: list[TranscriptSegment] = Field(default_factory=list)
    word_count: int = 0
    duration_seconds: int = 0
    confidence: float = 0.0
    speakers_detected: int = 0
    language: str = "en"


class PollingSettings(BaseModel):
    interval_minutes: int = 30
    max_episodes_per_run: int = 10
    lookback_days: int = 7


class TranscriptionSettings(BaseModel):
    provider: str = "assemblyai"
    speaker_diarization: bool = True
    language_code: str = "en"
    poll_interval_seconds: int = 30
    max_wait_minutes: int = 60


class StorageSettings(BaseModel):
    provider: str = "google_drive"
    root_folder_name: str = "Podcast Transcripts"
    root_folder_id: Optional[str] = None
    transcript_format: str = "markdown"


class ProcessingSettings(BaseModel):
    download_dir: str = "/tmp/podflow/audio"
    keep_audio: bool = False


class AnalysisSettings(BaseModel):
    enabled: bool = False
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"


class Settings(BaseModel):
    polling: PollingSettings = PollingSettings()
    transcription: TranscriptionSettings = TranscriptionSettings()
    storage: StorageSettings = StorageSettings()
    processing: ProcessingSettings = ProcessingSettings()
    analysis: AnalysisSettings = AnalysisSettings()
