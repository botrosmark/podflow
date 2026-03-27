"""SQLite state management."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from podflow.config import get_data_dir
from podflow.models import ContentItem, ContentStatus, Episode, EpisodeStatus, SourceType

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 3


def _get_db_path() -> Path:
    return get_data_dir() / "podflow.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_get_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        # Legacy tables (kept for backward compat)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            );

            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                podcast_slug TEXT NOT NULL,
                podcast_name TEXT NOT NULL,
                title TEXT NOT NULL,
                published_date TEXT,
                audio_url TEXT,
                duration_seconds INTEGER,
                description TEXT,
                episode_number TEXT,
                guests TEXT DEFAULT '[]',
                rss_guid TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'detected',
                detected_at TEXT NOT NULL,
                completed_at TEXT,
                error_message TEXT,
                audio_local_path TEXT,
                transcript_local_path TEXT,
                drive_file_id TEXT,
                drive_url TEXT,
                assemblyai_transcript_id TEXT,
                audience TEXT,
                summary TEXT,
                key_quotes TEXT,
                themes TEXT,
                content_brief TEXT,
                UNIQUE(podcast_slug, rss_guid)
            );

            CREATE INDEX IF NOT EXISTS idx_episodes_status ON episodes(status);
            CREATE INDEX IF NOT EXISTS idx_episodes_slug ON episodes(podcast_slug);
            CREATE INDEX IF NOT EXISTS idx_episodes_published ON episodes(published_date);

            CREATE TABLE IF NOT EXISTS episode_analysis (
                episode_id TEXT PRIMARY KEY,
                analysis_json TEXT NOT NULL,
                one_sentence_summary TEXT,
                topic_tags TEXT,
                companies_json TEXT,
                macro_calls_json TEXT,
                content_hooks_json TEXT,
                marketing_tactics_json TEXT,
                people_json TEXT,
                contrarian_takes_json TEXT,
                why_it_matters_mark TEXT,
                why_it_matters_brooke TEXT,
                analyzed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS briefs_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brief_type TEXT NOT NULL,
                sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                episodes_covered TEXT NOT NULL,
                recipient TEXT
            );

            -- New v3 tables
            CREATE TABLE IF NOT EXISTS thought_leaders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                priority INTEGER NOT NULL DEFAULT 2,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thought_leader_id INTEGER NOT NULL REFERENCES thought_leaders(id),
                type TEXT NOT NULL,
                platform TEXT,
                name TEXT,
                rss_url TEXT,
                web_url TEXT,
                handle TEXT,
                hosts TEXT DEFAULT '[]',
                category TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_polled_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_sources_tl ON sources(thought_leader_id);
            CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(type);

            CREATE TABLE IF NOT EXISTS content_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id),
                thought_leader_slug TEXT NOT NULL,
                source_type TEXT NOT NULL,
                title TEXT NOT NULL,
                published_date TEXT,
                content_url TEXT,
                duration_seconds INTEGER,
                description TEXT,
                guid TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'detected',
                detected_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT,
                error_message TEXT,
                transcript_local_path TEXT,
                drive_file_id TEXT,
                drive_url TEXT,
                assemblyai_transcript_id TEXT,
                word_count INTEGER,
                guests TEXT DEFAULT '[]',
                tags TEXT DEFAULT '[]',
                UNIQUE(source_id, guid)
            );

            CREATE INDEX IF NOT EXISTS idx_ci_status ON content_items(status);
            CREATE INDEX IF NOT EXISTS idx_ci_tl ON content_items(thought_leader_slug);
            CREATE INDEX IF NOT EXISTS idx_ci_type ON content_items(source_type);
            CREATE INDEX IF NOT EXISTS idx_ci_published ON content_items(published_date);

            CREATE TABLE IF NOT EXISTS content_analysis (
                content_item_id INTEGER PRIMARY KEY REFERENCES content_items(id),
                analysis_json TEXT NOT NULL,
                one_sentence_summary TEXT,
                topic_tags TEXT,
                companies_json TEXT,
                macro_calls_json TEXT,
                content_hooks_json TEXT,
                marketing_tactics_json TEXT,
                people_json TEXT,
                contrarian_takes_json TEXT,
                why_it_matters TEXT,
                source_type TEXT,
                analyzed_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)

        # Migration: add audience column to episodes if missing
        cursor = conn.execute("PRAGMA table_info(episodes)")
        columns = {row["name"] for row in cursor.fetchall()}
        if "audience" not in columns:
            conn.execute("ALTER TABLE episodes ADD COLUMN audience TEXT")

        # Set schema version
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        elif row["version"] < SCHEMA_VERSION:
            conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
        conn.commit()
    finally:
        conn.close()


# ============================================
# Config → DB sync
# ============================================

def sync_thought_leaders_from_config() -> None:
    """Upsert thought leaders and sources from YAML config into DB."""
    from podflow.config import load_thought_leaders
    leaders = load_thought_leaders()
    if not leaders:
        return

    conn = get_connection()
    try:
        for tl in leaders:
            # Upsert thought leader
            conn.execute("""
                INSERT INTO thought_leaders (slug, name, tags, priority, enabled, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(slug) DO UPDATE SET
                    name=excluded.name, tags=excluded.tags,
                    priority=excluded.priority, enabled=excluded.enabled,
                    updated_at=datetime('now')
            """, (tl.slug, tl.name, json.dumps(tl.tags), tl.priority, int(tl.enabled)))

            tl_id = conn.execute(
                "SELECT id FROM thought_leaders WHERE slug = ?", (tl.slug,)
            ).fetchone()["id"]

            for src in tl.sources:
                # Check if source already exists by rss_url or handle
                existing = None
                if src.rss_url:
                    existing = conn.execute(
                        "SELECT id FROM sources WHERE thought_leader_id = ? AND rss_url = ?",
                        (tl_id, src.rss_url)
                    ).fetchone()
                elif src.handle:
                    existing = conn.execute(
                        "SELECT id FROM sources WHERE thought_leader_id = ? AND handle = ?",
                        (tl_id, src.handle)
                    ).fetchone()

                if existing:
                    conn.execute("""
                        UPDATE sources SET type=?, platform=?, name=?, rss_url=?,
                            web_url=?, handle=?, hosts=?, category=?, enabled=?
                        WHERE id=?
                    """, (src.type.value, src.platform, src.name, src.rss_url,
                          src.web_url, src.handle, json.dumps(src.hosts),
                          src.category, int(src.enabled), existing["id"]))
                else:
                    conn.execute("""
                        INSERT INTO sources (thought_leader_id, type, platform, name,
                            rss_url, web_url, handle, hosts, category, enabled)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (tl_id, src.type.value, src.platform, src.name,
                          src.rss_url, src.web_url, src.handle,
                          json.dumps(src.hosts), src.category, int(src.enabled)))

        conn.commit()
        logger.info(f"Synced {len(leaders)} thought leaders to DB")
    finally:
        conn.close()


