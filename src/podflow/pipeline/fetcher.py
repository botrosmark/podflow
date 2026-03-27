"""Content fetcher for non-podcast sources (newsletters, X threads).

Newsletters: fetch article HTML from RSS content or web URL, convert to text.
X threads: extract tweet text from RSS entry content.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import feedparser
import requests

from podflow.config import get_data_dir

logger = logging.getLogger(__name__)


def _content_dir() -> Path:
    d = get_data_dir() / "content"
    d.mkdir(exist_ok=True)
    return d


def fetch_newsletter_text(entry: dict, source_name: str | None = None) -> str | None:
    """Extract article text from an RSS feed entry.

    Most Substack/newsletter feeds include full HTML content in the entry.
    Falls back to fetching the article URL.
    """
    # Try content from RSS entry first (most Substacks include full text)
    content = ""
    if entry.get("content"):
        for c in entry["content"]:
            if c.get("type", "").startswith("text/html"):
                content = c.get("value", "")
                break
            elif c.get("value"):
                content = c["value"]

    if not content and entry.get("summary"):
        content = entry["summary"]

    # If we got HTML content, convert to text
    if content and len(content) > 500:
        text = _html_to_text(content)
        if len(text) > 300:
            return text

    # Fall back to fetching the article URL
    link = entry.get("link")
    if link:
        try:
            resp = requests.get(link, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 Podflow/2.0"
            })
            if resp.status_code == 200 and len(resp.text) > 1000:
                return _html_to_text(resp.text)
        except Exception as e:
            logger.debug(f"Failed to fetch article {link}: {e}")

    return None


def fetch_x_thread_text(entry: dict) -> str | None:
    """Extract tweet/thread text from an rss.app RSS entry."""
    # rss.app puts tweet text in summary or content
    text = ""
    if entry.get("summary"):
        text = _html_to_text(entry["summary"])
    elif entry.get("content"):
        for c in entry["content"]:
            if c.get("value"):
                text = _html_to_text(c["value"])
                break

    if not text or len(text) < 50:
        return None

    return text


def save_content_text(thought_leader_slug: str, content_id: int,
                       text: str, source_type: str) -> str:
    """Save content text to local file. Returns the file path."""
    d = _content_dir() / source_type
    d.mkdir(exist_ok=True)
    path = d / f"{thought_leader_slug}_{content_id}.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _html_to_text(html: str) -> str:
    """Convert HTML to readable text."""
    text = re.sub(r'<(script|style|nav|footer|header)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<br\s*/?>|</p>|</div>|</li>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>', '- ', text, flags=re.IGNORECASE)
    text = re.sub(r'<h[1-6][^>]*>', '\n## ', text, flags=re.IGNORECASE)
    text = re.sub(r'</h[1-6]>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()
