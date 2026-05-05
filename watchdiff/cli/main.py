"""
WatchDiff CLI - monitor URLs from the terminal.

Usage:
    watchdiff init                                      # generate watchdiff.config.json
    watchdiff run https://example.com --target .price   # continuous monitoring
    watchdiff run --config watchdiff.config.json        # run from config file
    watchdiff check https://example.com --target .price
    watchdiff history https://example.com --target .price
    watchdiff reports https://example.com
    watchdiff clear https://example.com
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from watchdiff.core import WatchDiff
from watchdiff.models import DiffReport

app = typer.Typer(
    name="watchdiff",
    help="WatchDiff - lightweight web change monitoring.",
    add_completion=False,
)
console = Console()

# ---------------------------------------------------------------------------
# Shared options
# ---------------------------------------------------------------------------

_URL_ARG        = typer.Argument(..., help="URL to monitor.")
_TARGET_OPT     = typer.Option(None, "--target", "-t", help="CSS selector or XPath to watch.")
_INTERVAL_OPT   = typer.Option(300, "--interval", "-i", help="Seconds between checks.")
_STORAGE_OPT    = typer.Option(".watchdiff", "--storage", "-s", help="Storage directory.")
_LIMIT_OPT      = typer.Option(20, "--limit", "-n", help="Number of entries to show.")
_VERBOSE_OPT    = typer.Option(False, "--verbose", "-v", help="Enable debug logging.")

# Default config file name for auto-discovery
_CONFIG_FILE    = "watchdiff.config.json"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command("init")
def cmd_init(
    output: str = typer.Option(_CONFIG_FILE, "--output", "-o", help="Output config file path."),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite if file already exists."),
) -> None:
    """Generate a watchdiff.config.json template."""
    dest = Path(output)
    if dest.exists() and not force:
        console.print(
            f"[yellow]{dest}[/] already exists. Use [bold]--force[/] to overwrite."
        )
        raise typer.Exit(1)

    template = {
        "storage": ".watchdiff",
        "watchers": [
            {
                "url":              "https://example.com",
                "target":           ".price",
                "interval":         300,
                "label":            "Example price tracker",
                "diff_mode":        "line",
                "browser":          False,
                "cooldown":         0,
                "webhooks":         [],
                "proxies":          [],
                "user_agents":      [],
                "ignore_selectors": [],
                "ignore_patterns":  [],
                "timeout":          15,
                "headers":          {},
            }
        ],
    }

    dest.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]Created[/] {dest}")
    console.print(
        "Edit the file, then run: [bold cyan]watchdiff run --config "
        f"{dest}[/]"
    )


@app.command("run")
def cmd_run(
    url: str | None         = typer.Argument(None, help="URL to monitor (omit when using --config)."),
    target: str | None      = _TARGET_OPT,
    interval: int           = _INTERVAL_OPT,
    storage: str            = _STORAGE_OPT,
    webhook: list[str]      = typer.Option([], "--webhook", "-w", help="Webhook URL (repeatable)."),
    verbose: bool           = _VERBOSE_OPT,
    diff_mode: str          = typer.Option("line", "--diff-mode", help="Diff mode: line | semantic."),
    browser: bool           = typer.Option(False, "--browser", help="Use headless browser (Playwright)."),
    cooldown: int           = typer.Option(0, "--cooldown", help="Min seconds between alerts (0 = off)."),
    config_file: str | None = typer.Option(None, "--config", "-c",
                                           help="Load watchers from a config JSON file."),
) -> None:
    """Start continuous monitoring of a URL or a config file."""
    _setup_logging(verbose)

    def _print_report(report: DiffReport) -> None:
        _render_report(report)

    if config_file or (url is None and Path(_CONFIG_FILE).exists()):
        # Run from config file
        file_path = Path(config_file) if config_file else Path(_CONFIG_FILE)
        _run_from_config(file_path, _print_report)
        return

    if url is None:
        console.print(
            "[red]Error:[/] provide a URL or a config file "
            f"([bold]--config[/] or create [bold]{_CONFIG_FILE}[/])."
        )
        raise typer.Exit(1)

    wd = WatchDiff(storage_dir=storage)
    wd.watch(
        url,
        target    = target,
        interval  = interval,
        webhooks  = webhook or [],
        diff_mode = diff_mode,
        browser   = browser,
        cooldown  = cooldown,
    )
    wd.on_change(_print_report)

    cooldown_label = f"{cooldown}s" if cooldown > 0 else "off"
    console.print(
        Panel(
            f"[bold cyan]WatchDiff[/] monitoring [green]{url}[/]\n"
            f"Target:    [yellow]{target or 'full page'}[/]  "
            f"Interval:  [yellow]{interval}s[/]\n"
            f"Diff mode: [yellow]{diff_mode}[/]  "
            f"Browser:   [yellow]{browser}[/]  "
            f"Cooldown:  [yellow]{cooldown_label}[/]\n"
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
    diff_mode: str          = typer.Option("line", "--diff-mode", help="Diff mode: line | semantic."),
    browser: bool           = typer.Option(False, "--browser", help="Use headless browser."),
    cooldown: int           = typer.Option(0, "--cooldown", help="Min seconds between alerts (0 = off)."),
) -> None:
    """Run a single check and print the result."""
    _setup_logging(verbose)

    wd = WatchDiff(storage_dir=storage)
    wd.watch(url, target=target, interval=0, diff_mode=diff_mode, browser=browser, cooldown=cooldown)

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

    store     = Store(storage)
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
    url: str            = _URL_ARG,
    target: str | None  = _TARGET_OPT,
    storage: str        = _STORAGE_OPT,
    limit: int          = _LIMIT_OPT,
) -> None:
    """Show diff reports for a URL."""
    from watchdiff.store import Store

    store   = Store(storage)
    rpts    = store.load_reports(url, target, limit=limit)

    if not rpts:
        console.print("[yellow]No reports found.[/]")
        raise typer.Exit(0)

    for r in reversed(rpts):
        changes = r.get("changes", [])
        console.print(
            Panel(
                "\n".join(
                    f"[{c['kind']}] {c.get('before', '')} -> {c.get('after', '')}"
                    for c in changes[:10]
                ) or "[dim]No changes[/]",
                title=r["compared_at"],
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

def _run_from_config(path: Path, on_change_cb: object) -> None:
    """Load a watchdiff.config.json and start monitoring all watchers."""
    if not path.exists():
        console.print(f"[red]Config file not found:[/] {path}")
        raise typer.Exit(1)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        console.print(f"[red]Failed to read config:[/] {exc}")
        raise typer.Exit(1)

    storage  = data.get("storage", ".watchdiff")
    watchers = data.get("watchers", [])

    if not watchers:
        console.print("[yellow]No watchers defined in config file.[/]")
        raise typer.Exit(0)

    from watchdiff.models import BrowserOptions  # noqa: PLC0415

    wd = WatchDiff(storage_dir=storage)
    for w in watchers:
        bo = None
        if w.get("browser_options"):
            raw_bo = w["browser_options"]
            bo = BrowserOptions(
                wait_for          = raw_bo.get("wait_for", "load"),
                wait_for_selector = raw_bo.get("wait_for_selector"),
                timeout           = raw_bo.get("timeout", 30000),
            )

        wd.watch(
            w["url"],
            target           = w.get("target"),
            interval         = w.get("interval", 300),
            label            = w.get("label"),
            headers          = w.get("headers", {}),
            timeout          = w.get("timeout", 15),
            ignore_selectors = w.get("ignore_selectors", []),
            ignore_patterns  = w.get("ignore_patterns", []),
            webhooks         = w.get("webhooks", []),
            diff_mode        = w.get("diff_mode", "line"),
            browser          = w.get("browser", False),
            browser_options  = bo,
            proxies          = w.get("proxies", []),
            user_agents      = w.get("user_agents", []),
            cooldown         = w.get("cooldown", 0),
        )

    wd.on_change(on_change_cb)  # type: ignore[arg-type]

    count = len(watchers)
    console.print(
        Panel(
            f"[bold cyan]WatchDiff[/] loaded [green]{count}[/] watcher(s) from [yellow]{path}[/]\n"
            f"Storage: [yellow]{storage}[/]\n"
            f"Press [bold]Ctrl+C[/] to stop.",
            title="WatchDiff",
        )
    )
    wd.start(block=True)


def _render_report(report: DiffReport) -> None:
    if not report.has_changes:
        console.print(f"[green]OK[/] {report.summary()}")
        return

    lines = [f"[bold]{report.summary()}[/]\n"]
    for change in report.changes:
        if change.kind.value == "added":
            lines.append(f"  [green][+][/] {change.after}")
        elif change.kind.value == "removed":
            lines.append(f"  [red][-][/] {change.before}")
        elif change.kind.value == "modified":
            lines.append(f"  [yellow][~][/] {change.before} [dim]->[/] {change.after}")

    console.print(Panel("\n".join(lines), title="Changes detected", border_style="yellow"))


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level   = level,
        format  = "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt = "%H:%M:%S",
    )
