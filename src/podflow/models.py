"""Pydantic models for podflow."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ============================================
# Legacy models (kept for backward compat)
# ============================================

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
    audience: str = "mark"
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
    audience: Optional[str] = None
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


# ============================================
# New thought-leader-centric models
# ============================================

class SourceType(str, Enum):
    podcast = "podcast"
    newsletter = "newsletter"
    x_twitter = "x_twitter"
    youtube = "youtube"


class ContentStatus(str, Enum):
    detected = "detected"
    fetching = "fetching"
    transcribing = "transcribing"
    storing = "storing"
    complete = "complete"
    error = "error"
    skipped = "skipped"


class SourceConfig(BaseModel):
    type: SourceType
    platform: Optional[str] = None
    name: Optional[str] = None
    rss_url: Optional[str] = None
    web_url: Optional[str] = None
    handle: Optional[str] = None
    hosts: list[str] = Field(default_factory=list)
    category: Optional[str] = None
    enabled: bool = True


class ThoughtLeaderConfig(BaseModel):
    name: str
    slug: str
    tags: list[str] = Field(default_factory=list)
    priority: int = 2
    enabled: bool = True
    sources: list[SourceConfig] = Field(default_factory=list)


class ContentItem(BaseModel):
    id: Optional[int] = None
    source_id: int
    thought_leader_slug: str
    source_type: SourceType
    title: str
    published_date: Optional[datetime] = None
    content_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    description: Optional[str] = None
    guid: str
    status: ContentStatus = ContentStatus.detected
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    transcript_local_path: Optional[str] = None
    drive_file_id: Optional[str] = None
    drive_url: Optional[str] = None
    assemblyai_transcript_id: Optional[str] = None
    word_count: Optional[int] = None
    guests: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


# ============================================
# Settings
# ============================================

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
    idea_bank_spreadsheet_id: Optional[str] = None


class ProcessingSettings(BaseModel):
    download_dir: str = "/tmp/podflow/audio"
    keep_audio: bool = False


class AnalysisSettings(BaseModel):
    enabled: bool = False
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    max_transcript_tokens: int = 120000


class XTwitterSettings(BaseModel):
    provider: str = "rss_app"
    poll_interval_minutes: int = 60
    min_tweet_length: int = 100
    include_threads: bool = True


class EmailSettings(BaseModel):
    enabled: bool = True
    provider: str = "resend"
    mark_recipients: list[str] = Field(default_factory=lambda: ["botros.mark.a@gmail.com"])
    brooke_recipients: list[str] = Field(default_factory=lambda: ["botros.mark.a@gmail.com"])
    brief_time: str = "06:00"
    lookback_hours: int = 24


class Settings(BaseModel):
    polling: PollingSettings = PollingSettings()
    transcription: TranscriptionSettings = TranscriptionSettings()
    storage: StorageSettings = StorageSettings()
    processing: ProcessingSettings = ProcessingSettings()
    analysis: AnalysisSettings = AnalysisSettings()
    x_twitter: XTwitterSettings = XTwitterSettings()
    email: EmailSettings = EmailSettings()
