"""Free transcript sources: YouTube captions and website scrapers.

Avoids AssemblyAI costs for podcasts that publish video on YouTube
or full transcripts on their websites.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

import requests

from podflow.config import get_data_dir

logger = logging.getLogger(__name__)

# YouTube channel handles for podcasts that publish full episodes
YOUTUBE_CHANNELS = {
    "diary-of-a-ceo": "@TheDiaryOfACEO",
    "hormozi-game": "@AlexHormozi",
    "all-in": "@alaboroflove",
    "my-first-million": "@MyFirstMillionPod",
    "colin-and-samir": "@ColinandSamir",
    "marketing-school": "@MarketingSchool",
    "skinny-confidential": "@TheSkinnyConfidential",
    "earned": "@CreatorIQ",
    "marketing-millennials": "@TheMarketingMillennials",
    "marketing-against-grain": "@HubSpot",
    "lennys-podcast": "@LennysPodcast",
}

# Podcasts with free website transcripts
WEBSITE_TRANSCRIPT_SOURCES = {
    "perpetual-traffic": "perpetualtraffic",
    "amy-porterfield": "amyporterfield",
    "marketing-ai": "marketingai",
    "marketing-against-grain": "matg_website",
    "how-i-built-this": "npr",
    "lennys-podcast": "lennys_website",
}


def _transcripts_dir() -> Path:
    d = get_data_dir() / "transcripts"
    d.mkdir(exist_ok=True)
    return d


def has_free_source(podcast_slug: str) -> bool:
    """Check if a podcast has a free transcript source available."""
    return podcast_slug in YOUTUBE_CHANNELS or podcast_slug in WEBSITE_TRANSCRIPT_SOURCES


def get_free_transcript(podcast_slug: str, episode_title: str,
                        episode_id: int) -> str | None:
    """Try to get a free transcript. Returns text or None."""
    # Try website scrapers first (higher quality)
    if podcast_slug in WEBSITE_TRANSCRIPT_SOURCES:
        text = _try_website_transcript(podcast_slug, episode_title)
        if text and len(text) > 500:
            path = _save_transcript(podcast_slug, episode_id, text)
            logger.info(f"Got website transcript for: {episode_title[:50]} ({len(text)} chars)")
            return path

    # Fall back to YouTube captions
    if podcast_slug in YOUTUBE_CHANNELS:
        text = _try_youtube_transcript(podcast_slug, episode_title)
        if text and len(text) > 500:
            path = _save_transcript(podcast_slug, episode_id, text)
            logger.info(f"Got YouTube transcript for: {episode_title[:50]} ({len(text)} chars)")
            return path

    return None


def _save_transcript(podcast_slug: str, episode_id: int, text: str) -> str:
    """Save transcript text to local file. Returns the file path."""
    path = _transcripts_dir() / f"{podcast_slug}_{episode_id}.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


# ============================================
# YouTube Captions
# ============================================

def _try_youtube_transcript(podcast_slug: str, episode_title: str) -> str | None:
    """Search YouTube for the episode and extract captions."""
    channel = YOUTUBE_CHANNELS.get(podcast_slug)
    if not channel:
        return None

    video_id = _find_youtube_video(channel, episode_title)
    if not video_id:
        return None

    return _extract_youtube_captions(video_id)


def _find_youtube_video(channel: str, episode_title: str) -> str | None:
    """Use yt-dlp to search for a YouTube video matching the episode title."""
    # Clean title for search
    clean_title = re.sub(r'[^\w\s]', '', episode_title)[:80]
    search_query = f"{channel} {clean_title}"

    try:
        result = subprocess.run(
            [
                "yt-dlp",
                f"ytsearch1:{search_query}",
                "--get-id",
                "--no-download",
                "--no-warnings",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        video_id = result.stdout.strip()
        if video_id and len(video_id) == 11:
            return video_id
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug(f"yt-dlp search failed: {e}")

    return None


def _extract_youtube_captions(video_id: str) -> str | None:
    """Extract captions from a YouTube video using youtube-transcript-api."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        ytt = YouTubeTranscriptApi()
        segments = ytt.fetch(video_id, languages=["en"])

        # Join segments into flowing text with paragraph breaks every ~5 sentences
        lines = []
        sentence_count = 0
        current_para = []
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            current_para.append(text)
            sentence_count += text.count('.') + text.count('?') + text.count('!')
            if sentence_count >= 5:
                lines.append(' '.join(current_para))
                current_para = []
                sentence_count = 0

        if current_para:
            lines.append(' '.join(current_para))

        return '\n\n'.join(lines)

    except Exception as e:
        logger.debug(f"YouTube caption extraction failed for {video_id}: {e}")
        return None


# ============================================
# Website Transcript Scrapers
# ============================================

