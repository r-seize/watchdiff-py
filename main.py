"""
WatchDiff CLI - monitor URLs from the terminal.

Usage:
    watchdiff run https://example.com --target .price --interval 60
    watchdiff check https://example.com --target .price
    watchdiff history https://example.com --target .price
    watchdiff reports https://example.com
    watchdiff clear https://example.com
"""

from __future__ import annotations

import json
import logging

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from watchdiff.core import WatchDiff
from watchdiff.models import DiffReport

app = typer.Typer(
    name            = "watchdiff",
    help            = "WatchDiff - lightweight web change monitoring.",
    add_completion  = False,
)
console = Console()

# ---------------------------------------------------------------------------
# Shared options
# ---------------------------------------------------------------------------

_URL_ARG            = typer.Argument(..., help="URL to monitor.")
_TARGET_OPT         = typer.Option(None, "--target", "-t", help="CSS selector to watch (e.g. .price).")
_INTERVAL_OPT       = typer.Option(300, "--interval", "-i", help="Seconds between checks.")
_STORAGE_OPT        = typer.Option(".watchdiff", "--storage", "-s", help="Storage directory.")
_LIMIT_OPT          = typer.Option(20, "--limit", "-n", help="Number of entries to show.")
_VERBOSE_OPT        = typer.Option(False, "--verbose", "-v", help="Enable debug logging.")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command("run")
def cmd_run(
    url: str                = _URL_ARG,
    target: str | None      = _TARGET_OPT,
    interval: int           = _INTERVAL_OPT,
    storage: str            = _STORAGE_OPT,
    webhook: list[str]      = typer.Option([], "--webhook", "-w", help="Webhook URL (repeatable)."),
    verbose: bool           = _VERBOSE_OPT,
) -> None:
    """Start continuous monitoring of a URL."""
    _setup_logging(verbose)

    def _print_report(report: DiffReport) -> None:
        _render_report(report)

    wd = WatchDiff(storage_dir=storage)
    wd.watch(url, target=target, interval=interval, webhooks=webhook or [])
    wd.on_change(_print_report)

    console.print(
        Panel(
            f"[bold cyan]WatchDiff[/] monitoring [green]{url}[/]\n"
            f"Target: [yellow]{target or 'full page'}[/]  "
            f"Interval: [yellow]{interval}s[/]\n"
            f"Press [bold]Ctrl+C[/] to stop.",
            title="WatchDiff",
        )
    )
    wd.start(block=True)


@app.command("check")
def cmd_check(
    url: str                = _URL_ARG,
    target: str | None      = _TARGET_OPT,
    storage: str            = _STORAGE_OPT,
    verbose: bool           = _VERBOSE_OPT,
    output_json: bool       = typer.Option(False, "--json", help="Output raw JSON."),
) -> None:
    """Run a single check and print the result."""
    _setup_logging(verbose)

    wd = WatchDiff(storage_dir=storage)
    wd.watch(url, target=target, interval=0)

    report = wd.check_once(url)

    if report is None:
        console.print("[yellow]First snapshot captured - nothing to compare yet.[/]")
        raise typer.Exit(0)

    if output_json:
        typer.echo(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        _render_report(report)


@app.command("history")
def cmd_history(
    url: str                = _URL_ARG,
    target: str | None      = _TARGET_OPT,
    storage: str            = _STORAGE_OPT,
    limit: int              = _LIMIT_OPT,
) -> None:
    """Show snapshot history for a URL."""
    from watchdiff.store import Store

    store = Store(storage)
    snapshots = store.load_history(url, target, limit=limit)

    if not snapshots:
        console.print("[yellow]No snapshots found.[/]")
        raise typer.Exit(0)

    table = Table(title=f"Snapshot history - {url}", show_lines=True)
    table.add_column("Captured at", style="cyan")
    table.add_column("Checksum", style="dim")
    table.add_column("Content preview")

    for snap in reversed(snapshots):
        preview = snap.content[:80].replace("\n", " ")
        table.add_row(
            snap.captured_at.strftime("%Y-%m-%d %H:%M:%S"),
            snap.checksum[:8],
            preview,
        )

    console.print(table)


@app.command("reports")
def cmd_reports(
    url: str                = _URL_ARG,
    target: str | None      = _TARGET_OPT,
    storage: str            = _STORAGE_OPT,
    limit: int              = _LIMIT_OPT,
) -> None:
    """Show diff reports for a URL."""
    from watchdiff.store import Store

    store   = Store(storage)
    reports = store.load_reports(url, target, limit=limit)

    if not reports:
        console.print("[yellow]No reports found.[/]")
        raise typer.Exit(0)

    for r in reversed(reports):
        changes = r.get("changes", [])
        console.print(
            Panel(
                "\n".join(
                    f"[{c['kind']}] {c.get('before', '')} → {c.get('after', '')}"
                    for c in changes[:10]
                ) or "[dim]No changes[/]",
                title=r['compared_at'],
                subtitle=f"{len(changes)} change(s)",
            )
        )


@app.command("clear")
def cmd_clear(
    url: str                = _URL_ARG,
    target: str | None      = _TARGET_OPT,
    storage: str            = _STORAGE_OPT,
    yes: bool               = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete all stored snapshots and reports for a URL."""
    if not yes:
        confirmed = typer.confirm(f"Delete all history for {url!r}?")
        if not confirmed:
            raise typer.Abort()

    from watchdiff.store import Store

    store = Store(storage)
    store.clear_history(url, target)
    console.print(f"[green]Done.[/] History cleared for {url}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render_report(report: DiffReport) -> None:
    if not report.has_changes:
        console.print(f"[green]OK[/] {report.summary()}")
        return

    lines = [f"[bold]{report.summary()}[/]\n"]
    for change in report.changes:
        match change.kind.value:
            case "added":
                lines.append(f"  [green][+][/] {change.after}")
            case "removed":
                lines.append(f"  [red][-][/] {change.before}")
            case "modified":
                lines.append(f"  [yellow][~][/] {change.before} [dim]→[/] {change.after}")

    console.print(Panel("\n".join(lines), title="Changes detected", border_style="yellow"))


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )