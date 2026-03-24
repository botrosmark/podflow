"""SQLite state management."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from podflow.config import get_data_dir
from podflow.models import Episode, EpisodeStatus

SCHEMA_VERSION = 1


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
                summary TEXT,
                key_quotes TEXT,
                themes TEXT,
                content_brief TEXT,
                UNIQUE(podcast_slug, rss_guid)
            );

            CREATE INDEX IF NOT EXISTS idx_episodes_status ON episodes(status);
            CREATE INDEX IF NOT EXISTS idx_episodes_slug ON episodes(podcast_slug);
            CREATE INDEX IF NOT EXISTS idx_episodes_published ON episodes(published_date);
        """)
        # Set schema version if not present
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
    finally:
        conn.close()


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


def get_recent_episodes(
    limit: int = 50,
    podcast_slug: str | None = None,
) -> list[Episode]:
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
