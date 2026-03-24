"""Google Drive upload stage."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from podflow.config import get_podcast_by_slug, load_settings
from podflow.db import update_episode
from podflow.drive import get_drive_service, get_podcast_folder_id, upload_markdown
from podflow.models import Episode, EpisodeStatus, Transcript
from podflow.pipeline.enricher import build_filename, build_transcript_markdown

logger = logging.getLogger(__name__)


def store_transcript(episode: Episode, transcript: Transcript) -> Episode:
    """Format and upload transcript to Google Drive."""
    settings = load_settings()
    podcast = get_podcast_by_slug(episode.podcast_slug)
    if not podcast:
        raise ValueError(f"Unknown podcast slug: {episode.podcast_slug}")

    episode.status = EpisodeStatus.storing
    update_episode(episode)

    markdown = build_transcript_markdown(episode, transcript)
    filename = build_filename(episode)

    logger.info(f"Uploading to Drive: {filename}")

    service = get_drive_service()
    folder_id = get_podcast_folder_id(
        service,
        settings.storage.root_folder_name,
        podcast.category,
        podcast.name,
    )

    result = upload_markdown(service, markdown, filename, folder_id)

    episode.drive_file_id = result["id"]
    episode.drive_url = result["url"]
    episode.status = EpisodeStatus.complete
    episode.completed_at = datetime.now(timezone.utc)
    update_episode(episode)

    logger.info(f"Uploaded: {filename} -> {result['url']}")
    return episode
