"""Podflow Intelligence Dashboard — FastAPI + HTMX web app."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request, Response, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jose import jwt

from podflow.db import (
    get_analyzed_content_since,
    get_connection,
    get_content_item_by_id,
    get_content_analysis,
    get_recent_content_items,
    init_db,
    sync_thought_leaders_from_config,
)
from podflow.config import load_thought_leaders

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

JWT_SECRET = os.environ.get("PODFLOW_JWT_SECRET", "podflow-dev-secret-change-me")
JWT_ALGORITHM = "HS256"
ALLOWED_EMAILS = set()

app = FastAPI(title="Podflow Intelligence Dashboard")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.on_event("startup")
def startup():
    init_db()
    sync_thought_leaders_from_config()
    # Load allowed emails from settings
    from podflow.config import load_settings
    settings = load_settings()
    ALLOWED_EMAILS.update(settings.email.mark_recipients)
    ALLOWED_EMAILS.update(settings.email.brooke_recipients)


# ============================================
# Auth helpers
# ============================================

def _get_user(request: Request) -> str | None:
    """Get current user from JWT cookie. Returns user_id or None."""
    token = request.cookies.get("podflow_session")
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("user_id")
    except Exception:
        return None


def _require_user(request: Request) -> str:
    """Get current user or redirect to login."""
    user = _get_user(request)
    if not user:
        return None
    return user


def _get_persona(request: Request) -> str:
    """Get active persona from cookie."""
    return request.cookies.get("podflow_persona", "mark")


# ============================================
# Auth routes
# ============================================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, msg: str = ""):
    return templates.TemplateResponse(request, "login.html", {"msg": msg})


@app.post("/login")
async def login_submit(request: Request, email: str = Form(...)):
    email = email.strip().lower()
    if not ALLOWED_EMAILS or email in ALLOWED_EMAILS:
        # For simplicity, generate JWT directly (skip email for dev)
        # In production, send magic link via Resend
        user_id = "mark" if "mark" in email else "brooke"
        token = jwt.encode(
            {"user_id": user_id, "email": email, "exp": datetime.now(timezone.utc) + timedelta(days=30)},
            JWT_SECRET, algorithm=JWT_ALGORITHM,
        )
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("podflow_session", token, max_age=30*86400, httponly=True, samesite="lax")
        return response
    return RedirectResponse("/login?msg=Email+not+authorized", status_code=303)


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("podflow_session")
    return response


# ============================================
# Dashboard routes
# ============================================

@app.get("/", response_class=HTMLResponse)
async def today(request: Request):
    user = _require_user(request)
    if not user:
        return RedirectResponse("/login")

    persona = _get_persona(request)
    since = datetime.now(timezone.utc) - timedelta(hours=48)

    # Get recent analyzed content
    analyzed = get_analyzed_content_since(since)
    if not analyzed:
        # Fall back to wider window
        analyzed = get_analyzed_content_since(datetime.now(timezone.utc) - timedelta(days=14))

    # Parse analysis JSON into insight cards
    cards = _build_insight_cards(analyzed, persona)

    # Get top ideas from Idea Bank
    top_ideas = []
    try:
        from podflow.idea_bank import get_top_ideas
        sheet = "Mark" if persona == "mark" else "Brooke"
        top_ideas = get_top_ideas(sheet, 8)
    except Exception:
        pass

    # Get user actions for starred state
    conn = get_connection()
    starred = set()
    try:
        rows = conn.execute(
            "SELECT content_item_id FROM user_actions WHERE user_id = ? AND action_type = 'star'",
            (user,)
        ).fetchall()
        starred = {r["content_item_id"] for r in rows}
    except Exception:
        pass
    finally:
        conn.close()

    return templates.TemplateResponse(request, "today.html", {
        "user": user,
        "persona": persona,
        "cards": cards[:30],
        "top_ideas": top_ideas,
        "starred": starred,
        "total_items": len(analyzed),
    })


@app.get("/feed", response_class=HTMLResponse)
async def feed(request: Request, source_type: str = "", tag: str = "",
               timerange: str = "week", filter: str = "", sort: str = "newest"):
    user = _require_user(request)
    if not user:
        return RedirectResponse("/login")

    persona = _get_persona(request)

    # Build time window
    if timerange == "today":
        since = datetime.now(timezone.utc) - timedelta(hours=24)
    elif timerange == "week":
        since = datetime.now(timezone.utc) - timedelta(days=7)
    elif timerange == "month":
        since = datetime.now(timezone.utc) - timedelta(days=30)
    else:
        since = datetime.now(timezone.utc) - timedelta(days=365)

    analyzed = get_analyzed_content_since(since)
    cards = _build_insight_cards(analyzed, persona)

    # Apply filters
    if source_type:
        cards = [c for c in cards if c["source_type"] == source_type]
    if tag:
        cards = [c for c in cards if tag in c.get("tags", [])]
    if filter == "starred":
        conn = get_connection()
        starred_ids = {r["content_item_id"] for r in conn.execute(
            "SELECT content_item_id FROM user_actions WHERE user_id = ? AND action_type = 'star'", (user,)
        ).fetchall()}
        conn.close()
        cards = [c for c in cards if c["content_item_id"] in starred_ids]

    # Get starred state
    conn = get_connection()
    starred = set()
    try:
        rows = conn.execute(
            "SELECT content_item_id FROM user_actions WHERE user_id = ? AND action_type = 'star'", (user,)
        ).fetchall()
        starred = {r["content_item_id"] for r in rows}
    except Exception:
        pass
    finally:
        conn.close()

    # Get all unique tags for filter bar
    all_tags = set()
    for c in cards:
        all_tags.update(c.get("tags", []))

    return templates.TemplateResponse(request, "feed.html", {
        "user": user,
        "persona": persona,
        "cards": cards[:100],
        "starred": starred,
        "source_type": source_type,
        "tag": tag,
        "timerange": timerange,
        "current_filter": filter,
        "sort": sort,
        "all_tags": sorted(all_tags),
    })


@app.get("/item/{item_id}", response_class=HTMLResponse)
async def detail(request: Request, item_id: int):
    user = _require_user(request)
    if not user:
        return RedirectResponse("/login")

    persona = _get_persona(request)
    item = get_content_item_by_id(item_id)
    if not item:
        return HTMLResponse("Not found", status_code=404)

    analysis = get_content_analysis(item_id)
    analysis_data = json.loads(analysis["analysis_json"]) if analysis else {}

    # Check starred state
    conn = get_connection()
    is_starred = conn.execute(
        "SELECT 1 FROM user_actions WHERE user_id = ? AND content_item_id = ? AND action_type = 'star'",
        (user, item_id)
    ).fetchone() is not None
    rating = None
    r = conn.execute(
        "SELECT action_type FROM user_actions WHERE user_id = ? AND content_item_id = ? AND action_type IN ('rate_up', 'rate_down')",
        (user, item_id)
    ).fetchone()
    if r:
        rating = r["action_type"]
    conn.close()

    return templates.TemplateResponse(request, "detail.html", {
        "user": user,
        "persona": persona,
        "item": item,
        "analysis": analysis_data,
        "is_starred": is_starred,
        "rating": rating,
    })


@app.get("/leaders", response_class=HTMLResponse)
async def leaders_page(request: Request):
    user = _require_user(request)
    if not user:
        return RedirectResponse("/login")

    tls = load_thought_leaders()

    # Get content counts per leader
    conn = get_connection()
    counts = {}
    rows = conn.execute("""
        SELECT thought_leader_slug, COUNT(*) as cnt
        FROM content_items WHERE status = 'complete'
        GROUP BY thought_leader_slug
    """).fetchall()
    for r in rows:
        counts[r["thought_leader_slug"]] = r["cnt"]
    conn.close()

    return templates.TemplateResponse(request, "leaders.html", {
        "user": user,
        "leaders": tls,
        "counts": counts,
    })


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = ""):
    user = _require_user(request)
    if not user:
        return RedirectResponse("/login")

    results = []
    if q and len(q) >= 2:
        conn = get_connection()
        pattern = f"%{q}%"
        rows = conn.execute("""
            SELECT ci.id, ci.thought_leader_slug, ci.source_type, ci.title,
                   ci.published_date, ca.one_sentence_summary, ca.analysis_json
            FROM content_analysis ca
            JOIN content_items ci ON ci.id = ca.content_item_id
            WHERE ca.one_sentence_summary LIKE ?
               OR ca.companies_json LIKE ?
               OR ca.content_hooks_json LIKE ?
               OR ca.contrarian_takes_json LIKE ?
               OR ci.title LIKE ?
            ORDER BY ci.published_date DESC
            LIMIT 30
        """, (pattern, pattern, pattern, pattern, pattern)).fetchall()
        results = [dict(r) for r in rows]
        conn.close()

    return templates.TemplateResponse(request, "search.html", {
        "user": user,
        "q": q,
        "results": results,
    })


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    user = _require_user(request)
    if not user:
        return RedirectResponse("/login")

    tls = load_thought_leaders()

    # Pipeline status
    conn = get_connection()
    status_counts = {}
    for row in conn.execute("SELECT status, COUNT(*) as cnt FROM content_items GROUP BY status").fetchall():
        status_counts[row["status"]] = row["cnt"]

    total_analyses = conn.execute("SELECT COUNT(*) as cnt FROM content_analysis").fetchone()["cnt"]

    # User action stats
    action_counts = {}
    for row in conn.execute(
        "SELECT action_type, COUNT(*) as cnt FROM user_actions WHERE user_id = ? GROUP BY action_type",
        (user,)
    ).fetchall():
        action_counts[row["action_type"]] = row["cnt"]

    conn.close()

    return templates.TemplateResponse(request, "settings.html", {
        "user": user,
        "leaders": tls,
        "status_counts": status_counts,
        "total_analyses": total_analyses,
        "action_counts": action_counts,
    })


# ============================================
# Action endpoints (HTMX)
# ============================================

@app.post("/api/star/{item_id}", response_class=HTMLResponse)
async def toggle_star(request: Request, item_id: int):
    user = _require_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM user_actions WHERE user_id = ? AND content_item_id = ? AND action_type = 'star'",
        (user, item_id)
    ).fetchone()

    if existing:
        conn.execute("DELETE FROM user_actions WHERE id = ?", (existing["id"],))
        is_starred = False
    else:
        conn.execute(
            "INSERT OR IGNORE INTO user_actions (user_id, content_item_id, action_type) VALUES (?, ?, 'star')",
            (user, item_id)
        )
        is_starred = True
    conn.commit()
    conn.close()

    icon = "★" if is_starred else "☆"
    cls = "text-yellow-400" if is_starred else "text-gray-400 hover:text-yellow-400"
    return HTMLResponse(
        f'<button hx-post="/api/star/{item_id}" hx-swap="outerHTML" '
        f'class="action-btn {cls}" title="Star">{icon}</button>'
    )


@app.post("/api/rate/{item_id}", response_class=HTMLResponse)
async def rate(request: Request, item_id: int, rating: str = Form(...)):
    user = _require_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    action = f"rate_{rating}"
    conn = get_connection()
    # Remove existing rating
    conn.execute(
        "DELETE FROM user_actions WHERE user_id = ? AND content_item_id = ? AND action_type IN ('rate_up', 'rate_down')",
        (user, item_id)
    )
    conn.execute(
        "INSERT INTO user_actions (user_id, content_item_id, action_type) VALUES (?, ?, ?)",
        (user, item_id, action)
    )
    conn.commit()
    conn.close()

    up_cls = "text-green-500" if rating == "up" else "text-gray-400 hover:text-green-500"
    down_cls = "text-red-500" if rating == "down" else "text-gray-400 hover:text-red-500"
    return HTMLResponse(f'''
        <span class="flex gap-1" id="rate-{item_id}">
            <button hx-post="/api/rate/{item_id}" hx-vals='{{"rating":"up"}}' hx-target="#rate-{item_id}" hx-swap="outerHTML" class="action-btn {up_cls}" title="Useful">👍</button>
            <button hx-post="/api/rate/{item_id}" hx-vals='{{"rating":"down"}}' hx-target="#rate-{item_id}" hx-swap="outerHTML" class="action-btn {down_cls}" title="Not useful">👎</button>
        </span>
    ''')


@app.post("/api/archive/{item_id}", response_class=HTMLResponse)
async def archive(request: Request, item_id: int):
    user = _require_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO user_actions (user_id, content_item_id, action_type) VALUES (?, ?, 'archive')",
        (user, item_id)
    )
    conn.commit()
    conn.close()
    return HTMLResponse("")  # Card disappears


@app.post("/api/persona", response_class=HTMLResponse)
async def switch_persona(request: Request, persona: str = Form(...)):
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("podflow_persona", persona, max_age=365*86400, samesite="lax")
    return response


# ============================================
# Helpers
# ============================================

def _build_insight_cards(analyzed: list[dict], persona: str) -> list[dict]:
    """Convert analyzed content into flat insight cards for rendering."""
    cards = []
    for item in analyzed:
        analysis = json.loads(item.get("analysis_json", "{}"))
        base = {
            "content_item_id": item.get("id"),
            "thought_leader": item.get("thought_leader_slug", ""),
            "source_type": item.get("source_type", "podcast"),
            "title": item.get("title", ""),
            "published_date": item.get("published_date"),
            "drive_url": item.get("drive_url", ""),
            "tags": item.get("tags", []),
            "summary": analysis.get("one_sentence_summary", ""),
        }

        # Companies
        for c in analysis.get("companies", []):
            cards.append({
                **base,
                "insight_type": "company",
                "headline": f"{c.get('name', '')} ({c.get('ticker', '—')}) — {c.get('sentiment', 'neutral').upper()}",
                "body": c.get("thesis", ""),
                "location": c.get("approximate_location", ""),
            })

        # Macro calls
        for m in analysis.get("macro_calls", []):
            cards.append({
                **base,
                "insight_type": "macro",
                "headline": m.get("theme", ""),
                "body": m.get("position", ""),
                "location": m.get("approximate_location", ""),
            })

        # Content hooks
        for h in analysis.get("content_hooks", []):
            cards.append({
                **base,
                "insight_type": "hook",
                "headline": h.get("headline", ""),
                "body": h.get("insight", ""),
                "pillar": h.get("content_pillar", ""),
            })

        # Marketing tactics
        for t in analysis.get("marketing_tactics", []):
            platform = f" [{t.get('platform')}]" if t.get("platform") else ""
            cards.append({
                **base,
                "insight_type": "tactic",
                "headline": f"{t.get('tactic', '')}{platform}",
                "body": t.get("applicable_to", ""),
                "result": t.get("result_cited", ""),
            })

        # Contrarian takes
        for take in analysis.get("contrarian_takes", []):
            cards.append({
                **base,
                "insight_type": "contrarian",
                "headline": take[:100],
                "body": take,
            })

    # Sort by persona preference
    type_order = {
        "mark": {"company": 0, "macro": 1, "contrarian": 2, "hook": 3, "tactic": 4},
        "brooke": {"tactic": 0, "hook": 1, "company": 2, "contrarian": 3, "macro": 4},
    }
    order = type_order.get(persona, type_order["mark"])
    cards.sort(key=lambda c: (order.get(c.get("insight_type", ""), 5), str(c.get("published_date", ""))))
    cards.reverse()  # newest first within each group

    return cards
