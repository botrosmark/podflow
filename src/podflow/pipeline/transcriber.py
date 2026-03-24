"""AssemblyAI transcription integration."""

from __future__ import annotations

import logging

import requests

from podflow.config import get_assemblyai_key, load_settings
from podflow.db import update_episode
from podflow.models import Episode, EpisodeStatus, Transcript, TranscriptSegment

logger = logging.getLogger(__name__)

API_BASE = "https://api.assemblyai.com/v2"


def _headers() -> dict:
    return {"Authorization": get_assemblyai_key(), "Content-Type": "application/json"}


def _parse_transcript_result(episode: Episode, result: dict) -> Transcript:
    """Parse a completed AssemblyAI response into a Transcript."""
    settings = load_settings()
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

    return Transcript(
        episode_id=episode.id,
        raw_text=raw_text,
        segments=segments,
        word_count=word_count,
        duration_seconds=episode.duration_seconds or 0,
        confidence=confidence,
        speakers_detected=speakers_detected,
        language=settings.transcription.language_code,
    )


def submit_transcription(episode: Episode) -> str:
    """Submit audio to AssemblyAI. Returns transcript ID immediately (non-blocking)."""
    settings = load_settings()

    if not episode.audio_url:
        raise ValueError(f"No audio URL for episode: {episode.title}")

    episode.status = EpisodeStatus.transcribing
    update_episode(episode)

    logger.info(f"Submitting to AssemblyAI: {episode.title}")

    payload = {
        "audio_url": episode.audio_url,
        "speech_models": ["universal-3-pro"],
        "speaker_labels": settings.transcription.speaker_diarization,
        "language_code": settings.transcription.language_code,
    }

    resp = requests.post(f"{API_BASE}/transcript", json=payload, headers=_headers())
    resp.raise_for_status()
    transcript_id = resp.json()["id"]

    episode.assemblyai_transcript_id = transcript_id
    update_episode(episode)

    logger.info(f"  Submitted: {transcript_id}")
    return transcript_id


def check_transcription(episode: Episode) -> Transcript | None:
    """Check if a submitted transcription is complete. Returns Transcript if done, None if still processing."""
    transcript_id = episode.assemblyai_transcript_id
    if not transcript_id:
        raise ValueError(f"No AssemblyAI transcript ID for episode: {episode.title}")

    resp = requests.get(f"{API_BASE}/transcript/{transcript_id}", headers=_headers())
    resp.raise_for_status()
    result = resp.json()
    status = result["status"]

    if status == "completed":
        transcript = _parse_transcript_result(episode, result)
        logger.info(
            f"Transcription complete for '{episode.title}': {transcript.word_count} words, "
            f"{transcript.speakers_detected} speakers, confidence={transcript.confidence:.2f}"
        )
        return transcript
    elif status == "error":
        error_msg = result.get("error", "unknown error")
        episode.status = EpisodeStatus.error
        episode.error_message = f"AssemblyAI error: {error_msg}"
        update_episode(episode)
        raise RuntimeError(f"Transcription failed: {error_msg}")
    else:
        logger.debug(f"  '{episode.title}' still {status}")
        return None


# Keep legacy sync function for test-transcribe CLI and backwards compat
def transcribe_episode(episode: Episode) -> Transcript:
    """Submit audio to AssemblyAI and poll until complete (blocking)."""
    import time

    settings = load_settings()
    submit_transcription(episode)

    poll_interval = settings.transcription.poll_interval_seconds
    max_wait = settings.transcription.max_wait_minutes * 60
    elapsed = 0

    while elapsed < max_wait:
        transcript = check_transcription(episode)
        if transcript is not None:
            return transcript
        time.sleep(poll_interval)
        elapsed += poll_interval

    raise RuntimeError(f"Transcription timed out after {max_wait}s")
