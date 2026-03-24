"""Utility functions."""

from __future__ import annotations

import logging
import re
import sys


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def parse_guests_from_title(title: str, hosts: list[str]) -> list[str]:
    """Heuristic guest extraction from episode title.

    Common patterns:
      - "Guest Name - Topic"
      - "Guest Name: Topic"
      - "EP123: Guest Name - Topic"
      - "Guest Name | Topic"
      - "#123 - Guest Name - Topic"
    """
    # Strip common prefixes like "EP123:", "#123 -", "Ep. 123:"
    cleaned = re.sub(r"^(EP\.?\s*\d+\s*[:|-]\s*|#\d+\s*[-|:]\s*)", "", title, flags=re.IGNORECASE)

    # Split on common delimiters
    for delim in [" - ", " | ", ": "]:
        if delim in cleaned:
            candidate = cleaned.split(delim)[0].strip()
            # Check it's not a host name and looks like a person name
            if candidate and candidate not in hosts and _looks_like_name(candidate):
                return [candidate]

    return []


def _looks_like_name(text: str) -> bool:
    """Basic check: 2-5 words, no overly long words, starts with uppercase."""
    words = text.split()
    if len(words) < 2 or len(words) > 6:
        return False
    if not text[0].isupper():
        return False
    # Reject if it contains common non-name words
    lower = text.lower()
    non_name = {"the", "how", "why", "what", "when", "where", "is", "are", "was", "best", "top", "new"}
    if words[0].lower() in non_name:
        return False
    return all(len(w) < 25 for w in words)


def sanitize_filename(name: str) -> str:
    """Create a filesystem-safe filename."""
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "?"
    minutes = seconds // 60
    if minutes >= 60:
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}m"
    return f"{minutes}m"
