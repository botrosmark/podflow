"""Audio download."""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from podflow.config import load_settings
from podflow.db import update_episode
from podflow.models import Episode, EpisodeStatus

logger = logging.getLogger(__name__)


def download_audio(episode: Episode) -> Episode:
    """Download episode audio to local storage.

    Note: AssemblyAI can fetch audio URLs directly, so this step is only
    needed if the audio URL requires authentication or is ephemeral.
    For most podcast RSS feeds, we skip local download and pass the URL
    directly to AssemblyAI.
    """
    if not episode.audio_url:
        raise ValueError(f"No audio URL for episode: {episode.title}")

    settings = load_settings()
    download_dir = Path(settings.processing.download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{episode.podcast_slug}_{episode.id}.mp3"
    filepath = download_dir / filename

    episode.status = EpisodeStatus.downloading
    update_episode(episode)

    logger.info(f"Downloading audio: {episode.title}")
    try:
        resp = requests.get(episode.audio_url, stream=True, timeout=300)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        episode.audio_local_path = str(filepath)
        update_episode(episode)
        logger.info(f"Downloaded to {filepath}")
    except Exception as e:
        logger.error(f"Download failed for {episode.title}: {e}")
        raise

    return episode


def cleanup_audio(episode: Episode) -> None:
    """Remove local audio file if configured."""
    settings = load_settings()
    if not settings.processing.keep_audio and episode.audio_local_path:
        path = Path(episode.audio_local_path)
        if path.exists():
            path.unlink()
            logger.debug(f"Cleaned up audio: {path}")
