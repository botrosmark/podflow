"""Constructs email HTML from analysis data.

Uses diversity-aware selection to prevent any single podcast from
dominating the brief. Caps each section at 5-7 items.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from podflow.utils import format_duration

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Max items per section in briefs
MAX_PER_SECTION = 7
# Max items from any single podcast in one section
MAX_PER_PODCAST = 2


def _get_top_ideas_safe(sheet_name: str, limit: int) -> list[dict]:
    """Fetch top ideas from Idea Bank, failing silently if unavailable."""
    try:
        from podflow.idea_bank import get_top_ideas
        return get_top_ideas(sheet_name, limit)
    except Exception as e:
        logger.debug(f"Could not fetch top ideas for {sheet_name}: {e}")
        return []


def _get_env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


def _diverse_select(items: list[dict], key: str = "source_podcast",
                    limit: int = MAX_PER_SECTION,
                    per_source: int = MAX_PER_PODCAST) -> list[dict]:
    """Select items with diversity — no single source dominates.

    Round-robin: pick the best item from each source first,
    then come back for seconds, up to per_source cap.
    """
    if not items:
        return []

    # Group by source
    by_source: dict[str, list[dict]] = {}
    for item in items:
        src = item.get(key, "unknown")
        by_source.setdefault(src, []).append(item)

    # Round-robin selection
    selected = []
    for round_num in range(per_source):
        for src, src_items in by_source.items():
            if round_num < len(src_items) and len(selected) < limit:
                selected.append(src_items[round_num])

    return selected[:limit]


def _score_tactic(t: dict) -> int:
    """Score a tactic by specificity — items with numbers/platforms rank higher."""
    score = 0
    if t.get("result_cited"):
        score += 3
    if t.get("platform"):
        score += 2
    if t.get("source_url"):
        score += 1
    return score


def _score_company(c: dict) -> int:
    """Score a company mention — tickers and strong sentiment rank higher."""
    score = 0
    if c.get("ticker"):
        score += 2
    if c.get("sentiment") in ("bullish", "bearish"):
        score += 1
    if len(c.get("thesis", "")) > 50:
        score += 1
    return score


def build_mark_daily(analyzed_episodes: list[dict]) -> str:
    """Build Mark's daily brief HTML from analyzed episode data."""
    env = _get_env()
    template = env.get_template("daily_brief.html")

    companies = []
    macro_calls = []
    contrarian_takes = []
    content_hooks = []
    entity_counter: Counter = Counter()
    entity_data: dict[str, dict] = {}
    episodes_index = []

    for ep in analyzed_episodes:
        analysis = json.loads(ep.get("analysis_json", "{}"))
        audience = ep.get("audience", analysis.get("audience", "mark"))
        if audience not in ("mark", "both"):
            continue

        podcast_name = ep.get("podcast_name", "")
        episode_title = ep.get("episode_title", analysis.get("episode_title", ep.get("title", "")))
        drive_url = ep.get("drive_url", "")

        for c in analysis.get("companies", []):
            companies.append({
                "name": c.get("name", ""),
                "ticker": c.get("ticker"),
                "sentiment": c.get("sentiment", "neutral"),
                "thesis": c.get("thesis", ""),
                "source_podcast": podcast_name,
                "source_episode": episode_title,
                "source_url": drive_url,
            })
            ename = c.get("name", "").lower()
            entity_counter[ename] += 1
            entity_data[ename] = {
                "name": c.get("name", ""),
                "type": "Company",
                "sentiment": c.get("sentiment", "neutral"),
                "context": c.get("thesis", "")[:80],
            }

        for m in analysis.get("macro_calls", []):
            macro_calls.append({
                "theme": m.get("theme", ""),
                "position": m.get("position", ""),
                "speaker": m.get("speaker", ""),
                "source_podcast": podcast_name,
                "source_url": drive_url,
            })

        for take in analysis.get("contrarian_takes", []):
            contrarian_takes.append({
                "take": take,
                "source": podcast_name,
                "source_podcast": podcast_name,
            })

        for hook in analysis.get("content_hooks", [])[:2]:
            content_hooks.append({
                "headline": hook.get("headline", ""),
                "insight": hook.get("insight", ""),
                "source": podcast_name,
                "source_podcast": podcast_name,
            })

        for p in analysis.get("people_mentioned", []):
            pname = p.get("name", "").lower()
            entity_counter[pname] += 1
            entity_data[pname] = {
                "name": p.get("name", ""),
                "type": "Person",
                "sentiment": p.get("sentiment", "neutral"),
                "context": p.get("context", "")[:80],
            }

        pub_date = ep.get("published_date")
        date_str = pub_date.strftime("%Y-%m-%d") if isinstance(pub_date, datetime) else str(pub_date or "")
        episodes_index.append({
            "podcast_name": podcast_name,
            "title": episode_title,
            "drive_url": drive_url,
            "date": date_str,
            "duration": format_duration(ep.get("duration_seconds")),
            "guests": ", ".join(ep.get("guests", [])),
            "tags": ", ".join(analysis.get("topic_tags", [])),
            "summary": analysis.get("one_sentence_summary", ""),
        })

    # Rank then diversity-select
    companies.sort(key=_score_company, reverse=True)
    entity_table = []
    for name, count in entity_counter.most_common(15):
        data = entity_data.get(name, {})
        entity_table.append({
            "name": data.get("name", name),
            "type": data.get("type", ""),
            "mentions": count,
            "sentiment": data.get("sentiment", "neutral"),
            "context": data.get("context", ""),
        })

    top_ideas = _get_top_ideas_safe("Mark", 5)
    now = datetime.now(timezone.utc)
    count = len(episodes_index)

    return template.render(
        title=f"Podflow Brief — {now.strftime('%b %d, %Y')}",
        subtitle=f"{count} episode{'s' if count != 1 else ''} analyzed",
        brief_type="mark",
        companies=_diverse_select(companies, limit=7),
        macro_calls=_diverse_select(macro_calls, limit=5),
        contrarian_takes=_diverse_select(contrarian_takes, limit=5),
        content_hooks=_diverse_select(content_hooks, limit=5),
        entity_table=entity_table[:12],
        top_ideas=top_ideas,
        episodes=episodes_index,
        generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
    )


