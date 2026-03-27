"""Claude API analysis of transcripts."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import anthropic

from podflow.analysis.models import EpisodeAnalysis
from podflow.analysis.prompts import (
    BROOKE_ANALYSIS_PROMPT,
    MARK_ANALYSIS_PROMPT,
    WEEKLY_BROOKE_PROMPT,
    WEEKLY_MARK_PROMPT,
)
from podflow.config import load_podcasts, load_settings
from podflow.db import get_analysis, get_unanalyzed_episodes, save_analysis

logger = logging.getLogger(__name__)


def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Add it to .env or environment.")
    return anthropic.Anthropic(api_key=api_key)


def _get_audience_for_podcast(podcast_slug: str) -> str:
    """Look up the audience tag for a podcast from config."""
    podcasts = load_podcasts()
    for p in podcasts:
        if p.slug == podcast_slug:
            return p.audience
    return "mark"


def _truncate_transcript(text: str, max_tokens: int) -> str:
    """Truncate transcript intelligently if it exceeds token limit.
    Rough estimate: 1 token ~= 4 characters.
    """
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text

    # Keep first 2000 words, last 2000 words, sample from middle
    words = text.split()
    if len(words) <= 4000:
        return text

    head = " ".join(words[:2000])
    tail = " ".join(words[-2000:])
    middle_words = words[2000:-2000]

    # Sample evenly from middle to fit budget
    remaining_chars = max_chars - len(head) - len(tail) - 200  # padding
    if remaining_chars > 0 and middle_words:
        middle_text = " ".join(middle_words)
        if len(middle_text) > remaining_chars:
            # Take evenly spaced samples
            step = max(1, len(middle_words) // (remaining_chars // 6))
            sampled = middle_words[::step]
            middle_text = " ".join(sampled)[:remaining_chars]
        return f"{head}\n\n[... transcript truncated for length ...]\n\n{middle_text}\n\n[... continued ...]\n\n{tail}"

    return f"{head}\n\n[... transcript truncated for length ...]\n\n{tail}"


def _call_claude(prompt: str, model: str) -> str:
    """Call Claude API and return the text response."""
    client = _get_client()
    message = client.messages.create(
        model=model,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _parse_analysis_json(raw: str) -> dict:
    """Extract JSON from Claude's response, handling markdown code blocks and preamble."""
    text = raw.strip()
    # Remove markdown code fences
    if "```" in text:
        import re
        match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    # Find the JSON object boundaries
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]
    return json.loads(text)


JUNK_TITLE_PATTERNS = [
    r"(?i)\bbest of\b",
    r"(?i)\breplay\b",
    r"(?i)\bre-?run\b",
    r"(?i)\bclassic episode\b",
    r"(?i)\btrailer\b",
    r"(?i)\bintroducing\b",
    r"(?i)\bbonuspreview\b",
]

MIN_TRANSCRIPT_CHARS = 3000  # Skip transcripts under ~500 words


def _is_junk_episode(title: str, transcript_text: str) -> bool:
    """Filter out reruns, trailers, and short filler episodes."""
    import re
    for pattern in JUNK_TITLE_PATTERNS:
        if re.search(pattern, title):
            return True
    if len(transcript_text) < MIN_TRANSCRIPT_CHARS:
        return True
    return False


