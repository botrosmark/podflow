"""Config loading and validation."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from podflow.models import PodcastConfig, Settings

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


def load_podcasts() -> list[PodcastConfig]:
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