def build_brooke_daily(analyzed_episodes: list[dict]) -> str:
    """Build Brooke's daily brief HTML from analyzed episode data."""
    env = _get_env()
    template = env.get_template("daily_brief.html")

    tactics = []
    brand_insights = []
    content_hooks = []
    founder_gems = []
    episodes_index = []

    for ep in analyzed_episodes:
        analysis = json.loads(ep.get("analysis_json", "{}"))
        audience = ep.get("audience", analysis.get("audience", "brooke"))
        if audience not in ("brooke", "both"):
            continue

        podcast_name = ep.get("podcast_name", "")
        episode_title = ep.get("episode_title", analysis.get("episode_title", ep.get("title", "")))
        drive_url = ep.get("drive_url", "")

        for t in analysis.get("marketing_tactics", []):
            tactics.append({
                "tactic": t.get("tactic", ""),
                "platform": t.get("platform"),
                "result_cited": t.get("result_cited"),
                "applicable_to": t.get("applicable_to", ""),
                "source_podcast": podcast_name,
                "source_episode": episode_title,
                "source_url": drive_url,
            })

        for c in analysis.get("companies", []):
            brand_insights.append({
                "name": c.get("name", ""),
                "thesis": c.get("thesis", ""),
                "source": podcast_name,
                "source_podcast": podcast_name,
            })

        for hook in analysis.get("content_hooks", []):
            content_hooks.append({
                "headline": hook.get("headline", ""),
                "insight": hook.get("insight", ""),
                "content_pillar": hook.get("content_pillar", ""),
                "source": podcast_name,
                "source_podcast": podcast_name,
            })

        for take in analysis.get("contrarian_takes", []):
            founder_gems.append({
                "quote": take,
                "speaker": "Guest",
                "source": podcast_name,
                "source_podcast": podcast_name,
            })

        pub_date = ep.get("published_date")
        date_str = pub_date.strftime("%Y-%m-%d") if isinstance(pub_date, datetime) else str(pub_date or "")
        episodes_index.append({
            "podcast_name": podcast_name,
            "title": episode_title,
            "drive_url": drive_url,
            "date": date_str,
            "duration": format_duration(ep.get("duration_seconds")),
            "guests": ", ".join(ep.get("guests", [])),
            "tags": ", ".join(analysis.get("topic_tags", [])),
            "summary": analysis.get("one_sentence_summary", ""),
        })

    # Rank tactics by specificity, then diversity-select everything
    tactics.sort(key=_score_tactic, reverse=True)
    top_ideas = _get_top_ideas_safe("Brooke", 5)
    now = datetime.now(timezone.utc)
    count = len(episodes_index)

    return template.render(
        title=f"ATELIER Intel — {now.strftime('%b %d, %Y')}",
        subtitle=f"{count} episode{'s' if count != 1 else ''} analyzed",
        brief_type="brooke",
        tactics=_diverse_select(tactics, limit=7),
        brand_insights=_diverse_select(brand_insights, limit=6),
        content_hooks=_diverse_select(content_hooks, limit=7),
        founder_gems=_diverse_select(founder_gems, limit=5),
        top_ideas=top_ideas,
        episodes=episodes_index,
        generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
    )


def build_weekly_mark(synthesis: dict, episode_count: int) -> str:
    """Build Mark's weekly digest HTML."""
    env = _get_env()
    template = env.get_template("weekly_digest.html")
    now = datetime.now(timezone.utc)

    return template.render(
        title=f"Podflow Weekly — {now.strftime('%b %d, %Y')}",
        subtitle=f"Week in review — {episode_count} episodes",
        brief_type="mark",
        theme_convergence=synthesis.get("theme_convergence", []),
        company_heat_map=synthesis.get("company_heat_map", []),
        consensus_vs_contrarian=synthesis.get("consensus_vs_contrarian", []),
        biggest_macro_call=synthesis.get("biggest_macro_call"),
        one_thing=synthesis.get("one_thing"),
        generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
        episode_count=episode_count,
    )


def build_weekly_brooke(synthesis: dict, episode_count: int) -> str:
    """Build Brooke's weekly digest HTML."""
    env = _get_env()
    template = env.get_template("weekly_digest.html")
    now = datetime.now(timezone.utc)

    return template.render(
        title=f"ATELIER Weekly — {now.strftime('%b %d, %Y')}",
        subtitle=f"Week in review — {episode_count} episodes",
        brief_type="brooke",
        content_themes=synthesis.get("content_themes", []),
        carousel_series=synthesis.get("carousel_series", []),
        best_founder_story=synthesis.get("best_founder_story"),
        ai_tool_of_week=synthesis.get("ai_tool_of_week"),
        one_thing=synthesis.get("one_thing"),
        generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
        episode_count=episode_count,
    )
