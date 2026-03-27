"""Persistent Idea Bank backed by Google Sheets.

One spreadsheet with two sheets (Mark / Brooke). Each analysis run
appends new ideas and bumps the score of ideas that get reinforced
by additional episodes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from googleapiclient.discovery import build

from podflow.config import load_settings
from podflow.drive import get_credentials, find_or_create_folder, get_drive_service

logger = logging.getLogger(__name__)

SHEET_HEADERS = [
    "ID",
    "Idea",
    "Detail",
    "Category",
    "Audience",
    "Sources",
    "Score",
    "First Seen",
    "Last Reinforced",
    "Status",
]

IDEA_CATEGORIES = {
    "companies": "investment_signal",
    "macro_calls": "macro_call",
    "content_hooks": "content_hook",
    "marketing_tactics": "marketing_tactic",
    "contrarian_takes": "contrarian",
}


def _get_sheets_service():
    creds = get_credentials()
    return build("sheets", "v4", credentials=creds)


def _idea_hash(idea: str, category: str) -> str:
    """Stable hash for dedup. Two ideas are the same if their core text and category match."""
    normalized = idea.strip().lower()[:200]
    return hashlib.sha256(f"{category}:{normalized}".encode()).hexdigest()[:12]


def get_or_create_spreadsheet(settings=None) -> str:
    """Get or create the Idea Bank spreadsheet. Returns spreadsheet ID."""
    if settings is None:
        settings = load_settings()

    # Check if we already have the ID stored
    idea_bank_id = getattr(settings.storage, "idea_bank_spreadsheet_id", None)
    if idea_bank_id:
        return idea_bank_id

    # Create spreadsheet via Sheets API
    sheets = _get_sheets_service()
    body = {
        "properties": {"title": "Podflow Idea Bank"},
        "sheets": [
            {
                "properties": {
                    "title": "Mark",
                    "gridProperties": {"frozenRowCount": 1},
                }
            },
            {
                "properties": {
                    "title": "Brooke",
                    "gridProperties": {"frozenRowCount": 1},
                }
            },
        ],
    }
    spreadsheet = sheets.spreadsheets().create(body=body, fields="spreadsheetId").execute()
    ss_id = spreadsheet["spreadsheetId"]
    logger.info(f"Created Idea Bank spreadsheet: {ss_id}")

    # Write headers to both sheets
    for sheet_name in ["Mark", "Brooke"]:
        sheets.spreadsheets().values().update(
            spreadsheetId=ss_id,
            range=f"{sheet_name}!A1",
            valueInputOption="RAW",
            body={"values": [SHEET_HEADERS]},
        ).execute()

    # Format header row (bold, freeze)
    _format_headers(sheets, ss_id)

    # Move spreadsheet into the Podcast Transcripts folder
    drive_service = get_drive_service()
    root_id = settings.storage.root_folder_id
    if root_id:
        drive_service.files().update(
            fileId=ss_id,
            addParents=root_id,
            removeParents="root",
            fields="id, parents",
        ).execute()

    # Save the ID to settings
    _save_spreadsheet_id(ss_id)

    return ss_id


def _format_headers(sheets, ss_id: str) -> None:
    """Bold the header row and set column widths."""
    # Get actual sheet IDs
    meta = sheets.spreadsheets().get(spreadsheetId=ss_id, fields="sheets.properties").execute()
    sheet_ids = [s["properties"]["sheetId"] for s in meta.get("sheets", [])]

    requests = []
    for sheet_id in sheet_ids:
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                        "backgroundColor": {"red": 0.1, "green": 0.1, "blue": 0.1},
                    }
                },
                "fields": "userEnteredFormat(textFormat,backgroundColor)",
            }
        })
        col_widths = [100, 300, 400, 120, 80, 300, 60, 100, 100, 80]
        for i, width in enumerate(col_widths):
            requests.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            })

    sheets.spreadsheets().batchUpdate(
        spreadsheetId=ss_id,
        body={"requests": requests},
    ).execute()


def _save_spreadsheet_id(ss_id: str) -> None:
    """Save spreadsheet ID to settings.yaml."""
    settings = load_settings()
    # Add to storage settings — we'll store it in settings.yaml directly
    from podflow.config import CONFIG_DIR
    import yaml
    settings_path = CONFIG_DIR / "settings.yaml"
    with open(settings_path) as f:
        raw = yaml.safe_load(f)
    raw.setdefault("storage", {})["idea_bank_spreadsheet_id"] = ss_id
    with open(settings_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False)
    logger.info(f"Saved Idea Bank spreadsheet ID to settings.yaml")


def _read_existing_ideas(sheets, ss_id: str, sheet_name: str) -> dict[str, int]:
    """Read existing idea IDs and their row numbers. Returns {id: row_number}."""
    result = sheets.spreadsheets().values().get(
        spreadsheetId=ss_id,
        range=f"{sheet_name}!A:A",
    ).execute()
    values = result.get("values", [])
    existing = {}
    for i, row in enumerate(values):
        if i == 0:  # skip header
            continue
        if row:
            existing[row[0]] = i + 1  # 1-indexed for Sheets API
    return existing


def _read_full_sheet(sheets, ss_id: str, sheet_name: str) -> list[list[str]]:
    """Read all rows from a sheet."""
    result = sheets.spreadsheets().values().get(
        spreadsheetId=ss_id,
        range=f"{sheet_name}!A:J",
    ).execute()
    return result.get("values", [])


def extract_ideas_from_analysis(analysis_json: str, podcast_name: str,
                                 episode_title: str, drive_url: str,
                                 audience: str) -> list[dict]:
    """Extract discrete ideas from an episode analysis."""
    analysis = json.loads(analysis_json) if isinstance(analysis_json, str) else analysis_json
    ideas = []
    source = f"{podcast_name}: {episode_title}"
    source_link = f'=HYPERLINK("{drive_url}", "{source[:80]}")' if drive_url else source

    # Company mentions → investment signals
    for c in analysis.get("companies", []):
        if not c.get("thesis"):
            continue
        name = c.get("name", "")
        ticker_str = f" ({c['ticker']})" if c.get("ticker") else ""
        ideas.append({
            "idea": f"{name}{ticker_str} — {c.get('sentiment', 'neutral').upper()}",
            "detail": c.get("thesis", ""),
            "category": "investment_signal",
            "audience": "mark" if audience in ("mark", "both") else audience,
            "source": source_link,
        })

    # Macro calls
    for m in analysis.get("macro_calls", []):
        ideas.append({
            "idea": m.get("theme", ""),
            "detail": m.get("position", ""),
            "category": "macro_call",
            "audience": "mark" if audience in ("mark", "both") else audience,
            "source": source_link,
        })

    # Content hooks
    for h in analysis.get("content_hooks", []):
        target = "brooke" if h.get("content_pillar") in ("luxury_brand", "marketing_innovation", "creator_economy") else "both"
        if audience == "mark" and target == "brooke":
            target = "both"
        ideas.append({
            "idea": h.get("headline", ""),
            "detail": h.get("insight", ""),
            "category": "content_hook",
            "audience": target if audience == "both" else audience,
            "source": source_link,
        })

    # Marketing tactics
    for t in analysis.get("marketing_tactics", []):
        platform_str = f" [{t['platform']}]" if t.get("platform") else ""
        ideas.append({
            "idea": f"{t.get('tactic', '')}{platform_str}",
            "detail": t.get("applicable_to", ""),
            "category": "marketing_tactic",
            "audience": "brooke",
            "source": source_link,
        })

    # Contrarian takes
    for take in analysis.get("contrarian_takes", []):
        ideas.append({
            "idea": take[:120],
            "detail": take,
            "category": "contrarian",
            "audience": audience if audience != "both" else "mark",
            "source": source_link,
        })

    return ideas


def sync_ideas_to_sheet(ideas: list[dict], ss_id: str | None = None) -> dict[str, int]:
    """Sync extracted ideas to the Google Sheet. Returns {sheet_name: new_count}."""
    if ss_id is None:
        ss_id = get_or_create_spreadsheet()

    sheets = _get_sheets_service()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stats = {"Mark": 0, "Brooke": 0}

    # Partition ideas by target sheet
    mark_ideas = [i for i in ideas if i["audience"] in ("mark", "both")]
    brooke_ideas = [i for i in ideas if i["audience"] in ("brooke", "both")]

    for sheet_name, sheet_ideas in [("Mark", mark_ideas), ("Brooke", brooke_ideas)]:
        if not sheet_ideas:
            continue

        existing = _read_existing_ideas(sheets, ss_id, sheet_name)
        full_rows = _read_full_sheet(sheets, ss_id, sheet_name)

        new_rows = []
        updates = []

        for idea in sheet_ideas:
            idea_id = _idea_hash(idea["idea"], idea["category"])

            if idea_id in existing:
                # Reinforce: bump score and update last_reinforced, append source
                row_num = existing[idea_id]
                if row_num < len(full_rows):
                    row = full_rows[row_num - 1]  # 0-indexed in full_rows
                    # Pad row if it's too short
                    while len(row) < 10:
                        row.append("")
                    old_score = int(row[6]) if row[6].isdigit() else 1
                    old_sources = row[5]
                    new_source = idea["source"]
                    if new_source not in old_sources:
                        combined_sources = f"{old_sources}\n{new_source}" if old_sources else new_source
                    else:
                        combined_sources = old_sources
                    updates.append({
                        "range": f"{sheet_name}!F{row_num}:I{row_num}",
                        "values": [[combined_sources, old_score + 1, row[7], now]],
                    })
            else:
                new_rows.append([
                    idea_id,
                    idea["idea"],
                    idea["detail"],
                    idea["category"],
                    idea["audience"],
                    idea["source"],
                    1,         # initial score
                    now,       # first seen
                    now,       # last reinforced
                    "new",     # status
                ])
                existing[idea_id] = len(full_rows) + len(new_rows)  # prevent re-adding in same batch

        # Batch update reinforcements
        if updates:
            sheets.spreadsheets().values().batchUpdate(
                spreadsheetId=ss_id,
                body={"valueInputOption": "USER_ENTERED", "data": updates},
            ).execute()
            logger.info(f"Reinforced {len(updates)} existing ideas in {sheet_name}")

        # Append new rows
        if new_rows:
            sheets.spreadsheets().values().append(
                spreadsheetId=ss_id,
                range=f"{sheet_name}!A:J",
                valueInputOption="USER_ENTERED",
                body={"values": new_rows},
            ).execute()
            stats[sheet_name] = len(new_rows)
            logger.info(f"Added {len(new_rows)} new ideas to {sheet_name}")

    # Sort both sheets by score descending
    _sort_sheet_by_score(sheets, ss_id)

    return stats


def _sort_sheet_by_score(sheets, ss_id: str) -> None:
    """Sort both sheets by Score column (G, index 6) descending."""
    # Get sheet IDs
    meta = sheets.spreadsheets().get(spreadsheetId=ss_id, fields="sheets.properties").execute()
    for sheet in meta.get("sheets", []):
        sheet_id = sheet["properties"]["sheetId"]
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=ss_id,
            body={
                "requests": [{
                    "sortRange": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,  # skip header
                        },
                        "sortSpecs": [
                            {"dimensionIndex": 6, "sortOrder": "DESCENDING"},  # Score
                            {"dimensionIndex": 8, "sortOrder": "DESCENDING"},  # Last Reinforced
                        ],
                    }
                }]
            },
        ).execute()


def get_top_ideas(sheet_name: str, limit: int = 5, ss_id: str | None = None) -> list[dict]:
    """Get the top N ideas by score for use in briefs."""
    if ss_id is None:
        ss_id = get_or_create_spreadsheet()

    sheets = _get_sheets_service()
    rows = _read_full_sheet(sheets, ss_id, sheet_name)

    if len(rows) <= 1:
        return []

    ideas = []
    for row in rows[1:limit + 1]:  # already sorted by score desc
        while len(row) < 10:
            row.append("")
        ideas.append({
            "id": row[0],
            "idea": row[1],
            "detail": row[2],
            "category": row[3],
            "audience": row[4],
            "sources": row[5],
            "score": int(row[6]) if row[6].isdigit() else 1,
            "first_seen": row[7],
            "last_reinforced": row[8],
            "status": row[9],
        })

    return ideas


def sync_all_analyses(ss_id: str | None = None) -> dict[str, int]:
    """Extract ideas from all analyzed episodes and sync to the sheet."""
    from podflow.db import get_connection

    if ss_id is None:
        ss_id = get_or_create_spreadsheet()

    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT e.podcast_name, e.title, e.drive_url, e.audience,
                   ea.analysis_json
            FROM episode_analysis ea
            JOIN episodes e ON CAST(e.id AS TEXT) = ea.episode_id
        """).fetchall()
    finally:
        conn.close()

    all_ideas = []
    for row in rows:
        audience = row["audience"] or "mark"
        ideas = extract_ideas_from_analysis(
            analysis_json=row["analysis_json"],
            podcast_name=row["podcast_name"],
            episode_title=row["title"],
            drive_url=row["drive_url"] or "",
            audience=audience,
        )
        all_ideas.extend(ideas)

    logger.info(f"Extracted {len(all_ideas)} ideas from {len(rows)} episodes")
    return sync_ideas_to_sheet(all_ideas, ss_id)
