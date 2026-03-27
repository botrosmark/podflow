"""Click CLI for podflow."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from podflow.config import get_podcast_by_slug, load_podcasts, load_settings, save_settings
from podflow.db import (
    get_analysis,
    get_analyzed_episodes_since,
    get_episode_by_id,
    get_episodes_by_status,
    get_failed_episodes,
    get_recent_episodes,
    get_unanalyzed_episodes,
    init_db,
    record_brief_sent,
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


def _try_free_transcripts(limit: int) -> int:
    """Try to get free transcripts for detected episodes. Returns count completed."""
    from podflow.db import update_episode
    from podflow.pipeline.free_transcripts import get_free_transcript, has_free_source

    episodes = get_episodes_by_status(EpisodeStatus.detected, limit=limit)
    if not episodes:
        return 0

    completed = 0
    for ep in episodes:
        if not has_free_source(ep.podcast_slug):
            continue

        try:
            path = get_free_transcript(ep.podcast_slug, ep.title, ep.id)
            if path:
                ep.transcript_local_path = path
                ep.status = EpisodeStatus.storing
                update_episode(ep)

                # Upload to Drive
                from podflow.pipeline.enricher import build_filename
                from podflow.drive import get_drive_service, get_podcast_folder_id, upload_markdown
                from podflow.config import load_settings, get_podcast_by_slug

                settings = load_settings()
                podcast = get_podcast_by_slug(ep.podcast_slug)
                if podcast:
                    service = get_drive_service()
                    folder_id = get_podcast_folder_id(
                        service, settings.storage.root_folder_name,
                        podcast.category, podcast.name,
                    )
                    content = Path(path).read_text(encoding="utf-8")
                    filename = build_filename(ep)
                    result = upload_markdown(service, content, filename, folder_id)
                    ep.drive_file_id = result["id"]
                    ep.drive_url = result["url"]

                ep.status = EpisodeStatus.complete
                ep.completed_at = datetime.now(timezone.utc)
                update_episode(ep)
                console.print(f"  [green]Free transcript:[/green] {ep.podcast_name}: {ep.title[:40]}")
                completed += 1
        except Exception as e:
            logger.debug(f"Free transcript failed for {ep.title}: {e}")
            # Don't mark as error — let it fall through to AssemblyAI

    return completed


def _submit_new(limit: int) -> int:
    """Submit detected episodes for transcription via AssemblyAI. Returns count submitted."""
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
            console.print(f"  [cyan]Submitted:[/cyan] {ep.podcast_name}: {ep.title[:40]}")
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
@click.option("--free-only", is_flag=True, help="Only use free transcript sources, skip AssemblyAI")
def process(free_only: bool) -> None:
    """Collect completed transcriptions and submit new ones."""
    settings = load_settings()

    # Phase 1: Collect any completed transcriptions (from AssemblyAI)
    transcribing = get_episodes_by_status(EpisodeStatus.transcribing)
    if transcribing:
        console.print(f"[bold]Checking {len(transcribing)} transcription(s) in progress...[/bold]")
        completed = _collect_completed()
        if completed:
            console.print(f"[green]{completed} episode(s) completed and uploaded.[/green]\n")

    # Phase 2: Try free transcripts (YouTube captions, website scrapes)
    detected = get_episodes_by_status(EpisodeStatus.detected, limit=500)
    if detected:
        console.print(f"[bold]Trying free transcripts for {len(detected)} episode(s)...[/bold]")
        free_count = _try_free_transcripts(500)
        if free_count:
            console.print(f"[green]{free_count} episode(s) completed via free transcripts.[/green]\n")

    # Phase 3: Submit remaining to AssemblyAI (unless --free-only)
    if not free_only:
        remaining = get_episodes_by_status(EpisodeStatus.detected, limit=settings.polling.max_episodes_per_run)
        if remaining:
            console.print(f"[bold]Submitting {len(remaining)} episode(s) to AssemblyAI...[/bold]")
            submitted = _submit_new(settings.polling.max_episodes_per_run)
            console.print(f"[cyan]{submitted} episode(s) submitted to AssemblyAI.[/cyan]")

    still_detected = len(get_episodes_by_status(EpisodeStatus.detected))
    if still_detected and free_only:
        console.print(f"[dim]{still_detected} episode(s) remaining (no free source available, use without --free-only for AssemblyAI)[/dim]")
    elif not transcribing and not detected:
        console.print("[dim]Nothing to process.[/dim]")


@cli.command()
def run() -> None:
    """Full pipeline: poll → process → analyze (designed for cron)."""
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

    # Step 2.5: Try free transcripts first
    free_count = _try_free_transcripts(500)
    if free_count:
        console.print(f"[green]✓ {free_count} episode(s) completed via free transcripts.[/green]")

    # Step 3: Submit remaining to AssemblyAI
    submitted = _submit_new(settings.polling.max_episodes_per_run)
    if submitted:
        console.print(f"[cyan]{submitted} episode(s) submitted for transcription.[/cyan]")

    # Step 4: Analyze completed episodes
    if settings.analysis.enabled:
        unanalyzed = get_unanalyzed_episodes()
        if unanalyzed:
            console.print(f"\n[bold]Analyzing {len(unanalyzed)} episode(s)...[/bold]")
            from podflow.pipeline.analyzer import analyze_all
            results = analyze_all()
            if results:
                console.print(f"[green]✓ Analyzed {len(results)} episode(s).[/green]")

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
    table.add_column("Audience")
    table.add_column("Priority", justify="center")
    table.add_column("Enabled", justify="center")

    for p in sorted(podcasts, key=lambda x: (x.category, x.priority)):
        enabled = "[green]✓[/green]" if p.enabled else "[red]✗[/red]"
        audience_color = {"mark": "blue", "brooke": "magenta", "both": "green"}.get(p.audience, "white")
        table.add_row(p.slug, p.name, p.category, f"[{audience_color}]{p.audience}[/{audience_color}]", str(p.priority), enabled)

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


@cli.command()
def reupload() -> None:
    """Re-upload existing .md transcripts as Google Docs."""
    from podflow.drive import (
        delete_file,
        download_file_content,
        get_drive_service,
        get_podcast_folder_id,
        upload_markdown,
    )
    from podflow.db import update_episode

    settings = load_settings()
    service = get_drive_service()

    # Find all complete episodes with a Drive file
    episodes = get_episodes_by_status(EpisodeStatus.complete)
    targets = [ep for ep in episodes if ep.drive_file_id]

    if not targets:
        console.print("[dim]No completed episodes with Drive files to re-upload.[/dim]")
        return

    console.print(f"[bold]Re-uploading {len(targets)} transcript(s) as Google Docs...[/bold]\n")

    success = 0
    for ep in targets:
        try:
            # Download existing content from Drive
            console.print(f"  [dim]Downloading:[/dim] {ep.podcast_name}: {ep.title[:40]}")
            content = download_file_content(service, ep.drive_file_id)

            # Determine the target folder
            podcast = get_podcast_by_slug(ep.podcast_slug)
            if not podcast:
                console.print(f"    [red]✗ Unknown podcast slug: {ep.podcast_slug}[/red]")
                continue

            folder_id = get_podcast_folder_id(
                service,
                settings.storage.root_folder_name,
                podcast.category,
                podcast.name,
            )

            # Build filename without .md extension
            from podflow.pipeline.enricher import build_filename
            filename = build_filename(ep)

            # Delete old file
            console.print(f"    [dim]Deleting old .md file...[/dim]")
            delete_file(service, ep.drive_file_id)

            # Re-upload as Google Doc
            console.print(f"    [dim]Uploading as Google Doc...[/dim]")
            result = upload_markdown(service, content, filename, folder_id)

            # Update episode record
            ep.drive_file_id = result["id"]
            ep.drive_url = result["url"]
            update_episode(ep)

            console.print(f"    [green]✓ Done:[/green] {result['url']}")
            success += 1

        except Exception as e:
            console.print(f"    [red]✗ Error: {e}[/red]")
            logger.error(f"Failed to reupload {ep.title}: {e}")

    console.print(f"\n[green]Re-uploaded {success}/{len(targets)} transcript(s) as Google Docs.[/green]")


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


# ============================================
# ANALYSIS COMMANDS
# ============================================

@cli.command()
@click.option("--episode-id", type=int, help="Analyze a specific episode")
@click.option("--reanalyze", is_flag=True, help="Re-run analysis on already-analyzed episodes")
def analyze(episode_id: int | None, reanalyze: bool) -> None:
    """Analyze transcripts with Claude."""
    from podflow.pipeline.analyzer import analyze_all, analyze_episode

    if episode_id:
        ep = get_episode_by_id(episode_id)
        if not ep:
            console.print(f"[red]Episode {episode_id} not found[/red]")
            return
        if not ep.transcript_local_path:
            console.print(f"[red]Episode {episode_id} has no transcript[/red]")
            return

        console.print(f"[bold]Analyzing:[/bold] {ep.podcast_name}: {ep.title}")
        try:
            result = analyze_episode(
                episode_id=ep.id,
                podcast_slug=ep.podcast_slug,
                podcast_name=ep.podcast_name,
                episode_title=ep.title,
                transcript_path=ep.transcript_local_path,
                reanalyze=reanalyze,
            )
            if result:
                console.print(f"[green]✓ Analysis complete[/green]")
                console.print(f"  Summary: {result.one_sentence_summary}")
                console.print(f"  Tags: {', '.join(result.topic_tags)}")
                console.print(f"  Companies: {len(result.companies)}, Macro calls: {len(result.macro_calls)}")
            else:
                console.print("[dim]Episode already analyzed (use --reanalyze to redo)[/dim]")
        except Exception as e:
            console.print(f"[red]Analysis failed: {e}[/red]")
            logger.error(f"Analysis failed for {ep.title}: {e}", exc_info=True)
        return

    # Analyze all unanalyzed
    episodes = get_unanalyzed_episodes() if not reanalyze else [
        e for e in get_episodes_by_status(EpisodeStatus.complete) if e.transcript_local_path
    ]

    if not episodes:
        console.print("[dim]No episodes to analyze.[/dim]")
        return

    console.print(f"[bold]Analyzing {len(episodes)} episode(s)...[/bold]\n")
    results = analyze_all(reanalyze=reanalyze)
    console.print(f"\n[green]✓ Analyzed {len(results)} episode(s).[/green]")
    for r in results:
        console.print(f"  • {r.podcast_name}: {r.episode_title[:40]} — {r.one_sentence_summary[:60]}")

    # Auto-sync to Idea Bank
    if results:
        console.print(f"\n[bold]Syncing ideas to Idea Bank...[/bold]")
        try:
            from podflow.idea_bank import sync_all_analyses
            stats = sync_all_analyses()
            for sheet, count in stats.items():
                if count:
                    console.print(f"  [green]+ {count} new ideas in {sheet}[/green]")
        except Exception as e:
            console.print(f"  [yellow]Idea Bank sync skipped: {e}[/yellow]")


# ============================================
# IDEA BANK COMMANDS
# ============================================

@cli.command()
@click.option("--sync", "do_sync", is_flag=True, help="Sync all analyzed episodes to the Idea Bank")
@click.option("--top", "top_n", default=10, help="Show top N ideas per sheet")
def ideas(do_sync: bool, top_n: int) -> None:
    """Manage the Idea Bank in Google Sheets."""
    from podflow.idea_bank import get_or_create_spreadsheet, sync_all_analyses, get_top_ideas

    ss_id = get_or_create_spreadsheet()
    console.print(f"[dim]Idea Bank: https://docs.google.com/spreadsheets/d/{ss_id}[/dim]\n")

    if do_sync:
        console.print("[bold]Syncing all analyses to Idea Bank...[/bold]")
        stats = sync_all_analyses(ss_id)
        for sheet, count in stats.items():
            if count:
                console.print(f"  [green]+ {count} new ideas in {sheet}[/green]")
            else:
                console.print(f"  [dim]{sheet}: no new ideas (all already synced)[/dim]")
        console.print()

    # Show top ideas
    for sheet_name in ["Mark", "Brooke"]:
        top = get_top_ideas(sheet_name, limit=top_n, ss_id=ss_id)
        if not top:
            console.print(f"[dim]{sheet_name}: no ideas yet[/dim]")
            continue

        table = Table(title=f"Top {sheet_name} Ideas")
        table.add_column("Score", width=5, justify="center")
        table.add_column("Category", width=16)
        table.add_column("Idea", max_width=50)
        table.add_column("Detail", max_width=40)
        table.add_column("Status", width=8)

        for idea in top:
            cat_color = {
                "investment_signal": "green",
                "macro_call": "blue",
                "content_hook": "magenta",
                "marketing_tactic": "cyan",
                "contrarian": "yellow",
            }.get(idea["category"], "white")

            table.add_row(
                str(idea["score"]),
                f"[{cat_color}]{idea['category']}[/{cat_color}]",
                idea["idea"][:50],
                idea["detail"][:40],
                idea["status"],
            )

        console.print(table)
        console.print()


# ============================================
# BRIEF COMMANDS
# ============================================

@cli.command()
@click.option("--mark-only", is_flag=True, help="Only send Mark's brief")
@click.option("--brooke-only", is_flag=True, help="Only send Brooke's brief")
@click.option("--dry-run", is_flag=True, help="Save HTML locally, don't send")
@click.option("--weekly", is_flag=True, help="Generate weekly digest instead of daily")
@click.option("--since", default=None, help="Cover episodes since date (YYYY-MM-DD)")
def brief(mark_only: bool, brooke_only: bool, dry_run: bool, weekly: bool, since: str | None) -> None:
    """Generate and send email briefs."""
    from podflow.email.builder import (
        build_brooke_daily,
        build_mark_daily,
        build_weekly_brooke,
        build_weekly_mark,
    )

    settings = load_settings()

    # Determine lookback period
    if since:
        since_dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    elif weekly:
        since_dt = datetime.now(timezone.utc) - timedelta(days=7)
    else:
        since_dt = datetime.now(timezone.utc) - timedelta(hours=settings.email.lookback_hours)

    analyzed = get_analyzed_episodes_since(since_dt)
    if not analyzed:
        console.print("[dim]No analyzed episodes in the specified period. Skipping.[/dim]")
        return

    # Check if we already sent a brief covering these exact episodes (skip duplicates)
    if not since and not weekly and not dry_run:
        from podflow.db import get_connection as _gc
        conn = _gc()
        last = conn.execute(
            "SELECT episodes_covered FROM briefs_sent ORDER BY sent_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if last:
            import json as _json
            last_ids = set(_json.loads(last["episodes_covered"]))
            current_ids = {str(e.get("id", "")) for e in analyzed}
            if current_ids and current_ids == last_ids:
                console.print("[dim]No new episodes since last brief. Skipping.[/dim]")
                return

    console.print(f"[bold]Found {len(analyzed)} analyzed episode(s) since {since_dt.strftime('%Y-%m-%d')}[/bold]\n")

    send_mark = not brooke_only
    send_brooke = not mark_only
    now = datetime.now(timezone.utc)

    if weekly:
        _send_weekly_briefs(analyzed, send_mark, send_brooke, dry_run, settings)
    else:
        _send_daily_briefs(analyzed, send_mark, send_brooke, dry_run, settings)


def _send_daily_briefs(analyzed: list[dict], send_mark: bool, send_brooke: bool,
                       dry_run: bool, settings) -> None:
    from podflow.email.builder import build_brooke_daily, build_mark_daily

    now = datetime.now(timezone.utc)
    mark_eps = [e for e in analyzed if e.get("audience") in ("mark", "both", None)]
    brooke_eps = [e for e in analyzed if e.get("audience") in ("brooke", "both", None)]

    if send_mark and mark_eps:
        html = build_mark_daily(analyzed)
        subject = f"Podflow Brief — {now.strftime('%b %d, %Y')} — {len(mark_eps)} episodes"
        if dry_run:
            _save_dry_run(html, "daily_mark")
            console.print(f"[green]✓ Mark's brief saved ({len(mark_eps)} episodes)[/green]")
        else:
            from podflow.email.sender import send_email
            send_email(subject, html, settings.email.mark_recipients)
            record_brief_sent("daily_mark", [str(e.get("id", "")) for e in mark_eps],
                            ", ".join(settings.email.mark_recipients))
            console.print(f"[green]✓ Mark's brief sent to {settings.email.mark_recipients}[/green]")

    if send_brooke and brooke_eps:
        html = build_brooke_daily(analyzed)
        subject = f"ATELIER Intel — {now.strftime('%b %d, %Y')} — {len(brooke_eps)} episodes"
        if dry_run:
            _save_dry_run(html, "daily_brooke")
            console.print(f"[green]✓ Brooke's brief saved ({len(brooke_eps)} episodes)[/green]")
        else:
            from podflow.email.sender import send_email
            send_email(subject, html, settings.email.brooke_recipients)
            record_brief_sent("daily_brooke", [str(e.get("id", "")) for e in brooke_eps],
                            ", ".join(settings.email.brooke_recipients))
            console.print(f"[green]✓ Brooke's brief sent to {settings.email.brooke_recipients}[/green]")


def _send_weekly_briefs(analyzed: list[dict], send_mark: bool, send_brooke: bool,
                        dry_run: bool, settings) -> None:
    from podflow.email.builder import build_weekly_brooke, build_weekly_mark
    from podflow.pipeline.analyzer import generate_weekly_synthesis

    now = datetime.now(timezone.utc)

    # Collect all analyses JSON for synthesis
    mark_analyses = []
    brooke_analyses = []
    for ep in analyzed:
        analysis = json.loads(ep.get("analysis_json", "{}"))
        audience = ep.get("audience", analysis.get("audience", "mark"))
        if audience in ("mark", "both"):
            mark_analyses.append(analysis)
        if audience in ("brooke", "both"):
            brooke_analyses.append(analysis)

    if send_mark and mark_analyses:
        console.print("[bold]Generating Mark's weekly synthesis...[/bold]")
        synthesis = generate_weekly_synthesis(json.dumps(mark_analyses), "mark")
        html = build_weekly_mark(synthesis, len(mark_analyses))
        subject = f"Podflow Weekly — {now.strftime('%b %d, %Y')} — {len(mark_analyses)} episodes"
        if dry_run:
            _save_dry_run(html, "weekly_mark")
            console.print(f"[green]✓ Mark's weekly saved ({len(mark_analyses)} episodes)[/green]")
        else:
            from podflow.email.sender import send_email
            send_email(subject, html, settings.email.mark_recipients)
            record_brief_sent("weekly_mark", [str(e.get("id", "")) for e in analyzed],
                            ", ".join(settings.email.mark_recipients))
            console.print(f"[green]✓ Mark's weekly sent[/green]")

    if send_brooke and brooke_analyses:
        console.print("[bold]Generating Brooke's weekly synthesis...[/bold]")
        synthesis = generate_weekly_synthesis(json.dumps(brooke_analyses), "brooke")
        html = build_weekly_brooke(synthesis, len(brooke_analyses))
        subject = f"ATELIER Weekly — {now.strftime('%b %d, %Y')} — {len(brooke_analyses)} episodes"
        if dry_run:
            _save_dry_run(html, "weekly_brooke")
            console.print(f"[green]✓ Brooke's weekly saved ({len(brooke_analyses)} episodes)[/green]")
        else:
            from podflow.email.sender import send_email
            send_email(subject, html, settings.email.brooke_recipients)
            record_brief_sent("weekly_brooke", [str(e.get("id", "")) for e in analyzed],
                            ", ".join(settings.email.brooke_recipients))
            console.print(f"[green]✓ Brooke's weekly sent[/green]")


def _save_dry_run(html: str, name: str) -> None:
    from podflow.config import get_data_dir
    out_dir = get_data_dir() / "briefs"
    out_dir.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    path = out_dir / f"{name}_{now}.html"
    path.write_text(html, encoding="utf-8")
    console.print(f"  [dim]Saved: {path}[/dim]")


# ============================================
# SEARCH COMMAND
# ============================================

@cli.command()
@click.argument("query")
@click.option("--podcast", "-p", default=None, help="Filter by podcast slug")
@click.option("--since", default=None, help="Only search episodes since date (YYYY-MM-DD)")
@click.option("--limit", "-n", default=20, help="Max results to show")
def search(query: str, podcast: str | None, since: str | None, limit: int) -> None:
    """Search all local transcripts for a query string."""
    from podflow.db import get_connection

    conn = get_connection()
    try:
        sql = """
            SELECT id, podcast_slug, podcast_name, title, published_date,
                   transcript_local_path
            FROM episodes
            WHERE status = 'complete'
            AND transcript_local_path IS NOT NULL
        """
        params = []
        if podcast:
            sql += " AND podcast_slug = ?"
            params.append(podcast)
        if since:
            sql += " AND published_date >= ?"
            params.append(since)
        sql += " ORDER BY published_date DESC"

        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    if not rows:
        console.print("[dim]No transcripts to search.[/dim]")
        return

    results = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    for row in rows:
        path = Path(row["transcript_local_path"])
        if not path.exists():
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue

        lines = content.split("\n")
        for i, line in enumerate(lines):
            if pattern.search(line):
                # Get surrounding context (1 line before, 1 after)
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                context_lines = lines[start:end]
                results.append({
                    "podcast_name": row["podcast_name"],
                    "title": row["title"],
                    "date": row["published_date"] or "",
                    "line_num": i + 1,
                    "context": context_lines,
                    "match_line": line,
                })
                if len(results) >= limit:
                    break

        if len(results) >= limit:
            break

    if not results:
        console.print(f"[dim]No matches found for '{query}'.[/dim]")
        return

    console.print(f"[bold]Found {len(results)} match(es) for '{query}':[/bold]\n")

    for r in results:
        console.print(f"[cyan]{r['podcast_name']}[/cyan] — {r['title']}")
        console.print(f"[dim]{r['date']} · line {r['line_num']}[/dim]")
        for ctx_line in r["context"]:
            # Highlight the matched term
            highlighted = pattern.sub(lambda m: f"[bold yellow]{m.group()}[/bold yellow]", ctx_line.strip())
            console.print(f"  {highlighted}")
        console.print()
