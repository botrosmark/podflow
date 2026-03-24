# podflow

Podcast content intelligence pipeline. Automatically detects new episodes via RSS, transcribes audio with AssemblyAI (speaker diarization), and uploads structured Markdown transcripts to Google Drive. Designed to run on a VPS via cron every 30 minutes.

This is the data retrieval and cataloguing foundation — downstream analysis with Claude (quote extraction, content briefs, theme detection) plugs into the same pipeline.

## Architecture

```
┌─────────────┐     ┌────────────┐     ┌──────────────┐     ┌─────────────┐
│  RSS Feeds  │────▶│  Detector  │────▶│ Transcriber  │────▶│   Storer    │
│ (18 shows)  │     │ feedparser │     │  AssemblyAI  │     │ Google Drive│
└─────────────┘     └────────────┘     └──────────────┘     └─────────────┘
                          │                                       │
                          ▼                                       ▼
                    ┌────────────┐                     ┌──────────────────┐
                    │   SQLite   │                     │ Podcast Transcripts/
                    │   State    │                     │  ├── Investing/
                    │  Tracker   │                     │  ├── Tech/
                    └────────────┘                     │  ├── AI/
                                                       │  └── General/
                                                       └──────────────────┘
```

## Quick Start

### 1. Install

```bash
# Requires uv (https://docs.astral.sh/uv/)
uv sync
```

### 2. Environment

```bash
cp .env.example .env
# Edit .env and add your AssemblyAI API key
```

### 3. Google Drive Auth

Place your Google OAuth client secret at `credentials/client_secret.json`, then:

```bash
podflow setup-drive
```

This opens a browser for one-time OAuth consent and creates the Drive folder structure.

### 4. First Run

```bash
# Check all feeds and detect new episodes
podflow poll

# See what was detected
podflow status

# Process detected episodes (transcribe + upload)
podflow process
```

### 5. Cron Setup (VPS)

```bash
# Run every 30 minutes
*/30 * * * * cd /path/to/podcast-topics && /path/to/uv run podflow run >> /var/log/podflow.log 2>&1
```

## Adding / Removing Podcasts

Edit `config/podcasts.yaml`. Each entry needs:

```yaml
- name: "Podcast Name"
  slug: podcast-name          # URL-safe identifier
  rss_url: "https://..."      # RSS feed URL
  category: investing          # investing | tech | ai | general
  hosts: ["Host Name"]
  priority: 1                  # 1=high, 3=low (processing order)
  enabled: true                # Set false to skip
```

Validate the feed: `podflow test-feed podcast-name`

## CLI Reference

| Command | Description |
|---------|-------------|
| `podflow poll` | Check feeds, detect new episodes |
| `podflow process` | Transcribe and upload all detected episodes |
| `podflow run` | poll + process (what cron calls) |
| `podflow status` | Rich table of recent episodes |
| `podflow status -p <slug>` | Filter status by podcast |
| `podflow list-podcasts` | Show configured podcasts |
| `podflow test-feed <slug>` | Validate a feed, show latest episodes |
| `podflow test-transcribe <url>` | One-off transcription test |
| `podflow retry --episode-id <id>` | Retry one failed episode |
| `podflow retry --all-failed` | Retry all failures |
| `podflow backfill -p <slug> -n 5` | Backfill last N episodes |
| `podflow setup-drive` | Create Drive folder structure |

## Cost Estimate

- **AssemblyAI**: ~$0.37/hour of audio
- **18 podcasts**, ~2 episodes/week each, ~1 hour average = ~36 hours/week
- **Monthly estimate**: ~$53/month at full volume
- Google Drive: free (within normal usage)

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ASSEMBLYAI_API_KEY` | AssemblyAI API key |
| `GOOGLE_CLIENT_SECRET_PATH` | Path to OAuth client secret (default: `./credentials/client_secret.json`) |
| `GOOGLE_TOKEN_PATH` | Path to saved OAuth token (default: `./credentials/token.json`) |