def _try_website_transcript(podcast_slug: str, episode_title: str) -> str | None:
    """Try to scrape a transcript from the podcast's website."""
    source = WEBSITE_TRANSCRIPT_SOURCES.get(podcast_slug)
    if not source:
        return None

    try:
        if source == "npr":
            return _scrape_npr(episode_title)
        elif source == "perpetualtraffic":
            return _scrape_perpetual_traffic(episode_title)
        elif source == "amyporterfield":
            return _scrape_amy_porterfield(episode_title)
        elif source == "marketingai":
            return _scrape_marketing_ai(episode_title)
        elif source in ("matg_website", "lennys_website"):
            # These also have YouTube — let YouTube handle it
            return None
    except Exception as e:
        logger.debug(f"Website scrape failed for {podcast_slug}: {e}")

    return None


def _fetch_html(url: str) -> str | None:
    """Fetch a URL and return HTML text."""
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Podflow/1.0"
        })
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        logger.debug(f"HTTP fetch failed for {url}: {e}")
    return None


def _html_to_text(html: str) -> str:
    """Very basic HTML to text conversion."""
    # Remove script and style tags
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Convert <br> and <p> to newlines
    text = re.sub(r'<br\s*/?>|</p>', '\n', text, flags=re.IGNORECASE)
    # Remove all other tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode HTML entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    # Clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _scrape_npr(episode_title: str) -> str | None:
    """Scrape NPR transcript for How I Built This."""
    # Search NPR for the episode
    clean = re.sub(r'[^\w\s]', '', episode_title)[:60]
    search_url = f"https://www.npr.org/search?query=how+i+built+this+{clean.replace(' ', '+')}&page=1"
    html = _fetch_html(search_url)
    if not html:
        return None

    # Find transcript links
    matches = re.findall(r'href="(https://www\.npr\.org/\d+/\d+/\d+/[^"]+)"', html)
    if not matches:
        return None

    # Try the first match — get the transcript page
    article_url = matches[0]
    article_id = re.search(r'/(\d{8,})', article_url)
    if not article_id:
        return None

    transcript_url = f"https://www.npr.org/transcripts/{article_id.group(1)}"
    transcript_html = _fetch_html(transcript_url)
    if not transcript_html:
        return None

    return _html_to_text(transcript_html)


def _scrape_perpetual_traffic(episode_title: str) -> str | None:
    """Scrape Perpetual Traffic website for transcript."""
    # Their transcripts are embedded in episode pages with speaker labels
    clean = re.sub(r'[^\w\s]', '', episode_title)[:40].replace(' ', '+')
    search_url = f"https://perpetualtraffic.com/?s={clean}"
    html = _fetch_html(search_url)
    if not html:
        return None

    # Find episode page links
    matches = re.findall(r'href="(https://perpetualtraffic\.com/podcast/[^"]+)"', html)
    if not matches:
        return None

    page_html = _fetch_html(matches[0])
    if not page_html:
        return None

    # Extract transcript section (usually after "Transcript" heading)
    transcript_match = re.search(r'(?:transcript|read the transcript)[^<]*</[^>]+>(.*?)(?:<footer|<div class="post-nav|$)',
                                  page_html, re.DOTALL | re.IGNORECASE)
    if transcript_match:
        return _html_to_text(transcript_match.group(1))

    return None


def _scrape_amy_porterfield(episode_title: str) -> str | None:
    """Scrape Amy Porterfield transcript page."""
    # Try the transcript archive pattern
    # Episode numbers are in titles like "#699 - How to..."
    ep_match = re.search(r'#?(\d+)', episode_title)
    if ep_match:
        ep_num = ep_match.group(1)
        url = f"https://www.amyporterfield.com/transcript/{ep_num}transcript/"
        html = _fetch_html(url)
        if html and len(html) > 2000:
            return _html_to_text(html)
    return None


def _scrape_marketing_ai(episode_title: str) -> str | None:
    """Scrape Marketing AI Institute blog for transcript."""
    clean = re.sub(r'[^\w\s]', '', episode_title)[:40].replace(' ', '+')
    search_url = f"https://www.marketingaiinstitute.com/blog?search={clean}"
    html = _fetch_html(search_url)
    if not html:
        return None

    matches = re.findall(r'href="(https://www\.marketingaiinstitute\.com/blog/[^"]+)"', html)
    if not matches:
        return None

    page_html = _fetch_html(matches[0])
    if not page_html:
        return None

    # Extract the blog post body
    body_match = re.search(r'<div[^>]*class="[^"]*blog[^"]*body[^"]*"[^>]*>(.*?)</div>\s*</div>',
                           page_html, re.DOTALL | re.IGNORECASE)
    if body_match:
        return _html_to_text(body_match.group(1))

    return _html_to_text(page_html)
