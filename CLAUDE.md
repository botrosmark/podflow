# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Podflow

Podflow is a podcast content intelligence pipeline that polls RSS feeds, transcribes episodes via AssemblyAI, analyzes transcripts with Claude, and delivers personalized email briefs. It monitors 34 configured podcasts across two audience feeds (Mark and Brooke) on a cron schedule.

## Development Commands

```bash
# Install dependencies
uv sync

# Run CLI commands
uv run podflow <command>

# Key commands
uv run podflow poll              # Detect new episodes from RSS feeds
uv run podflow process           # Transcribe pending + upload to Drive
uv run podflow run               # Full pipeline (poll → process → analyze), used by cron
uv run podflow status            # Show episode statuses
uv run podflow analyze           # Analyze un-analyzed transcripts with Claude
uv run podflow brief --dry-run   # Generate email briefs (save locally without sending)
uv run podflow brief             # Generate and send daily email briefs
uv run podflow brief --weekly    # Generate and send weekly digest
uv run podflow search "query"    # Search all local transcripts
uv run podflow test-feed <slug>  # Validate a single podcast feed
uv run podflow test-transcribe <url>  # Test transcription on an audio URL
uv run podflow retry --all-failed     # Reprocess failed episodes
uv run podflow backfill -p <slug> -n <count>  # Backfill old episodes
```

No test suite, linter, or CI pipeline exists yet.

## Architecture

**Data flow:** RSS Feeds → Detector → SQLite DB → Transcriber (AssemblyAI) → Enricher (markdown) → Storer (Google Drive) → Analyzer (Claude) → Email Briefs (Resend)

**Episode state machine:** `detected → transcribing → storing → complete` (with `error` state and retry support)

**Audience system:** Each podcast is tagged `audience: mark`, `audience: brooke`, or `audience: both`. Analysis uses different prompts per audience. Daily briefs are personalized: Mark gets investment intelligence, Brooke gets marketing/brand tactics.

### Key modules (`src/podflow/`)

- **cli.py** — Click CLI entry point (`podflow.cli:cli`), orchestrates all pipeline phases
- **config.py** — Loads `config/podcasts.yaml` and `config/settings.yaml`, manages env vars
- **db.py** — SQLite3 with WAL mode; tables: `episodes`, `episode_analysis`, `briefs_sent`
- **models.py** — Pydantic models: `Episode`, `EpisodeStatus`, `Transcript`, `PodcastConfig`, `Settings`, `EmailSettings`
- **drive.py** — Google Drive + Gmail OAuth, uploads with folder hierarchy (Root → Category → Podcast)
- **pipeline/detector.py** — RSS polling with feedparser, deduplication by GUID
- **pipeline/transcriber.py** — Non-blocking AssemblyAI integration (submit → poll → parse with speaker diarization)
- **pipeline/enricher.py** — Builds YAML-frontmatter markdown transcripts with metadata
- **pipeline/storer.py** — Uploads enriched markdown to Google Drive
- **pipeline/analyzer.py** — Claude API analysis of transcripts, stores structured output in SQLite
- **analysis/models.py** — Pydantic models for structured analysis output (EpisodeAnalysis, CompanyMention, etc.)
- **analysis/prompts.py** — All Claude prompts centralized (Mark analysis, Brooke analysis, weekly synthesis)
- **email/builder.py** — Constructs email HTML from analysis data using Jinja2 templates
- **email/sender.py** — Email sending via Resend API
- **email/templates/** — Jinja2 HTML templates for daily briefs and weekly digests

### Design notes

- Transcription is non-blocking: audio URLs are sent directly to AssemblyAI (no local download), then polled for completion.
- For `audience: both` podcasts, both Mark and Brooke analysis prompts are run and results merged.
- Transcripts exceeding 120K tokens are truncated intelligently (keep head/tail, sample middle).
- Config is split: `podcasts.yaml` defines feeds/categories/hosts/audience; `settings.yaml` defines runtime behavior.
- Email delivery via Resend API (no OAuth scope needed).

## Environment Variables

Required in `.env` (see `.env.example`):
- `ASSEMBLYAI_API_KEY` — transcription service key
- `ANTHROPIC_API_KEY` — Claude API key for analysis
- `GOOGLE_CLIENT_SECRET_PATH` — path to OAuth JSON (default: `./credentials/client_secret.json`)
- `GOOGLE_TOKEN_PATH` — path to saved token (default: `./credentials/token.json`)
- `RESEND_API_KEY` — Resend email service key
- `RESEND_FROM_ADDRESS` — sender address (default: `Podflow <podflow@resend.dev>`)
