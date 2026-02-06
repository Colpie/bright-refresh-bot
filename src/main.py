"""
Bright Staffing Job Refresh Bot - Main Entry Point

Usage:
    python -m src.main run [--dry-run] [--config CONFIG_PATH]
    python -m src.main run --resume RUN_ID
    python -m src.main status [RUN_ID]
    python -m src.main history [--limit N]
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .config import load_config, validate_config, Config
from .api.client import BrightStaffingClient
from .services.state import StateManager, RunSummary
from .services.processor import JobProcessor
from .services.reporter import Reporter
from .services.rollback import RollbackService
from .utils.logging import setup_logging, get_logger

console = Console()


# --------------------------------------------------------------------------- #
#  Shared helpers
# --------------------------------------------------------------------------- #


def _quick_preflight_check(config: Config) -> bool:
    """Quick validation checks before production run."""
    checks_passed = True

    # Check API token
    if not config.api.access_token:
        console.print("  [red]FAIL[/red] No API token configured")
        checks_passed = False
    else:
        console.print("  [green]OK[/green] API token configured")

    # Check config errors
    errors = validate_config(config)
    if errors:
        console.print(f"  [red]FAIL[/red] Configuration has {len(errors)} error(s)")
        checks_passed = False
    else:
        console.print("  [green]OK[/green] Configuration valid")

    return checks_passed


def _load_and_validate_config(
    config_path: Optional[str],
    *,
    dry_run: bool = False,
    verbose: bool = False,
) -> Config:
    """Load config, apply overrides, validate, and set up logging."""
    config = load_config(config_path)

    if dry_run:
        config.processor.dry_run = True

    errors = validate_config(config)
    if errors and not config.processor.dry_run:
        console.print("[red]Configuration errors:[/red]")
        for error in errors:
            console.print(f"  - {error}")
        sys.exit(1)

    log_level = "DEBUG" if verbose else config.logging.level
    setup_logging(
        level=log_level,
        log_dir=config.logging.dir,
        log_format=config.logging.format,
        max_file_size_mb=config.logging.max_file_size_mb,
        backup_count=config.logging.backup_count,
    )
    return config


async def _init_state(config: Config) -> Optional[StateManager]:
    """Create and initialize a StateManager (with DB existence check)."""
    db_path = Path(config.state.db_path)
    if not db_path.exists() and str(db_path) != ":memory:":
        console.print("[yellow]No processing history found[/yellow]")
        return None
    manager = StateManager(config.state.db_path)
    await manager.initialize()
    return manager


# --------------------------------------------------------------------------- #
#  Display helpers
# --------------------------------------------------------------------------- #


def _print_banner() -> None:
    banner = """
    +==================================================+
    |     Bright Staffing Job Refresh Bot v1.0.0        |
    |                                                   |
    |  Automated vacancy refresh for Bright Staffing    |
    +==================================================+
    """
    console.print(banner, style="bold blue")


def _print_config_summary(config: Config) -> None:
    table = Table(title="Configuration", show_header=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("API Base URL", config.api.base_url)
    table.add_row("API Version", config.api.api_version)
    table.add_row("Dry Run", "Yes" if config.processor.dry_run else "No")
    table.add_row("Batch Size", str(config.processor.batch_size))
    table.add_row("Close Reason ID", str(config.processor.close_reason))
    table.add_row("Multipost Channels", ", ".join(str(c) for c in config.processor.multipost_channels))
    table.add_row("Rate Limit", f"{config.api.rate_limit} req/sec")
    table.add_row("Circuit Breaker", f"{config.processor.circuit_breaker_threshold} failures")

    console.print(table)
    console.print()


def _print_result_summary(result) -> None:
    if result.total == 0:
        console.print(Panel("[yellow]No vacancies found to process[/yellow]"))
        return

    status_style = (
        "green" if result.failed == 0
        else "red" if result.successful == 0
        else "yellow"
    )

    table = Table(title="Processing Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right")

    table.add_row("Total Vacancies", str(result.total))
    table.add_row("Successful", f"[green]{result.successful}[/green]")
    table.add_row("Failed", f"[red]{result.failed}[/red]")
    table.add_row("Skipped", str(result.skipped))

    success_rate = (result.successful / result.total * 100) if result.total > 0 else 0
    table.add_row("Success Rate", f"[{status_style}]{success_rate:.1f}%[/{status_style}]")

    console.print(table)

    # Detailed error summary
    if result.failed > 0 and result.results:
        console.print()
        failed_results = [r for r in result.results if not r.success]

        # Group errors by type
        error_groups = {}
        for r in failed_results:
            error_key = r.error_message.split(":")[0] if r.error_message else "Unknown"
            if error_key not in error_groups:
                error_groups[error_key] = []
            error_groups[error_key].append(r)

        # Print error summary table
        error_table = Table(title="Error Summary", show_header=True)
        error_table.add_column("Error Type", style="red")
        error_table.add_column("Count", justify="right")
        error_table.add_column("Example Vacancy", style="dim")

        for error_type, errors in sorted(error_groups.items(), key=lambda x: -len(x[1])):
            example_id = errors[0].original_vacancy_id
            error_table.add_row(error_type, str(len(errors)), example_id)

        console.print(error_table)

        # Print detailed failures (limited to first 10)
        console.print("\n[red]Failed Vacancies (showing first 10):[/red]")
        for r in failed_results[:10]:
            console.print(f"  [red]X[/red] {r.original_vacancy_id}: {r.error_message}")

        if len(failed_results) > 10:
            console.print(f"\n  ... and {len(failed_results) - 10} more failures")
            console.print(f"  [dim]Use 'python -m src.main status <run_id>' for full details[/dim]")


def _print_runs_table(runs: list[RunSummary], title: str, *, show_duration: bool = False) -> None:
    if not runs:
        console.print("[yellow]No processing history found[/yellow]")
        return

    table = Table(title=title)
    table.add_column("Run ID", style="cyan")
    table.add_column("Date")
    table.add_column("Status")
    table.add_column("Jobs")
    table.add_column("Success")
    table.add_column("Failed")
    if show_duration:
        table.add_column("Success Rate")
        table.add_column("Duration")

    for run in runs:
        status_style = (
            "green" if run.status == "completed"
            else "red" if run.status == "failed"
            else "yellow"
        )
        row = [
            run.run_id,
            run.started_at.strftime("%Y-%m-%d %H:%M"),
            f"[{status_style}]{run.status}[/{status_style}]",
            str(run.total_jobs),
            str(run.successful),
            str(run.failed),
        ]
        if show_duration:
            duration = f"{run.duration_seconds:.0f}s" if run.duration_seconds else "-"
            row.extend([f"{run.success_rate:.1f}%", duration])
        table.add_row(*row)

    console.print(table)


def _print_rollback_summary(result) -> None:
    if result.total_records == 0:
        console.print(Panel("[yellow]No records found to rollback[/yellow]"))
        return

    table = Table(title="Rollback Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right")

    table.add_row("Total Records", str(result.total_records))
    table.add_row("Reopened", f"[green]{result.reopened}[/green]")
    table.add_row("Closed New", f"[blue]{result.closed_new}[/blue]")
    table.add_row("Skipped", str(result.skipped))
    table.add_row("Failed", f"[red]{result.failed}[/red]")

    console.print(table)

    if result.failed > 0:
        console.print()
        console.print("[red]Failed Rollbacks:[/red]")
        for r in result.results:
            if not r.success:
                console.print(f"  - {r.vacancy_id}: {r.message}")


# --------------------------------------------------------------------------- #
#  CLI commands
# --------------------------------------------------------------------------- #


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """Bright Staffing Job Refresh Bot"""
    pass


@cli.command()
@click.option("--dry-run", is_flag=True, help="Run without making actual API calls")
@click.option("--config", "config_path", type=click.Path(exists=True), help="Path to config file")
@click.option("--resume", "resume_run_id", help="Resume a previous run by ID")
@click.option("--limit", type=int, help="Process only first N vacancies (for testing)")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def run(dry_run: bool, config_path: Optional[str], resume_run_id: Optional[str], limit: Optional[int], verbose: bool):
    """Run the job refresh process"""
    _print_banner()
    config = _load_and_validate_config(config_path, dry_run=dry_run, verbose=verbose)
    _print_config_summary(config)

    if config.processor.dry_run:
        console.print(Panel("[yellow]DRY RUN MODE - No actual API calls will be made[/yellow]"))

    if limit:
        console.print(Panel(f"[yellow]LIMIT MODE - Processing only first {limit} vacancies[/yellow]"))

    # Quick pre-flight check for production runs
    if not config.processor.dry_run and not resume_run_id:
        console.print("[cyan]Running pre-flight checks...[/cyan]")
        if not _quick_preflight_check(config):
            console.print("[red]Pre-flight checks failed. Use --dry-run to test, or run 'python -m src.main validate' for details.[/red]")
            sys.exit(1)
        console.print("[green]Pre-flight checks passed[/green]\n")

    try:
        result = asyncio.run(_run_processor(config, resume_run_id, limit))
        _print_result_summary(result)
        if result.failed > 0:
            sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Processing interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if verbose:
            console.print_exception()
        sys.exit(1)


async def _run_processor(config: Config, resume_run_id: Optional[str], limit: Optional[int] = None):
    state_manager = StateManager(config.state.db_path)
    await state_manager.initialize()

    async with BrightStaffingClient(
        config=config.api,
        dry_run=config.processor.dry_run,
        circuit_breaker_threshold=config.processor.circuit_breaker_threshold,
    ) as client:
        processor = JobProcessor(
            client=client,
            config=config.processor,
            state_manager=state_manager,
            dry_run=config.processor.dry_run,
            office_id=config.api.office_id,
        )

        result = await processor.run(
            run_id=resume_run_id,
            resume=bool(resume_run_id),
            limit=limit,
        )

        reporter = Reporter(state_manager, config.alerts)
        report = await reporter.generate_report(
            processor.run_id,
            dry_run=config.processor.dry_run,
        )

        if report:
            report_path = Path(config.logging.dir) / f"report_{processor.run_id}.md"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report.to_markdown())
            console.print(f"\nReport saved to: {report_path}")
            await reporter.send_alerts(report)

        return result


@cli.command()
@click.argument("run_id", required=False)
@click.option("--config", "config_path", type=click.Path(exists=True), help="Path to config file")
def status(run_id: Optional[str], config_path: Optional[str]):
    """Show status of a run or list recent runs"""
    config = load_config(config_path)
    asyncio.run(_show_status(config, run_id))


async def _show_status(config: Config, run_id: Optional[str]):
    state_manager = await _init_state(config)
    if state_manager is None:
        return

    if run_id:
        summary = await state_manager.get_run_summary(run_id)
        if not summary:
            console.print(f"[red]Run {run_id} not found[/red]")
            return

        table = Table(title=f"Run: {run_id}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value")

        table.add_row("Status", summary.status)
        table.add_row("Started", summary.started_at.strftime("%Y-%m-%d %H:%M:%S"))
        if summary.completed_at:
            table.add_row("Completed", summary.completed_at.strftime("%Y-%m-%d %H:%M:%S"))
        table.add_row("Total Jobs", str(summary.total_jobs))
        table.add_row("Successful", f"[green]{summary.successful}[/green]")
        table.add_row("Failed", f"[red]{summary.failed}[/red]")
        table.add_row("Skipped", str(summary.skipped))
        table.add_row("Success Rate", f"{summary.success_rate:.1f}%")
        if summary.duration_seconds:
            table.add_row("Duration", f"{summary.duration_seconds:.1f}s")

        console.print(table)

        if summary.failed > 0:
            failed_records = await state_manager.get_failed_records(run_id)
            if failed_records:
                console.print("\n[red]Failed Records:[/red]")
                for record in failed_records[:10]:
                    console.print(
                        f"  - {record.original_vacancy_id}: {record.error_message}"
                    )
                if len(failed_records) > 10:
                    console.print(f"  ... and {len(failed_records) - 10} more")
    else:
        runs = await state_manager.get_recent_runs(10)
        _print_runs_table(runs, "Recent Runs")


@cli.command()
@click.option("--limit", default=10, help="Number of runs to show")
@click.option("--config", "config_path", type=click.Path(exists=True), help="Path to config file")
def history(limit: int, config_path: Optional[str]):
    """Show processing history"""
    config = load_config(config_path)
    asyncio.run(_show_history(config, limit))


async def _show_history(config: Config, limit: int):
    state_manager = await _init_state(config)
    if state_manager is None:
        return
    runs = await state_manager.get_recent_runs(limit)
    _print_runs_table(runs, f"Processing History (Last {limit})", show_duration=True)


@cli.command()
@click.option("--config", "config_path", type=click.Path(exists=True), help="Path to config file")
def test_connection(config_path: Optional[str]):
    """Test API connection"""
    config = load_config(config_path)

    if not config.api.access_token:
        console.print("[red]No API token configured[/red]")
        console.print(
            "Set BRIGHT_API_ACCESS_TOKEN environment variable or configure in config file"
        )
        sys.exit(1)

    console.print(f"Testing connection to {config.api.base_url}...")
    asyncio.run(_test_connection(config))


async def _test_connection(config: Config):
    async with BrightStaffingClient(config=config.api) as client:
        try:
            response = await client.get_channels()
            if response.success:
                console.print("[green]Connection successful![/green]")
                if response.data:
                    console.print(f"Found {len(response.data)} channels")
            else:
                console.print(f"[red]Connection failed: {response.data}[/red]")
                sys.exit(1)
        except Exception as e:
            console.print(f"[red]Connection error: {e}[/red]")
            sys.exit(1)


@cli.command()
@click.option("--config", "config_path", type=click.Path(exists=True), help="Path to config file")
def validate(config_path: Optional[str]):
    """Validate configuration and API setup (pre-flight checks)"""
    _print_banner()
    console.print("[bold cyan]Pre-Flight Validation[/bold cyan]\n")

    config = load_config(config_path)
    asyncio.run(_run_validation(config))


async def _run_validation(config: Config):
    """Run comprehensive validation checks"""
    from .api.vacancy import VacancyService

    checks_passed = 0
    checks_total = 0

    # Check 1: API Token
    checks_total += 1
    console.print("[cyan]1. Checking API credentials...[/cyan]")
    if config.api.access_token:
        console.print("   [green]OK[/green] API token configured")
        checks_passed += 1
    else:
        console.print("   [red]FAIL[/red] No API token - set BRIGHT_API_ACCESS_TOKEN")

    # Check 2: API Connection
    checks_total += 1
    console.print("\n[cyan]2. Testing API connection...[/cyan]")
    try:
        async with BrightStaffingClient(config=config.api) as client:
            response = await client.get_channels()
            if response.success:
                console.print("   [green]OK[/green] API connection successful")
                checks_passed += 1
            else:
                console.print(f"   [red]FAIL[/red] API connection failed: {response.data}")
    except Exception as e:
        console.print(f"   [red]FAIL[/red] Connection error: {e}")

    # Check 3: List Channels
    checks_total += 1
    console.print("\n[cyan]3. Fetching available channels...[/cyan]")
    try:
        async with BrightStaffingClient(config=config.api) as client:
            vacancy_service = VacancyService(client)
            channels = await vacancy_service.get_channels()
            if channels:
                console.print(f"   [green]OK[/green] Found {len(channels)} channels:")
                for ch in channels:
                    status = "[green]active[/green]" if ch.active else "[red]inactive[/red]"
                    console.print(f"      - {ch.name} (ID: {ch.channel_id}) - {status}")
                checks_passed += 1
            else:
                console.print("   [yellow]WARN[/yellow] No channels found")
    except Exception as e:
        console.print(f"   [red]FAIL[/red] Failed to fetch channels: {e}")

    # Check 4: List Close Reasons
    checks_total += 1
    console.print("\n[cyan]4. Fetching valid close reasons...[/cyan]")
    try:
        async with BrightStaffingClient(config=config.api) as client:
            vacancy_service = VacancyService(client)
            reasons = await vacancy_service.get_close_reasons()
            if reasons:
                console.print(f"   [green]OK[/green] Found {len(reasons)} close reasons:")
                for reason in reasons[:10]:
                    reason_name = reason.get("name", reason.get("id", str(reason)))
                    console.print(f"      - {reason_name}")
                    if reason_name.lower() == config.processor.close_reason.lower():
                        console.print(f"        [green]OK - Configured reason '{config.processor.close_reason}' is valid[/green]")
                checks_passed += 1
            else:
                console.print("   [yellow]WARN[/yellow] No close reasons found")
    except Exception as e:
        console.print(f"   [red]FAIL[/red] Failed to fetch close reasons: {e}")

    # Check 5: Configuration Summary
    checks_total += 1
    console.print("\n[cyan]5. Configuration validation...[/cyan]")
    errors = validate_config(config)
    if not errors:
        console.print("   [green]OK[/green] Configuration is valid")
        checks_passed += 1
    else:
        console.print("   [red]FAIL[/red] Configuration errors:")
        for error in errors:
            console.print(f"      - {error}")

    # Summary
    console.print("\n" + "=" * 60)
    if checks_passed == checks_total:
        console.print(f"[bold green]All checks passed ({checks_passed}/{checks_total})[/bold green]")
        console.print("[green]System is ready for production use[/green]")
    else:
        console.print(f"[bold yellow]Checks: {checks_passed}/{checks_total} passed[/bold yellow]")
        if checks_passed < checks_total // 2:
            console.print("[red]System is NOT ready - fix critical issues first[/red]")
            sys.exit(1)
        else:
            console.print("[yellow]Some checks failed - review warnings above[/yellow]")

    # Show recommended test command
    console.print("\n[cyan]Next steps:[/cyan]")
    console.print("  1. Test with a small batch:")
    console.print("     [bold]python -m src.main run --dry-run --limit 5[/bold]")
    console.print("  2. Run live test with 5-10 vacancies:")
    console.print("     [bold]python -m src.main run --limit 10[/bold]")
    console.print("  3. Run full production batch:")
    console.print("     [bold]python -m src.main run[/bold]")


@cli.command()
@click.argument("run_id")
@click.option("--dry-run", is_flag=True, help="Simulate rollback without making changes")
@click.option("--no-reopen", is_flag=True, help="Don't reopen closed vacancies")
@click.option("--no-close-duplicates", is_flag=True, help="Don't close duplicate vacancies")
@click.option("--config", "config_path", type=click.Path(exists=True), help="Path to config file")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def rollback(
    run_id: str,
    dry_run: bool,
    no_reopen: bool,
    no_close_duplicates: bool,
    config_path: Optional[str],
    verbose: bool,
):
    """Rollback changes from a processing run"""
    _print_banner()
    console.print(f"[yellow]Rolling back run: {run_id}[/yellow]")

    config = _load_and_validate_config(config_path, dry_run=dry_run, verbose=verbose)

    if dry_run:
        console.print(Panel("[yellow]DRY RUN MODE - No actual changes will be made[/yellow]"))

    try:
        result = asyncio.run(
            _run_rollback(
                config, run_id,
                dry_run=dry_run,
                reopen_closed=not no_reopen,
                close_duplicates=not no_close_duplicates,
            )
        )
        _print_rollback_summary(result)
    except KeyboardInterrupt:
        console.print("\n[yellow]Rollback interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if verbose:
            console.print_exception()
        sys.exit(1)


async def _run_rollback(
    config: Config,
    run_id: str,
    dry_run: bool,
    reopen_closed: bool,
    close_duplicates: bool,
):
    state_manager = StateManager(config.state.db_path)
    await state_manager.initialize()

    async with BrightStaffingClient(
        config=config.api,
        dry_run=dry_run,
    ) as client:
        rollback_service = RollbackService(
            client=client,
            state_manager=state_manager,
            dry_run=dry_run,
        )
        return await rollback_service.rollback_run(
            run_id,
            reopen_closed=reopen_closed,
            close_duplicates=close_duplicates,
        )


# --------------------------------------------------------------------------- #
#  Scheduler command (timezone-aware, no manual UTC conversion needed)
# --------------------------------------------------------------------------- #


@cli.command()
@click.option("--config", "config_path", type=click.Path(exists=True), help="Path to config file")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def scheduler(config_path: Optional[str], verbose: bool):
    """Run as a persistent scheduler (timezone-aware, handles DST automatically)"""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    _print_banner()
    config = _load_and_validate_config(config_path, verbose=verbose)

    tz = config.schedule.timezone
    dow_map = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
    day = dow_map.get(config.schedule.day_of_week, "sat")

    console.print(f"[cyan]Schedule:[/cyan] Every {day} at {config.schedule.hour:02d}:{config.schedule.minute:02d} ({tz})")
    console.print("[cyan]DST handling:[/cyan] Automatic (uses timezone-aware scheduling)")
    console.print("[dim]Waiting for next scheduled run...[/dim]\n")

    def run_job():
        console.print(f"\n[bold green]Scheduled run triggered[/bold green]")
        try:
            result = asyncio.run(_run_processor(config, resume_run_id=None))
            _print_result_summary(result)
        except Exception as e:
            console.print(f"[red]Scheduled run failed: {e}[/red]")

    sched = BlockingScheduler()
    sched.add_job(
        run_job,
        CronTrigger(
            day_of_week=day,
            hour=config.schedule.hour,
            minute=config.schedule.minute,
            timezone=tz,
        ),
    )

    try:
        sched.start()
    except KeyboardInterrupt:
        console.print("\n[yellow]Scheduler stopped[/yellow]")


# --------------------------------------------------------------------------- #
#  Entry point
# --------------------------------------------------------------------------- #


def main():
    cli()


if __name__ == "__main__":
    main()
