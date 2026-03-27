"""Config loading and validation."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from podflow.models import PodcastConfig, Settings, ThoughtLeaderConfig, SourceConfig

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = _PROJECT_ROOT / "config"
DATA_DIR = _PROJECT_ROOT / "data"


def get_config_dir() -> Path:
    return CONFIG_DIR


def get_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def load_settings() -> Settings:
    path = CONFIG_DIR / "settings.yaml"
    if not path.exists():
        return Settings()
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return Settings(**raw)


def save_settings(settings: Settings) -> None:
    path = CONFIG_DIR / "settings.yaml"
    with open(path, "w") as f:
        yaml.dump(settings.model_dump(), f, default_flow_style=False, sort_keys=False)


# ============================================
# Thought Leader config (new)
# ============================================

def load_thought_leaders() -> list[ThoughtLeaderConfig]:
    """Load thought leaders from config/thought_leaders.yaml."""
    path = CONFIG_DIR / "thought_leaders.yaml"
    if not path.exists():
        return []
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    leaders = []
    for tl in raw.get("thought_leaders", []):
        sources_raw = tl.pop("sources", [])
        sources = [SourceConfig(**s) for s in sources_raw]
        leaders.append(ThoughtLeaderConfig(**tl, sources=sources))
    return leaders


def get_thought_leader_by_slug(slug: str) -> ThoughtLeaderConfig | None:
    for tl in load_thought_leaders():
        if tl.slug == slug:
            return tl
    return None


def save_thought_leaders(leaders: list[ThoughtLeaderConfig]) -> None:
    """Write thought leaders back to YAML."""
    path = CONFIG_DIR / "thought_leaders.yaml"
    data = {"thought_leaders": []}
    for tl in leaders:
        d = tl.model_dump()
        # Convert SourceType enums to strings for YAML
        for s in d.get("sources", []):
            if hasattr(s.get("type"), "value"):
                s["type"] = s["type"].value
        data["thought_leaders"].append(d)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


# ============================================
# Legacy podcast config (backward compat)
# ============================================

def load_podcasts() -> list[PodcastConfig]:
    """Load podcasts. Tries thought_leaders.yaml first, falls back to podcasts.yaml."""
    # Try new format first
    leaders = load_thought_leaders()
    if leaders:
        podcasts = []
        for tl in leaders:
            for src in tl.sources:
                if src.type == "podcast" and src.enabled:
                    podcasts.append(PodcastConfig(
                        name=src.name or tl.name,
                        slug=tl.slug if len([s for s in tl.sources if s.type == "podcast"]) == 1 else f"{tl.slug}-podcast",
                        rss_url=src.rss_url or "",
                        category=src.category or (tl.tags[0] if tl.tags else "general"),
                        hosts=src.hosts,
                        audience="mark",  # legacy field
                        priority=tl.priority,
                        enabled=tl.enabled,
                    ))
        if podcasts:
            return podcasts

    # Fall back to old format
    path = CONFIG_DIR / "podcasts.yaml"
    if not path.exists():
        return []
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return [PodcastConfig(**p) for p in raw.get("podcasts", [])]


def get_podcast_by_slug(slug: str) -> PodcastConfig | None:
    for p in load_podcasts():
        if p.slug == slug:
            return p
    return None


def get_assemblyai_key() -> str:
    key = os.environ.get("ASSEMBLYAI_API_KEY", "")
    if not key:
        raise RuntimeError("ASSEMBLYAI_API_KEY not set. Add it to .env or environment.")
    return key


def get_google_client_secret_path() -> Path:
    return Path(os.environ.get("GOOGLE_CLIENT_SECRET_PATH", "./credentials/client_secret.json"))


def get_google_token_path() -> Path:
    return Path(os.environ.get("GOOGLE_TOKEN_PATH", "./credentials/token.json"))
