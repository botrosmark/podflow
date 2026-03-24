"""Metadata enrichment — format transcript for storage."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from podflow.config import get_podcast_by_slug
from podflow.models import Episode, Transcript
from podflow.utils import format_duration, sanitize_filename

logger = logging.getLogger(__name__)


def build_transcript_markdown(episode: Episode, transcript: Transcript) -> str:
    """Build the Markdown transcript with YAML frontmatter."""
    podcast = get_podcast_by_slug(episode.podcast_slug)
    hosts = podcast.hosts if podcast else []
    guests = episode.guests or []
    duration_min = (episode.duration_seconds // 60) if episode.duration_seconds else 0

    frontmatter = f"""---
podcast: "{episode.podcast_name}"
episode: "{episode.episode_number or ''}"
title: "{episode.title}"
date: "{episode.published_date.strftime('%Y-%m-%d') if episode.published_date else ''}"
hosts: {hosts}
guests: {guests}
duration_minutes: {duration_min}
category: {podcast.category if podcast else 'unknown'}
transcript_confidence: {transcript.confidence:.2f}
speakers_detected: {transcript.speakers_detected}
word_count: {transcript.word_count}
processed_at: "{datetime.now(timezone.utc).isoformat(timespec='seconds')}Z"
---"""

    header = f"# {episode.title}\n\n"
    header += f"**Podcast:** {episode.podcast_name}"
    if episode.published_date:
        header += f" | **Date:** {episode.published_date.strftime('%B %d, %Y')}"
    if duration_min:
        header += f" | **Duration:** {format_duration(episode.duration_seconds)}"
    header += "\n\n## Transcript\n"

    body_lines = []
    if transcript.segments:
        for seg in transcript.segments:
            body_lines.append(f"\n**{seg.speaker}:** {seg.text}\n")
    else:
        body_lines.append(f"\n{transcript.raw_text}\n")

    return frontmatter + "\n\n" + header + "\n".join(body_lines)


def build_filename(episode: Episode) -> str:
    """Generate the Drive filename for a transcript."""
    date_str = episode.published_date.strftime("%Y-%m-%d") if episode.published_date else "unknown"
    ep_num = f"_EP{episode.episode_number}" if episode.episode_number else ""

    # Use first guest or truncated title
    name_part = ""
    if episode.guests:
        name_part = f"_{sanitize_filename(episode.guests[0])}"
    else:
        words = episode.title.split()[:5]
        name_part = f"_{sanitize_filename(' '.join(words))}"

    return f"{date_str}{ep_num}{name_part}"
