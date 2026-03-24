"""Click CLI for podflow."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import click
from rich.console import Console
from rich.table import Table

from podflow.config import get_podcast_by_slug, load_podcasts, load_settings, save_settings
from podflow.db import (
    get_episode_by_id,
    get_episodes_by_status,
    get_failed_episodes,
    get_recent_episodes,
    init_db,
    reset_episode_for_retry,
)
from podflow.models import EpisodeStatus
from podflow.utils import format_duration, setup_logging

console = Console()
logger = logging.getLogger(__name__)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def cli(verbose: bool) -> None:
    """podflow — Podcast content intelligence pipeline."""
    setup_logging(verbose)
    init_db()


@cli.command()
def poll() -> None:
    """Check RSS feeds and detect new episodes."""
    from podflow.pipeline.detector import poll_all_feeds

    new_episodes = poll_all_feeds()
    if new_episodes:
        console.print(f"\n[green]Detected {len(new_episodes)} new episode(s):[/green]")
        for ep in new_episodes:
            console.print(f"  • {ep.podcast_name}: {ep.title}")
    else:
        console.print("[dim]No new episodes found.[/dim]")


def _collect_completed() -> int:
    """Check transcribing episodes and store any that are done. Returns count of completed."""
    from podflow.pipeline.downloader import cleanup_audio
    from podflow.pipeline.storer import store_transcript
    from podflow.pipeline.transcriber import check_transcription

    transcribing = get_episodes_by_status(EpisodeStatus.transcribing)
    if not transcribing:
        return 0

    completed = 0
    for ep in transcribing:
        try:
            transcript = check_transcription(ep)
            if transcript is None:
                console.print(f"  [dim]⏳ Still transcribing: {ep.podcast_name}: {ep.title[:40]}[/dim]")
                continue

            console.print(f"  [blue]Transcription ready:[/blue] {ep.podcast_name}: {ep.title[:40]}")
            console.print(f"    [dim]{transcript.word_count} words, {transcript.speakers_detected} speakers[/dim]")

            ep = store_transcript(ep, transcript)
            console.print(f"    [green]✓ Uploaded to Drive[/green]")

            cleanup_audio(ep)
            completed += 1

        except Exception as e:
            logger.error(f"Failed to collect {ep.title}: {e}")
            ep.status = EpisodeStatus.error
            ep.error_message = str(e)
            from podflow.db import update_episode
            update_episode(ep)
            console.print(f"    [red]✗ Error: {e}[/red]")

    return completed


def _submit_new(limit: int) -> int:
    """Submit detected episodes for transcription. Returns count submitted."""
    from podflow.pipeline.transcriber import submit_transcription

    episodes = get_episodes_by_status(EpisodeStatus.detected, limit=limit)
    if not episodes:
        return 0

    submitted = 0
    for ep in episodes:
        try:
            if not ep.audio_url:
                logger.warning(f"Skipping {ep.title}: no audio URL")
                continue

            submit_transcription(ep)
            console.print(f"  [cyan]📤 Submitted:[/cyan] {ep.podcast_name}: {ep.title[:40]}")
            submitted += 1

        except Exception as e:
            logger.error(f"Failed to submit {ep.title}: {e}")
            ep.status = EpisodeStatus.error
            ep.error_message = str(e)
            from podflow.db import update_episode
            update_episode(ep)
            console.print(f"  [red]✗ Submit error: {e}[/red]")

    return submitted


@cli.command()
def process() -> None:
    """Collect completed transcriptions and submit new ones."""
    settings = load_settings()

    # Phase 1: Collect any completed transcriptions
    transcribing = get_episodes_by_status(EpisodeStatus.transcribing)
    if transcribing:
        console.print(f"[bold]Checking {len(transcribing)} transcription(s) in progress...[/bold]")
        completed = _collect_completed()
        if completed:
            console.print(f"[green]{completed} episode(s) completed and uploaded.[/green]\n")

    # Phase 2: Submit new episodes for transcription
    detected = get_episodes_by_status(EpisodeStatus.detected, limit=settings.polling.max_episodes_per_run)
    if detected:
        console.print(f"[bold]Submitting {len(detected)} episode(s) for transcription...[/bold]")
        submitted = _submit_new(settings.polling.max_episodes_per_run)
        console.print(f"[cyan]{submitted} episode(s) submitted to AssemblyAI.[/cyan]")

    if not transcribing and not detected:
        console.print("[dim]Nothing to process.[/dim]")


@cli.command()
def run() -> None:
    """Poll feeds, collect completed transcriptions, submit new ones (designed for cron)."""
    from podflow.pipeline.detector import poll_all_feeds

    settings = load_settings()

    # Step 1: Poll for new episodes
    new_episodes = poll_all_feeds()
    if new_episodes:
        console.print(f"[green]Detected {len(new_episodes)} new episode(s)[/green]")

    # Step 2: Collect completed transcriptions
    completed = _collect_completed()
    if completed:
        console.print(f"[green]✓ {completed} episode(s) completed and uploaded.[/green]")

    # Step 3: Submit new episodes for transcription
    submitted = _submit_new(settings.polling.max_episodes_per_run)
    if submitted:
        console.print(f"[cyan]{submitted} episode(s) submitted for transcription.[/cyan]")

    # Summary
    still_transcribing = len(get_episodes_by_status(EpisodeStatus.transcribing))
    still_detected = len(get_episodes_by_status(EpisodeStatus.detected))
    if still_transcribing or still_detected:
        console.print(f"[dim]Queue: {still_transcribing} transcribing, {still_detected} waiting[/dim]")
    elif not new_episodes and not completed and not submitted:
        console.print("[dim]All caught up.[/dim]")


@cli.command()
@click.option("--podcast", "-p", default=None, help="Filter by podcast slug")
@click.option("--limit", "-n", default=20, help="Number of episodes to show")
def status(podcast: str | None, limit: int) -> None:
    """Show recent episodes and their processing status."""
    episodes = get_recent_episodes(limit=limit, podcast_slug=podcast)

    if not episodes:
        console.print("[dim]No episodes found.[/dim]")
        return

    table = Table(title="Recent Episodes")
    table.add_column("ID", style="dim", width=5)
    table.add_column("Podcast", style="cyan", max_width=25)
    table.add_column("Title", max_width=40)
    table.add_column("Date", width=12)
    table.add_column("Duration", width=8)
    table.add_column("Status", width=12)

    status_colors = {
        "detected": "yellow",
        "downloading": "blue",
        "transcribing": "blue",
        "storing": "blue",
        "complete": "green",
        "error": "red",
    }

    for ep in episodes:
        date_str = ep.published_date.strftime("%Y-%m-%d") if ep.published_date else "—"
        color = status_colors.get(ep.status.value, "white")
        table.add_row(
            str(ep.id),
            ep.podcast_name,
            ep.title[:40],
            date_str,
            format_duration(ep.duration_seconds),
            f"[{color}]{ep.status.value}[/{color}]",
        )

    console.print(table)


@cli.command("list-podcasts")
def list_podcasts() -> None:
    """Show configured podcasts and their enabled state."""
    podcasts = load_podcasts()

    table = Table(title="Configured Podcasts")
    table.add_column("Slug", style="cyan")
    table.add_column("Name")
    table.add_column("Category")
    table.add_column("Priority", justify="center")
    table.add_column("Enabled", justify="center")

    for p in sorted(podcasts, key=lambda x: (x.category, x.priority)):
        enabled = "[green]✓[/green]" if p.enabled else "[red]✗[/red]"
        table.add_row(p.slug, p.name, p.category, str(p.priority), enabled)

    console.print(table)
    console.print(f"\n[dim]{len(podcasts)} podcasts configured, {sum(1 for p in podcasts if p.enabled)} enabled[/dim]")


@cli.command("test-feed")
@click.argument("slug")
@click.option("--count", "-n", default=5, help="Number of entries to show")
def test_feed_cmd(slug: str, count: int) -> None:
    """Validate a podcast feed and show latest episodes."""
    podcast = get_podcast_by_slug(slug)
    if not podcast:
        console.print(f"[red]Unknown podcast slug: {slug}[/red]")
        console.print("[dim]Run 'podflow list-podcasts' to see available slugs.[/dim]")
        return

    console.print(f"[bold]Testing feed:[/bold] {podcast.name}")
    console.print(f"[dim]URL: {podcast.rss_url}[/dim]\n")

    try:
        from podflow.pipeline.detector import test_feed
        entries = test_feed(podcast, count)

        if not entries:
            console.print("[red]No entries found in feed![/red]")
            return

        table = Table(title=f"Latest {len(entries)} Episodes")
        table.add_column("Title", max_width=50)
        table.add_column("Published", width=20)
        table.add_column("Duration", width=10)
        table.add_column("Audio URL", max_width=30)

        for e in entries:
            dur = format_duration(e["duration"]) if e["duration"] else "—"
            audio = "✓" if e["audio_url"] else "[red]✗ missing[/red]"
            table.add_row(e["title"][:50], e["published"][:20], dur, audio)

        console.print(table)
        console.print(f"\n[green]Feed is working![/green]")

    except Exception as e:
        console.print(f"[red]Feed error: {e}[/red]")


@cli.command("test-transcribe")
@click.argument("audio_url")
def test_transcribe_cmd(audio_url: str) -> None:
    """One-off transcription test with an audio URL."""
    import assemblyai as aai
    from podflow.config import get_assemblyai_key

    aai.settings.api_key = get_assemblyai_key()

    console.print(f"[bold]Submitting for transcription...[/bold]")
    console.print(f"[dim]{audio_url}[/dim]\n")

    config = aai.TranscriptionConfig(speaker_labels=True, language_code="en")
    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(audio_url, config=config)

    if transcript.status == aai.TranscriptStatus.error:
        console.print(f"[red]Error: {transcript.error}[/red]")
        return

    word_count = len(transcript.text.split()) if transcript.text else 0
    speakers = len({u.speaker for u in (transcript.utterances or [])})

    console.print(f"[green]Success![/green]")
    console.print(f"Words: {word_count}")
    console.print(f"Speakers: {speakers}")
    console.print(f"Confidence: {transcript.confidence:.2f}")

    if transcript.utterances:
        console.print(f"\n[bold]First 3 utterances:[/bold]")
        for utt in transcript.utterances[:3]:
            console.print(f"  [cyan]Speaker {utt.speaker}:[/cyan] {utt.text[:100]}...")


@cli.command()
@click.option("--episode-id", type=int, help="Retry a specific failed episode")
@click.option("--all-failed", is_flag=True, help="Retry all failed episodes")
def retry(episode_id: int | None, all_failed: bool) -> None:
    """Retry failed episodes."""
    if not episode_id and not all_failed:
        console.print("[red]Specify --episode-id or --all-failed[/red]")
        return

    if episode_id:
        ep = get_episode_by_id(episode_id)
        if not ep:
            console.print(f"[red]Episode {episode_id} not found[/red]")
            return
        if ep.status != EpisodeStatus.error:
            console.print(f"[yellow]Episode {episode_id} is not in error state (status={ep.status.value})[/yellow]")
            return
        reset_episode_for_retry(episode_id)
        console.print(f"[green]Reset episode {episode_id} for retry. Run 'podflow process' to reprocess.[/green]")
    else:
        failed = get_failed_episodes()
        if not failed:
            console.print("[dim]No failed episodes.[/dim]")
            return
        for ep in failed:
            reset_episode_for_retry(ep.id)
        console.print(f"[green]Reset {len(failed)} failed episode(s). Run 'podflow process' to reprocess.[/green]")


@cli.command()
@click.option("--podcast", "-p", required=True, help="Podcast slug")
@click.option("--count", "-n", default=5, help="Number of episodes to backfill")
def backfill(podcast: str, count: int) -> None:
    """Backfill the last N episodes for a podcast."""
    from podflow.pipeline.detector import detect_new_episodes

    pod = get_podcast_by_slug(podcast)
    if not pod:
        console.print(f"[red]Unknown podcast: {podcast}[/red]")
        return

    console.print(f"[bold]Backfilling {count} episodes for {pod.name}...[/bold]")

    # Use a very long lookback to grab older episodes
    new_eps = detect_new_episodes(pod, lookback_days=365 * 5)
    # Limit to requested count (they come in feed order, usually newest first)
    added = new_eps[:count]

    if added:
        console.print(f"[green]Added {len(added)} episode(s):[/green]")
        for ep in added:
            console.print(f"  • {ep.title}")
        console.print(f"\n[dim]Run 'podflow process' to transcribe and upload.[/dim]")
    else:
        console.print("[dim]No new episodes to add (all may already be tracked).[/dim]")


@cli.command("setup-drive")
def setup_drive_cmd() -> None:
    """Create Google Drive folder structure and authenticate."""
    from podflow.drive import run_oauth_flow, setup_folder_structure, find_or_create_folder, get_drive_service

    settings = load_settings()

    # Run OAuth if needed
    try:
        from podflow.drive import get_credentials
        get_credentials()
        console.print("[green]Google credentials already valid.[/green]")
    except RuntimeError:
        console.print("[bold]Starting Google OAuth flow...[/bold]")
        run_oauth_flow()
        console.print("[green]Authentication successful![/green]")

    # Create folder structure
    console.print(f"\n[bold]Creating folder structure: {settings.storage.root_folder_name}/[/bold]")
    folder_map = setup_folder_structure(settings.storage.root_folder_name)

    # Save root folder ID
    service = get_drive_service()
    root_id = find_or_create_folder(service, settings.storage.root_folder_name)
    settings.storage.root_folder_id = root_id
    save_settings(settings)

    total_folders = sum(len(v) for v in folder_map.values())
    console.print(f"\n[green]Done! Created {total_folders} podcast folders across {len(folder_map)} categories.[/green]")