def get_all_sources() -> list[dict]:
    """Get all enabled sources with thought leader info."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT s.*, tl.slug as tl_slug, tl.name as tl_name,
                   tl.tags as tl_tags, tl.priority as tl_priority
            FROM sources s
            JOIN thought_leaders tl ON s.thought_leader_id = tl.id
            WHERE s.enabled = 1 AND tl.enabled = 1
            ORDER BY tl.priority ASC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_source_by_id(source_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT s.*, tl.slug as tl_slug, tl.name as tl_name, tl.tags as tl_tags
            FROM sources s
            JOIN thought_leaders tl ON s.thought_leader_id = tl.id
            WHERE s.id = ?
        """, (source_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ============================================
# Content Items (new unified model)
# ============================================

def _row_to_content_item(row: sqlite3.Row) -> ContentItem:
    d = dict(row)
    d["guests"] = json.loads(d.get("guests") or "[]")
    d["tags"] = json.loads(d.get("tags") or "[]")
    d["source_type"] = SourceType(d["source_type"])
    d["status"] = ContentStatus(d["status"])
    if d.get("published_date"):
        d["published_date"] = datetime.fromisoformat(d["published_date"])
    if d.get("detected_at"):
        d["detected_at"] = datetime.fromisoformat(d["detected_at"])
    if d.get("completed_at"):
        d["completed_at"] = datetime.fromisoformat(d["completed_at"])
    return ContentItem(**d)


def insert_content_item(item: ContentItem) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO content_items
            (source_id, thought_leader_slug, source_type, title, published_date,
             content_url, duration_seconds, description, guid, status,
             detected_at, guests, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (item.source_id, item.thought_leader_slug, item.source_type.value,
              item.title, item.published_date.isoformat() if item.published_date else None,
              item.content_url, item.duration_seconds, item.description,
              item.guid, item.status.value,
              item.detected_at.isoformat() if item.detected_at else datetime.utcnow().isoformat(),
              json.dumps(item.guests), json.dumps(item.tags)))
        conn.commit()
        return cursor.lastrowid or 0
    finally:
        conn.close()


def update_content_item(item: ContentItem) -> None:
    if item.id is None:
        raise ValueError("Cannot update content item without id")
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE content_items SET
                status=?, completed_at=?, error_message=?, transcript_local_path=?,
                drive_file_id=?, drive_url=?, assemblyai_transcript_id=?, word_count=?
            WHERE id=?
        """, (item.status.value,
              item.completed_at.isoformat() if item.completed_at else None,
              item.error_message, item.transcript_local_path,
              item.drive_file_id, item.drive_url,
              item.assemblyai_transcript_id, item.word_count, item.id))
        conn.commit()
    finally:
        conn.close()


def content_item_exists(source_id: int, guid: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM content_items WHERE source_id = ? AND guid = ?",
            (source_id, guid),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_content_items_by_status(status: ContentStatus, source_type: str | None = None,
                                 limit: int = 500) -> list[ContentItem]:
    conn = get_connection()
    try:
        if source_type:
            rows = conn.execute(
                "SELECT * FROM content_items WHERE status = ? AND source_type = ? ORDER BY detected_at DESC LIMIT ?",
                (status.value, source_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM content_items WHERE status = ? ORDER BY detected_at DESC LIMIT ?",
                (status.value, limit),
            ).fetchall()
        return [_row_to_content_item(r) for r in rows]
    finally:
        conn.close()


def get_recent_content_items(limit: int = 50, thought_leader_slug: str | None = None,
                              source_type: str | None = None) -> list[ContentItem]:
    conn = get_connection()
    try:
        sql = "SELECT * FROM content_items WHERE 1=1"
        params: list = []
        if thought_leader_slug:
            sql += " AND thought_leader_slug = ?"
            params.append(thought_leader_slug)
        if source_type:
            sql += " AND source_type = ?"
            params.append(source_type)
        sql += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_content_item(r) for r in rows]
    finally:
        conn.close()


def get_content_item_by_id(item_id: int) -> ContentItem | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM content_items WHERE id = ?", (item_id,)).fetchone()
        return _row_to_content_item(row) if row else None
    finally:
        conn.close()


def get_unanalyzed_content() -> list[ContentItem]:
    """Get completed content items without analysis."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT ci.* FROM content_items ci
            LEFT JOIN content_analysis ca ON ci.id = ca.content_item_id
            WHERE ci.status = 'complete'
            AND ci.transcript_local_path IS NOT NULL
            AND ca.content_item_id IS NULL
            ORDER BY ci.published_date DESC
        """).fetchall()
        return [_row_to_content_item(r) for r in rows]
    finally:
        conn.close()


def save_content_analysis(content_item_id: int, analysis_json: str, summary: str,
                           topic_tags: str, companies_json: str, macro_calls_json: str,
                           content_hooks_json: str, marketing_tactics_json: str,
                           people_json: str, contrarian_takes_json: str,
                           why_it_matters: str | None, source_type: str) -> None:
    conn = get_connection()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO content_analysis
            (content_item_id, analysis_json, one_sentence_summary, topic_tags,
             companies_json, macro_calls_json, content_hooks_json,
             marketing_tactics_json, people_json, contrarian_takes_json,
             why_it_matters, source_type, analyzed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (content_item_id, analysis_json, summary, topic_tags,
              companies_json, macro_calls_json, content_hooks_json,
              marketing_tactics_json, people_json, contrarian_takes_json,
              why_it_matters, source_type))
        conn.commit()
    finally:
        conn.close()


def get_content_analysis(content_item_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM content_analysis WHERE content_item_id = ?", (content_item_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_analyzed_content_since(since: datetime) -> list[dict]:
    """Get analyzed content since a given datetime."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT ci.id, ci.thought_leader_slug, ci.source_type, ci.title,
                   ci.published_date, ci.duration_seconds, ci.guests, ci.drive_url,
                   ci.tags,
                   ca.analysis_json, ca.one_sentence_summary, ca.analyzed_at
            FROM content_analysis ca
            JOIN content_items ci ON ci.id = ca.content_item_id
            WHERE ci.published_date >= ? OR ca.analyzed_at >= ?
            ORDER BY ci.published_date DESC
        """, (since.isoformat(), since.isoformat())).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["guests"] = json.loads(d.get("guests") or "[]")
            d["tags"] = json.loads(d.get("tags") or "[]")
            if d.get("published_date"):
                d["published_date"] = datetime.fromisoformat(d["published_date"])
            if d.get("analyzed_at"):
                d["analyzed_at"] = datetime.fromisoformat(d["analyzed_at"])
            result.append(d)
        return result
    finally:
        conn.close()


# ============================================
# Migration: episodes → content_items
# ============================================

def migrate_episodes_to_content_items() -> int:
    """Migrate existing episodes into content_items. Returns count migrated."""
    conn = get_connection()
    try:
        # Check if already migrated
        existing = conn.execute("SELECT COUNT(*) as cnt FROM content_items").fetchone()["cnt"]
        if existing > 0:
            logger.info(f"Content items already has {existing} rows, skipping migration")
            return 0

        # For each episode, find or create the matching source
        episodes = conn.execute("SELECT * FROM episodes").fetchall()
        migrated = 0

        for ep in episodes:
            slug = ep["podcast_slug"]
            # Find the source by matching thought_leader slug or rss_url
            source = conn.execute("""
                SELECT s.id, tl.slug as tl_slug, tl.tags as tl_tags
                FROM sources s
                JOIN thought_leaders tl ON s.thought_leader_id = tl.id
                WHERE s.type = 'podcast'
                AND (tl.slug = ? OR s.name = ?)
                LIMIT 1
            """, (slug, ep["podcast_name"])).fetchone()

            if not source:
                # Try by RSS URL from old podcasts.yaml
                continue

            conn.execute("""
                INSERT OR IGNORE INTO content_items
                (source_id, thought_leader_slug, source_type, title, published_date,
                 content_url, duration_seconds, description, guid, status,
                 detected_at, completed_at, error_message, transcript_local_path,
                 drive_file_id, drive_url, assemblyai_transcript_id,
                 guests, tags)
                VALUES (?, ?, 'podcast', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (source["id"], source["tl_slug"],
                  ep["title"], ep["published_date"],
                  ep["audio_url"], ep["duration_seconds"], ep["description"],
                  ep["rss_guid"], ep["status"],
                  ep["detected_at"], ep["completed_at"], ep["error_message"],
                  ep["transcript_local_path"],
                  ep["drive_file_id"], ep["drive_url"],
                  ep["assemblyai_transcript_id"],
                  ep["guests"], source["tl_tags"]))
            migrated += 1

        # Migrate analyses
        for ea in conn.execute("SELECT * FROM episode_analysis").fetchall():
            # Find the content item by matching the legacy episode
            ep_id = ea["episode_id"]
            ci = conn.execute("""
                SELECT ci.id FROM content_items ci
                JOIN episodes e ON ci.guid = e.rss_guid
                WHERE e.id = ?
                LIMIT 1
            """, (int(ep_id) if ep_id.isdigit() else 0,)).fetchone()

            if ci:
                conn.execute("""
                    INSERT OR IGNORE INTO content_analysis
                    (content_item_id, analysis_json, one_sentence_summary, topic_tags,
                     companies_json, macro_calls_json, content_hooks_json,
                     marketing_tactics_json, people_json, contrarian_takes_json,
                     why_it_matters, source_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'podcast')
                """, (ci["id"], ea["analysis_json"], ea["one_sentence_summary"],
                      ea["topic_tags"], ea["companies_json"], ea["macro_calls_json"],
                      ea["content_hooks_json"], ea["marketing_tactics_json"],
                      ea["people_json"], ea["contrarian_takes_json"],
                      ea["why_it_matters_mark"] or ea["why_it_matters_brooke"]))

        conn.commit()
        logger.info(f"Migrated {migrated} episodes to content_items")
        return migrated
    finally:
        conn.close()


# ============================================
# Legacy Episode functions (kept for backward compat)
# ============================================

def _row_to_episode(row: sqlite3.Row) -> Episode:
    d = dict(row)
    d["guests"] = json.loads(d.get("guests") or "[]")
    d["key_quotes"] = json.loads(d["key_quotes"]) if d.get("key_quotes") else None
    d["themes"] = json.loads(d["themes"]) if d.get("themes") else None
    if d.get("published_date"):
        d["published_date"] = datetime.fromisoformat(d["published_date"])
    if d.get("detected_at"):
        d["detected_at"] = datetime.fromisoformat(d["detected_at"])
    if d.get("completed_at"):
        d["completed_at"] = datetime.fromisoformat(d["completed_at"])
    return Episode(**d)


def _episode_to_params(ep: Episode) -> dict:
    return {
        "podcast_slug": ep.podcast_slug,
        "podcast_name": ep.podcast_name,
        "title": ep.title,
        "published_date": ep.published_date.isoformat() if ep.published_date else None,
        "audio_url": ep.audio_url,
        "duration_seconds": ep.duration_seconds,
        "description": ep.description,
        "episode_number": ep.episode_number,
        "guests": json.dumps(ep.guests),
        "rss_guid": ep.rss_guid,
        "status": ep.status.value,
        "detected_at": ep.detected_at.isoformat(),
        "completed_at": ep.completed_at.isoformat() if ep.completed_at else None,
        "error_message": ep.error_message,
        "audio_local_path": ep.audio_local_path,
        "transcript_local_path": ep.transcript_local_path,
        "drive_file_id": ep.drive_file_id,
        "drive_url": ep.drive_url,
        "assemblyai_transcript_id": ep.assemblyai_transcript_id,
        "audience": ep.audience,
        "summary": ep.summary,
        "key_quotes": json.dumps(ep.key_quotes) if ep.key_quotes else None,
        "themes": json.dumps(ep.themes) if ep.themes else None,
        "content_brief": ep.content_brief,
    }


def insert_episode(ep: Episode) -> int:
    conn = get_connection()
    try:
        params = _episode_to_params(ep)
        cols = ", ".join(params.keys())
        placeholders = ", ".join(f":{k}" for k in params.keys())
        cursor = conn.execute(
            f"INSERT OR IGNORE INTO episodes ({cols}) VALUES ({placeholders})",
            params,
        )
        conn.commit()
        return cursor.lastrowid or 0
    finally:
        conn.close()


def update_episode(ep: Episode) -> None:
    if ep.id is None:
        raise ValueError("Cannot update episode without id")
    conn = get_connection()
    try:
        params = _episode_to_params(ep)
        params["id"] = ep.id
        set_clause = ", ".join(f"{k} = :{k}" for k in params if k != "id")
        conn.execute(f"UPDATE episodes SET {set_clause} WHERE id = :id", params)
        conn.commit()
    finally:
        conn.close()


def get_episode_by_id(episode_id: int) -> Episode | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        return _row_to_episode(row) if row else None
    finally:
        conn.close()


def episode_exists(podcast_slug: str, rss_guid: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM episodes WHERE podcast_slug = ? AND rss_guid = ?",
            (podcast_slug, rss_guid),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_episodes_by_status(status: EpisodeStatus, limit: int = 100) -> list[Episode]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM episodes WHERE status = ? ORDER BY detected_at DESC LIMIT ?",
            (status.value, limit),
        ).fetchall()
        return [_row_to_episode(r) for r in rows]
    finally:
        conn.close()


def get_recent_episodes(limit: int = 50, podcast_slug: str | None = None) -> list[Episode]:
    conn = get_connection()
    try:
        if podcast_slug:
            rows = conn.execute(
                "SELECT * FROM episodes WHERE podcast_slug = ? ORDER BY detected_at DESC LIMIT ?",
                (podcast_slug, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM episodes ORDER BY detected_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_episode(r) for r in rows]
    finally:
        conn.close()


def get_failed_episodes() -> list[Episode]:
    return get_episodes_by_status(EpisodeStatus.error)


def reset_episode_for_retry(episode_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE episodes SET status = 'detected', error_message = NULL WHERE id = ?",
            (episode_id,),
        )
        conn.commit()
    finally:
        conn.close()


# Legacy analysis functions

def save_analysis(episode_id: str, analysis_json: str, summary: str, topic_tags: str,
                  companies_json: str, macro_calls_json: str, content_hooks_json: str,
                  marketing_tactics_json: str, people_json: str, contrarian_takes_json: str,
                  why_mark: str | None, why_brooke: str | None) -> None:
    conn = get_connection()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO episode_analysis
            (episode_id, analysis_json, one_sentence_summary, topic_tags,
             companies_json, macro_calls_json, content_hooks_json,
             marketing_tactics_json, people_json, contrarian_takes_json,
             why_it_matters_mark, why_it_matters_brooke, analyzed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (episode_id, analysis_json, summary, topic_tags,
              companies_json, macro_calls_json, content_hooks_json,
              marketing_tactics_json, people_json, contrarian_takes_json,
              why_mark, why_brooke))
        conn.commit()
    finally:
        conn.close()


def get_analysis(episode_id: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM episode_analysis WHERE episode_id = ?", (episode_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_unanalyzed_episodes() -> list[Episode]:
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT e.* FROM episodes e
            LEFT JOIN episode_analysis ea ON CAST(e.id AS TEXT) = ea.episode_id
            WHERE e.status = 'complete'
            AND e.transcript_local_path IS NOT NULL
            AND ea.episode_id IS NULL
            ORDER BY e.published_date DESC
        """).fetchall()
        return [_row_to_episode(r) for r in rows]
    finally:
        conn.close()


def get_analyzed_episodes_since(since: datetime) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT e.id, e.podcast_slug, e.podcast_name, e.title, e.published_date,
                   e.duration_seconds, e.guests, e.drive_url, e.audience,
                   ea.analysis_json, ea.one_sentence_summary, ea.analyzed_at
            FROM episode_analysis ea
            JOIN episodes e ON CAST(e.id AS TEXT) = ea.episode_id
            WHERE e.published_date >= ? OR ea.analyzed_at >= ?
            ORDER BY e.published_date DESC
        """, (since.isoformat(), since.isoformat())).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["guests"] = json.loads(d.get("guests") or "[]")
            if d.get("published_date"):
                d["published_date"] = datetime.fromisoformat(d["published_date"])
            if d.get("analyzed_at"):
                d["analyzed_at"] = datetime.fromisoformat(d["analyzed_at"])
            result.append(d)
        return result
    finally:
        conn.close()


def record_brief_sent(brief_type: str, episode_ids: list[str], recipient: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO briefs_sent (brief_type, episodes_covered, recipient) VALUES (?, ?, ?)",
            (brief_type, json.dumps(episode_ids), recipient),
        )
        conn.commit()
    finally:
        conn.close()
