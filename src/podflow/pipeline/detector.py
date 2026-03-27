"""RSS polling and new episode detection."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser

from podflow.config import load_podcasts, load_settings
from podflow.db import episode_exists, insert_episode
from podflow.models import Episode, PodcastConfig
from podflow.utils import parse_guests_from_title

logger = logging.getLogger(__name__)


def _parse_published(entry: dict) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
            except (ValueError, OverflowError):
                continue
    return None


def _get_audio_url(entry: dict) -> str | None:
    for link in entry.get("links", []):
        if link.get("type", "").startswith("audio/") or link.get("rel") == "enclosure":
            return link.get("href")
    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("audio/"):
            return enc.get("href")
    return None


def _get_duration_seconds(entry: dict) -> int | None:
    duration_str = entry.get("itunes_duration", "")
    if not duration_str:
        return None
    try:
        parts = str(duration_str).split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        else:
            return int(parts[0])
    except (ValueError, IndexError):
        return None


def _get_episode_number(entry: dict) -> str | None:
    ep = entry.get("itunes_episode")
    if ep:
        return str(ep)
    return None


def _get_guid(entry: dict) -> str:
    return entry.get("id") or entry.get("link") or entry.get("title", "")


def detect_new_episodes(podcast: PodcastConfig, lookback_days: int = 7) -> list[Episode]:
    """Poll a single podcast feed and return new episodes."""
    logger.info(f"Polling feed: {podcast.name}")
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    try:
        feed = feedparser.parse(podcast.rss_url)
    except Exception as e:
        logger.error(f"Failed to parse feed for {podcast.name}: {e}")
        return []

    if feed.bozo and not feed.entries:
        logger.warning(f"Feed error for {podcast.name}: {feed.bozo_exception}")
        return []

    new_episodes = []
    for entry in feed.entries:
        pub_date = _parse_published(entry)
        if pub_date and pub_date < cutoff:
            continue

        guid = _get_guid(entry)
        if not guid:
            continue

        if episode_exists(podcast.slug, guid):
            continue

        audio_url = _get_audio_url(entry)
        guests = parse_guests_from_title(entry.get("title", ""), podcast.hosts)

        ep = Episode(
            podcast_slug=podcast.slug,
            podcast_name=podcast.name,
            title=entry.get("title", "Untitled"),
            published_date=pub_date,
            audio_url=audio_url,
            duration_seconds=_get_duration_seconds(entry),
            description=entry.get("summary", ""),
            episode_number=_get_episode_number(entry),
            guests=guests,
            rss_guid=guid,
            audience=podcast.audience,
        )

        ep_id = insert_episode(ep)
        if ep_id:
            ep.id = ep_id
            new_episodes.append(ep)
            logger.info(f"  New episode: {ep.title}")

    logger.info(f"  Found {len(new_episodes)} new episode(s) for {podcast.name}")
    return new_episodes


def poll_all_feeds() -> list[Episode]:
    """Poll all enabled podcasts and return new episodes."""
    settings = load_settings()
    podcasts = load_podcasts()
    all_new = []

    enabled = [p for p in podcasts if p.enabled]
    logger.info(f"Polling {len(enabled)} enabled podcast(s)...")

    for podcast in sorted(enabled, key=lambda p: p.priority):
        try:
            new_eps = detect_new_episodes(podcast, settings.polling.lookback_days)
            all_new.extend(new_eps)
        except Exception as e:
            logger.error(f"Error polling {podcast.name}: {e}")
            continue

    logger.info(f"Total new episodes detected: {len(all_new)}")
    return all_new


# ============================================
# Unified source polling (v3)
# ============================================

def poll_all_sources() -> list:
    """Poll all enabled sources (podcasts, newsletters, X feeds). Returns new ContentItems."""
    from podflow.db import (
        content_item_exists,
        get_all_sources,
        insert_content_item,
    )
    from podflow.models import ContentItem, ContentStatus, SourceType
    from podflow.pipeline.fetcher import fetch_newsletter_text, fetch_x_thread_text, save_content_text

    settings = load_settings()
    sources = get_all_sources()
    all_new = []

    logger.info(f"Polling {len(sources)} enabled source(s)...")

    for src in sources:
        rss_url = src.get("rss_url")
        if not rss_url:
            continue

        source_type = src["type"]
        tl_slug = src["tl_slug"]
        tl_name = src["tl_name"]
        source_id = src["id"]
        tl_tags = json.loads(src.get("tl_tags") or "[]")

        try:
            feed = feedparser.parse(rss_url)
        except Exception as e:
            logger.error(f"Failed to parse feed for {tl_name} ({source_type}): {e}")
            continue

        if feed.bozo and not feed.entries:
            logger.debug(f"Feed error for {tl_name}: {feed.bozo_exception}")
            continue

        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.polling.lookback_days)
        new_count = 0

        for entry in feed.entries:
            pub_date = _parse_published(entry)
            if pub_date and pub_date < cutoff:
                continue

            guid = _get_guid(entry)
            if not guid:
                continue

            if content_item_exists(source_id, guid):
                continue

            title = entry.get("title", "Untitled")

            # Source-type specific handling
            content_url = None
            duration = None
            description = entry.get("summary", "")
            transcript_path = None
            status = ContentStatus.detected

            if source_type == "podcast":
                content_url = _get_audio_url(entry)
                duration = _get_duration_seconds(entry)
            elif source_type == "newsletter":
                content_url = entry.get("link")
                # Try to extract text immediately
                text = fetch_newsletter_text(entry)
                if text and len(text) > 300:
                    # Save and mark for analysis (skip transcription step)
                    item_id_placeholder = hash(f"{source_id}:{guid}") & 0x7FFFFFFF
                    transcript_path = save_content_text(tl_slug, item_id_placeholder, text, "newsletter")
                    status = ContentStatus.complete
            elif source_type == "x_twitter":
                content_url = entry.get("link")
                text = fetch_x_thread_text(entry)
                if not text or len(text) < settings.x_twitter.min_tweet_length:
                    continue  # Skip short tweets
                if text.startswith("RT @"):
                    continue  # Skip retweets
                item_id_placeholder = hash(f"{source_id}:{guid}") & 0x7FFFFFFF
                transcript_path = save_content_text(tl_slug, item_id_placeholder, text, "x_twitter")
                status = ContentStatus.complete

            item = ContentItem(
                source_id=source_id,
                thought_leader_slug=tl_slug,
                source_type=SourceType(source_type),
                title=title,
                published_date=pub_date,
                content_url=content_url,
                duration_seconds=duration,
                description=description[:500] if description else None,
                guid=guid,
                status=status,
                transcript_local_path=transcript_path,
                tags=tl_tags,
            )

            item_id = insert_content_item(item)
            if item_id:
                item.id = item_id
                # Update transcript path with real ID if we saved content
                if transcript_path and status == ContentStatus.complete:
                    real_path = save_content_text(tl_slug, item_id,
                        Path(transcript_path).read_text() if Path(transcript_path).exists() else "",
                        source_type)
                    item.transcript_local_path = real_path
                    from podflow.db import update_content_item
                    item.completed_at = datetime.now(timezone.utc)
                    update_content_item(item)

                all_new.append(item)
                new_count += 1

        if new_count:
            logger.info(f"  {tl_name} ({source_type}): +{new_count} items")

    logger.info(f"Total new content items: {len(all_new)}")
    return all_new


import json
from pathlib import Path


def test_feed(podcast: PodcastConfig, count: int = 5) -> list[dict]:
    """Fetch and return the latest entries from a feed for testing."""
    feed = feedparser.parse(podcast.rss_url)
    results = []
    for entry in feed.entries[:count]:
        results.append({
            "title": entry.get("title", "Untitled"),
            "published": str(_parse_published(entry) or "unknown"),
            "audio_url": _get_audio_url(entry),
            "duration": _get_duration_seconds(entry),
            "guid": _get_guid(entry),
        })
    return results
