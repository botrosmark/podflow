# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Podflow

Podflow is a podcast content intelligence pipeline that polls RSS feeds, transcribes episodes via AssemblyAI, and uploads formatted markdown transcripts to Google Drive. It monitors 18 configured podcasts on a cron schedule.

## Development Commands

```bash
# Install dependencies
uv sync

# Run CLI commands
uv run podflow <command>

# Key commands
uv run podflow poll              # Detect new episodes from RSS feeds
uv run podflow process           # Transcribe pending + upload to Drive
uv run podflow run               # Full pipeline (poll → process), used by cron
uv run podflow status            # Show episode statuses
uv run podflow test-feed <slug>  # Validate a single podcast feed
uv run podflow test-transcribe <url>  # Test transcription on an audio URL
uv run podflow retry --all-failed     # Reprocess failed episodes
uv run podflow backfill -p <slug> -n <count>  # Backfill old episodes
```

No test suite, linter, or CI pipeline exists yet.

## Architecture

**Data flow:** RSS Feeds → Detector → SQLite DB → Transcriber (AssemblyAI) → Enricher (markdown) → Storer (Google Drive)

**Episode state machine:** `detected → transcribing → storing → complete` (with `error` state and retry support)

### Key modules (`src/podflow/`)

- **cli.py** — Click CLI entry point (`podflow.cli:cli`), orchestrates pipeline phases
- **config.py** — Loads `config/podcasts.yaml` and `config/settings.yaml`, manages env vars
- **db.py** — SQLite3 with WAL mode, single `episodes` table, JSON serialization for array fields
- **models.py** — Pydantic models: `Episode`, `EpisodeStatus`, `Transcript`, `PodcastConfig`, `Settings`
- **drive.py** — Google Drive OAuth and uploads with folder hierarchy (Root → Category → Podcast)
- **pipeline/detector.py** — RSS polling with feedparser, deduplication by GUID
- **pipeline/transcriber.py** — Non-blocking AssemblyAI integration (submit → poll → parse with speaker diarization)
- **pipeline/enricher.py** — Builds YAML-frontmatter markdown transcripts with metadata
- **pipeline/storer.py** — Uploads enriched markdown to Google Drive

### Design notes

- Transcription is non-blocking: audio URLs are sent directly to AssemblyAI (no local download), then polled for completion.
- Episode model has placeholder fields for future Claude-powered analysis (summary, key_quotes, themes, content_brief).
- Config is split: `podcasts.yaml` defines feeds/categories/hosts; `settings.yaml` defines runtime behavior.

## Environment Variables

Required in `.env` (see `.env.example`):
- `ASSEMBLYAI_API_KEY` — transcription service key
- `GOOGLE_CLIENT_SECRET_PATH` — path to OAuth JSON (default: `./credentials/client_secret.json`)
- `GOOGLE_TOKEN_PATH` — path to saved token (default: `./credentials/token.json`)