def analyze_episode(episode_id: int, podcast_slug: str, podcast_name: str,
                    episode_title: str, transcript_path: str,
                    reanalyze: bool = False) -> EpisodeAnalysis | None:
    """Analyze a single episode transcript with Claude."""
    settings = load_settings()
    model = settings.analysis.model
    max_tokens = settings.analysis.max_transcript_tokens

    ep_id_str = str(episode_id)

    # Check if already analyzed
    if not reanalyze and get_analysis(ep_id_str):
        logger.info(f"Episode {episode_id} already analyzed, skipping")
        return None

    # Read transcript
    path = Path(transcript_path)
    if not path.exists():
        logger.error(f"Transcript not found: {transcript_path}")
        return None

    transcript = path.read_text(encoding="utf-8")

    # Skip junk episodes
    if _is_junk_episode(episode_title, transcript):
        logger.info(f"Skipping junk episode: {episode_title}")
        return None

    transcript = _truncate_transcript(transcript, max_tokens)

    audience = _get_audience_for_podcast(podcast_slug)

    # Pick the right prompt — single call for all audience types
    from podflow.analysis.prompts import COMBINED_ANALYSIS_PROMPT

    if audience == "both":
        prompt_template = COMBINED_ANALYSIS_PROMPT
        label = "Combined"
    elif audience == "brooke":
        prompt_template = BROOKE_ANALYSIS_PROMPT
        label = "Brooke"
    else:
        prompt_template = MARK_ANALYSIS_PROMPT
        label = "Mark"

    prompt = prompt_template.format(
        podcast_name=podcast_name,
        episode_title=episode_title,
        episode_id=ep_id_str,
        audience=audience,
        transcript=transcript,
    )
    logger.info(f"Running {label} analysis for: {episode_title}")
    raw = _call_claude(prompt, model)
    merged = _parse_analysis_json(raw)

    # Ensure required fields
    merged["episode_id"] = ep_id_str
    merged["podcast_name"] = podcast_name
    merged["episode_title"] = episode_title
    merged["audience"] = audience

    analysis = EpisodeAnalysis(**merged)

    # Store in DB
    save_analysis(
        episode_id=ep_id_str,
        analysis_json=json.dumps(merged),
        summary=analysis.one_sentence_summary,
        topic_tags=json.dumps(analysis.topic_tags),
        companies_json=json.dumps([c.model_dump() for c in analysis.companies]),
        macro_calls_json=json.dumps([m.model_dump() for m in analysis.macro_calls]),
        content_hooks_json=json.dumps([h.model_dump() for h in analysis.content_hooks]),
        marketing_tactics_json=json.dumps([t.model_dump() for t in analysis.marketing_tactics]),
        people_json=json.dumps([p.model_dump() for p in analysis.people_mentioned]),
        contrarian_takes_json=json.dumps(analysis.contrarian_takes),
        why_mark=analysis.why_it_matters_mark,
        why_brooke=analysis.why_it_matters_brooke,
    )

    return analysis


def _dedupe_by_name(items: list[dict]) -> list[dict]:
    """Deduplicate a list of dicts by 'name' key."""
    seen = set()
    result = []
    for item in items:
        name = item.get("name", "").lower()
        if name not in seen:
            seen.add(name)
            result.append(item)
    return result


def analyze_all(reanalyze: bool = False) -> list[EpisodeAnalysis]:
    """Analyze all unanalyzed episodes."""
    if reanalyze:
        from podflow.db import get_episodes_by_status
        from podflow.models import EpisodeStatus
        episodes = get_episodes_by_status(EpisodeStatus.complete)
        episodes = [e for e in episodes if e.transcript_local_path]
    else:
        episodes = get_unanalyzed_episodes()

    results = []
    for ep in episodes:
        try:
            analysis = analyze_episode(
                episode_id=ep.id,
                podcast_slug=ep.podcast_slug,
                podcast_name=ep.podcast_name,
                episode_title=ep.title,
                transcript_path=ep.transcript_local_path,
                reanalyze=reanalyze,
            )
            if analysis:
                results.append(analysis)
        except Exception as e:
            logger.error(f"Failed to analyze {ep.title}: {e}")

    return results


def generate_weekly_synthesis(analyses_json: str, audience: str) -> dict:
    """Generate weekly synthesis from a collection of episode analyses."""
    settings = load_settings()
    model = settings.analysis.model

    if audience == "mark":
        prompt = WEEKLY_MARK_PROMPT.format(analyses_json=analyses_json)
    else:
        prompt = WEEKLY_BROOKE_PROMPT.format(analyses_json=analyses_json)

    raw = _call_claude(prompt, model)
    return _parse_analysis_json(raw)
