"""AssemblyAI transcription integration."""

from __future__ import annotations

import logging
import time

import requests

from podflow.config import get_assemblyai_key, load_settings
from podflow.db import update_episode
from podflow.models import Episode, EpisodeStatus, Transcript, TranscriptSegment

logger = logging.getLogger(__name__)

API_BASE = "https://api.assemblyai.com/v2"


def _headers() -> dict:
    return {"Authorization": get_assemblyai_key(), "Content-Type": "application/json"}


def transcribe_episode(episode: Episode) -> Transcript:
    """Submit audio to AssemblyAI and return structured transcript."""
    settings = load_settings()

    audio_source = episode.audio_url
    if not audio_source:
        raise ValueError(f"No audio URL for episode: {episode.title}")

    episode.status = EpisodeStatus.transcribing
    update_episode(episode)

    logger.info(f"Submitting to AssemblyAI: {episode.title}")

    # Submit transcription request using raw API
    payload = {
        "audio_url": audio_source,
        "speech_models": ["universal-3-pro"],
        "speaker_labels": settings.transcription.speaker_diarization,
        "language_code": settings.transcription.language_code,
    }

    resp = requests.post(f"{API_BASE}/transcript", json=payload, headers=_headers())
    resp.raise_for_status()
    transcript_data = resp.json()
    transcript_id = transcript_data["id"]

    episode.assemblyai_transcript_id = transcript_id
    update_episode(episode)

    # Poll for completion
    poll_interval = settings.transcription.poll_interval_seconds
    max_wait = settings.transcription.max_wait_minutes * 60
    elapsed = 0

    while elapsed < max_wait:
        resp = requests.get(f"{API_BASE}/transcript/{transcript_id}", headers=_headers())
        resp.raise_for_status()
        result = resp.json()
        status = result["status"]

        if status == "completed":
            break
        elif status == "error":
            raise RuntimeError(f"Transcription failed: {result.get('error', 'unknown error')}")
        else:
            logger.debug(f"  Status: {status}, waiting {poll_interval}s...")
            time.sleep(poll_interval)
            elapsed += poll_interval
    else:
        raise RuntimeError(f"Transcription timed out after {max_wait}s")

    # Parse results
    segments = []
    for utt in result.get("utterances") or []:
        segments.append(TranscriptSegment(
            speaker=f"Speaker {utt['speaker']}",
            text=utt["text"],
            start_ms=utt["start"],
            end_ms=utt["end"],
        ))

    speakers_detected = len({s.speaker for s in segments}) if segments else 0
    raw_text = result.get("text") or ""
    word_count = len(raw_text.split()) if raw_text else 0
    confidence = result.get("confidence") or 0.0

    transcript = Transcript(
        episode_id=episode.id,
        raw_text=raw_text,
        segments=segments,
        word_count=word_count,
        duration_seconds=episode.duration_seconds or 0,
        confidence=confidence,
        speakers_detected=speakers_detected,
        language=settings.transcription.language_code,
    )

    logger.info(
        f"Transcription complete: {word_count} words, "
        f"{speakers_detected} speakers, "
        f"confidence={confidence:.2f}"
    )
    return transcript
