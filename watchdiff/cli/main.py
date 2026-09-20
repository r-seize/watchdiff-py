"""
WatchDiff CLI - monitor URLs from the terminal.

Usage:
    watchdiff init                                       # generate watchdiff.config.json
    watchdiff run https://example.com --target .price    # continuous monitoring
    watchdiff run --config watchdiff.config.json         # run from config file
    watchdiff check https://example.com --target .price
    watchdiff diff  https://example.com --target .price  # compare last 2 snapshots
    watchdiff status                                     # show snapshot state per URL
    watchdiff history https://example.com --target .price
    watchdiff reports https://example.com
    watchdiff clear https://example.com
"""

from __future__ import annotations

import json
import logging
import logging.config
from pathlib import Path
from typing import Any

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

_URL_ARG      = typer.Argument(..., help="URL to monitor.")
_TARGET_OPT   = typer.Option(None,    "--target",   "-t", help="CSS selector or XPath to watch.",
                              envvar="WATCHDIFF_TARGET")
_INTERVAL_OPT = typer.Option(300,     "--interval", "-i", help="Seconds between checks.",
                              envvar="WATCHDIFF_INTERVAL")
_STORAGE_OPT  = typer.Option(".watchdiff", "--storage", "-s", help="Storage directory.",
                              envvar="WATCHDIFF_STORAGE")
_LIMIT_OPT    = typer.Option(20,  "--limit", "-n", help="Number of entries to show.")
_VERBOSE_OPT  = typer.Option(False, "--verbose", "-v", help="Enable debug logging.",
                              envvar="WATCHDIFF_VERBOSE")

_CONFIG_FILE  = "watchdiff.config.json"
_VALID_DIFF_MODES = {"line", "semantic", "word", "json", "rss"}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "level":     record.levelname.lower(),
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "name":      record.name,
            "message":   record.getMessage(),
        })


def _setup_logging(verbose: bool, log_format: str = "text") -> None:
    level = logging.DEBUG if verbose else logging.INFO
    if log_format == "json":
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logging.basicConfig(level=level, handlers=[handler], force=True)
    else:
        logging.basicConfig(
            level   = level,
            format  = "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
            datefmt = "%H:%M:%S",
        )


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

def _collect_config_errors(data: dict[str, Any]) -> list[str]:
    """Return a list of validation error strings (empty = valid)."""
    errors: list[str] = []

    watchers = data.get("watchers", [])
    if not isinstance(watchers, list):
        return ["'watchers' must be a list"]

    for i, w in enumerate(watchers):
        prefix = f"watchers[{i}]"

        url = w.get("url", "")
        if not str(url).startswith(("http://", "https://")):
            errors.append(f"{prefix}.url: must start with http:// or https:// (got {url!r})")

        diff_mode = w.get("diff_mode", "line")
        if diff_mode not in _VALID_DIFF_MODES:
            errors.append(
                f"{prefix}.diff_mode: must be one of {', '.join(sorted(_VALID_DIFF_MODES))} "
                f"(got {diff_mode!r})"
            )

        jitter = w.get("jitter", 0.0)
        if isinstance(jitter, (int, float)) and not (0.0 <= float(jitter) <= 1.0):
            errors.append(f"{prefix}.jitter: must be between 0.0 and 1.0 (got {jitter})")

        change_threshold = w.get("change_threshold")
        if change_threshold is not None and isinstance(change_threshold, (int, float)):
            if not (0.0 <= float(change_threshold) <= 1.0):
                errors.append(
                    f"{prefix}.change_threshold: must be between 0.0 and 1.0 "
                    f"(got {change_threshold})"
                )

        for field in (
            "interval", "timeout", "retries", "cooldown",
            "max_snapshots", "webhook_retries",
        ):
            val = w.get(field)
            if val is not None and (not isinstance(val, (int, float)) or float(val) < 0):
                errors.append(f"{prefix}.{field}: must be a non-negative number (got {val!r})")

        for field in ("ignore_selectors", "ignore_patterns", "webhooks", "proxies", "user_agents"):
            val = w.get(field)
            if val is not None and not isinstance(val, list):
                errors.append(f"{prefix}.{field}: must be a list (got {type(val).__name__})")

        headers = w.get("headers")
        if headers is not None and not isinstance(headers, dict):
            errors.append(f"{prefix}.headers: must be an object (got {type(headers).__name__})")

        schedule = w.get("schedule")
        if schedule is not None:
            parts = str(schedule).strip().split()
            if len(parts) != 5:
                errors.append(
                    f"{prefix}.schedule: must be a 5-field cron expression "
                    f"(e.g. '*/5 * * * *') — got {schedule!r}"
                )

        confirm_after = w.get("confirm_after")
        if confirm_after is not None and (not isinstance(confirm_after, (int, float)) or float(confirm_after) < 0):
            errors.append(f"{prefix}.confirm_after: must be a non-negative number (got {confirm_after!r})")

        json_path = w.get("json_path")
        if json_path is not None and not isinstance(json_path, str):
            errors.append(f"{prefix}.json_path: must be a string (got {type(json_path).__name__})")

        watcher_id = w.get("id")
        if watcher_id is not None and not isinstance(watcher_id, str):
            errors.append(f"{prefix}.id: must be a string (got {type(watcher_id).__name__})")

        maintenance_windows = w.get("maintenance_windows")
        if maintenance_windows is not None:
            if not isinstance(maintenance_windows, list):
                errors.append(f"{prefix}.maintenance_windows: must be a list")
            else:
                for j, mw in enumerate(maintenance_windows):
                    if not isinstance(mw, dict):
                        errors.append(f"{prefix}.maintenance_windows[{j}]: must be an object")
                    else:
                        for mw_field in ("from", "to"):
                            if mw_field not in mw:
                                errors.append(f"{prefix}.maintenance_windows[{j}].{mw_field}: required")

        active_between = w.get("active_between")
        if active_between is not None:
            if not isinstance(active_between, dict):
                errors.append(f"{prefix}.active_between: must be an object")
            else:
                for ab_field in ("from", "to"):
                    val = active_between.get(ab_field)
                    if val is None:
                        errors.append(f"{prefix}.active_between.{ab_field}: required (HH:MM)")
                    elif not isinstance(val, str) or len(val.split(":")) != 2:
                        errors.append(f"{prefix}.active_between.{ab_field}: must be HH:MM format")
                days = active_between.get("days")
                if days is not None and not isinstance(days, list):
                    errors.append(f"{prefix}.active_between.days: must be a list of integers 0-6")

        failure_policy = w.get("failure_policy")
        if failure_policy is not None:
            if not isinstance(failure_policy, dict):
                errors.append(f"{prefix}.failure_policy: must be an object")
            else:
                for fp_field in ("consecutive_failures", "recovery_checks"):
                    val = failure_policy.get(fp_field)
                    if val is not None and (not isinstance(val, int) or val < 1):
                        errors.append(f"{prefix}.failure_policy.{fp_field}: must be a positive integer")

    return errors


def _validate_config(data: dict[str, Any], path: Path) -> None:
    """Validate config and exit with errors if invalid (used by run/db commands)."""
    errors = _collect_config_errors(data)
    if errors:
        _exit_with_config_errors(errors, path)


def _exit_with_config_errors(errors: list[str], path: Path) -> None:
    console.print(f"[red]Config validation failed:[/] {path}")
    for err in errors:
        console.print(f"  [red]•[/] {err}")
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command("validate")
def cmd_validate(
    config_file: str  = typer.Argument(_CONFIG_FILE, help="Config file to validate."),
    output_json: bool = typer.Option(False, "--json", help="Output result as JSON."),
    verbose: bool     = _VERBOSE_OPT,
) -> None:
    """Check a config file for errors without starting any watchers."""
    _setup_logging(verbose)
    path = Path(config_file)
    if not path.exists():
        if output_json:
            print(json.dumps({"valid": False, "errors": [f"File not found: {path}"]}))
        else:
            console.print(f"[red]File not found:[/] {path}")
        raise typer.Exit(1)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        if output_json:
            print(json.dumps({"valid": False, "errors": [f"Invalid JSON: {exc}"]}))
        else:
            console.print(f"[red]Invalid JSON in {path}:[/] {exc}")
        raise typer.Exit(1)
    errors = _collect_config_errors(data)
    count = len(data.get("watchers", []))
    if output_json:
        print(json.dumps({"valid": not errors, "watchers": count, "errors": errors}))
        if errors:
            raise typer.Exit(1)
    elif errors:
        _exit_with_config_errors(errors, path)
    else:
        console.print(f"[green]✓[/] {path} is valid — {count} watcher(s) defined.")


@app.command("init")
def cmd_init(
    output: str = typer.Option(_CONFIG_FILE, "--output", "-o", help="Output config file path."),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite if file already exists."),
) -> None:
    """Generate a watchdiff.config.json template."""
    dest = Path(output)
    if dest.exists() and not force:
        console.print(f"[yellow]{dest}[/] already exists. Use [bold]--force[/] to overwrite.")
        raise typer.Exit(1)

    template = {
        "storage": ".watchdiff",
        "watchers": [
            {
                "url":                      "https://example.com",
                "target":                   ".price",
                "interval":                 300,
                "label":                    "Example price tracker",
                "diff_mode":                "line",
                "browser":                  False,
                "cooldown":                 0,
                "retries":                  0,
                "retry_delay":              1.0,
                "jitter":                   0.0,
                "dry_run":                  False,
                "max_snapshots":            None,
                "change_threshold":         None,
                "ignore_numbers":           False,
                "alert_if_no_change_after": None,
                "webhooks":                 [],
                "webhook_retries":          3,
                "proxies":                  [],
                "user_agents":              [],
                "ignore_selectors":         [],
                "ignore_patterns":          [],
                "timeout":                  15,
                "headers":                  {},
                "schedule":                 None,
                "confirm_after":            None,
                "json_path":               None,
                "email":                    None,
                "id":                       None,
                "maintenance_windows":      [],
                "active_between":           None,
                "failure_policy":           None,
            }
        ],
    }

    dest.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]Created[/] {dest}")
    console.print(
        "Edit the file, then run: [bold cyan]watchdiff run --config "
        f"{dest}[/]\n"
        "[dim]Config is validated on load - invalid fields are reported with clear messages.[/]"
    )


@app.command("run")
def cmd_run(
    url: str | None         = typer.Argument(None, help="URL to monitor (omit when using --config)."),
    target: str | None      = _TARGET_OPT,
    interval: int           = _INTERVAL_OPT,
    storage: str            = _STORAGE_OPT,
    webhook: list[str]      = typer.Option([], "--webhook", "-w", help="Webhook URL (repeatable).",
                                           envvar="WATCHDIFF_WEBHOOK"),
    verbose: bool           = _VERBOSE_OPT,
    quiet: bool             = typer.Option(False, "--quiet", "-q", help="Suppress change output.",
                                           envvar="WATCHDIFF_QUIET"),
    log_format: str         = typer.Option("text", "--log-format",
                                           help="Log format: text | json.",
                                           envvar="WATCHDIFF_LOG_FORMAT"),
    diff_mode: str          = typer.Option("line", "--diff-mode",
                                           help="Diff mode: line | semantic | word | json.",
                                           envvar="WATCHDIFF_DIFF_MODE"),
    browser: bool           = typer.Option(False, "--browser",
                                           help="Use headless browser (Playwright).",
                                           envvar="WATCHDIFF_BROWSER"),
    cooldown: int           = typer.Option(0, "--cooldown",
                                           help="Min seconds between alerts (0 = off).",
                                           envvar="WATCHDIFF_COOLDOWN"),
    dry_run: bool           = typer.Option(False, "--dry-run",
                                           help="Fetch+diff without saving or alerting.",
                                           envvar="WATCHDIFF_DRY_RUN"),
    retries: int            = typer.Option(0, "--retries",
                                           help="HTTP retry attempts on transient errors.",
                                           envvar="WATCHDIFF_RETRIES"),
    jitter: float           = typer.Option(0.0, "--jitter",
                                           help="Interval jitter fraction 0.0-1.0.",
                                           envvar="WATCHDIFF_JITTER"),
    max_snapshots: int      = typer.Option(0, "--max-snapshots",
                                           help="Max snapshots to keep (0 = unlimited).",
                                           envvar="WATCHDIFF_MAX_SNAPSHOTS"),
    change_threshold: float = typer.Option(0.0, "--change-threshold",
                                           help="Min change ratio 0.0-1.0 (0 = off).",
                                           envvar="WATCHDIFF_CHANGE_THRESHOLD"),
    ignore_numbers: bool    = typer.Option(False, "--ignore-numbers",
                                           help="Strip digit tokens before diffing.",
                                           envvar="WATCHDIFF_IGNORE_NUMBERS"),
    archive_html: bool      = typer.Option(False, "--archive-html",
                                           help="Save full HTML to disk on every change.",
                                           envvar="WATCHDIFF_ARCHIVE_HTML"),
    screenshot: bool        = typer.Option(False, "--screenshot",
                                           help="Save PNG screenshot on change (requires --browser).",
                                           envvar="WATCHDIFF_SCREENSHOT"),
    spike_window: int       = typer.Option(0, "--spike-window",
                                           help="Change spike detection window in seconds (0 = off).",
                                           envvar="WATCHDIFF_SPIKE_WINDOW"),
    spike_threshold: int    = typer.Option(0, "--spike-threshold",
                                           help="Alert when this many changes occur in spike window.",
                                           envvar="WATCHDIFF_SPIKE_THRESHOLD"),
    status_port: int        = typer.Option(0, "--status-port",
                                           help="Start status HTTP server on this port (0 = off).",
                                           envvar="WATCHDIFF_STATUS_PORT"),
    alert_on_status_change: bool = typer.Option(False, "--alert-on-status-change",
                                           help="Alert when HTTP status code changes.",
                                           envvar="WATCHDIFF_ALERT_ON_STATUS_CHANGE"),
    alert_if_no_change: int = typer.Option(0, "--alert-if-no-change",
                                           help="Fire silence alert after N seconds without change (0 = off).",
                                           envvar="WATCHDIFF_ALERT_IF_NO_CHANGE"),
    proxy: list[str]      = typer.Option([], "--proxy",
                                           help="Proxy URL (repeatable).",
                                           envvar="WATCHDIFF_PROXY"),
    user_agent: list[str] = typer.Option([], "--user-agent",
                                           help="User-Agent string (repeatable).",
                                           envvar="WATCHDIFF_USER_AGENT"),
    schedule: str | None  = typer.Option(None, "--schedule",
                                           help="5-field cron expression (overrides --interval).",
                                           envvar="WATCHDIFF_SCHEDULE"),
    confirm_after: int    = typer.Option(0, "--confirm-after",
                                           help="Re-fetch after N seconds before confirming change (0 = off).",
                                           envvar="WATCHDIFF_CONFIRM_AFTER"),
    json_path: str | None = typer.Option(None, "--json-path",
                                           help="$.dot.path expression to extract from JSON response before diffing.",
                                           envvar="WATCHDIFF_JSON_PATH"),
    config_file: str | None = typer.Option(None, "--config", "-c",
                                           help="Load watchers from a JSON config file."),
) -> None:
    """Start continuous monitoring of a URL or a config file."""
    _setup_logging(verbose, log_format)

    def _print_report(report: DiffReport) -> None:
        if not quiet:
            _render_report(report)

    if config_file or (url is None and Path(_CONFIG_FILE).exists()):
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
        target                 = target,
        interval               = interval,
        webhooks               = webhook or [],
        diff_mode              = diff_mode,
        browser                = browser,
        cooldown               = cooldown,
        dry_run                = dry_run,
        retries                = retries,
        jitter                 = jitter,
        max_snapshots          = max_snapshots or None,
        change_threshold       = change_threshold or None,
        ignore_numbers         = ignore_numbers,
        archive_html           = archive_html,
        screenshot_on_change   = screenshot,
        change_spike_window      = spike_window or None,
        change_spike_threshold   = spike_threshold or None,
        alert_on_status_change   = alert_on_status_change,
        alert_if_no_change_after = alert_if_no_change or None,
        proxies                  = proxy or [],
        user_agents              = user_agent or [],
        schedule                 = schedule or None,
        confirm_after            = confirm_after or None,
        json_path                = json_path or None,
    )
    wd.on_change(_print_report)

    cooldown_label       = f"{cooldown}s" if cooldown > 0 else "off"
    dry_run_label        = "[yellow]dry-run[/]" if dry_run else "off"
    status_change_label  = "[yellow]on[/]" if alert_on_status_change else "off"
    status_line = ""
    if status_port > 0:
        status_line = f"\nStatus API: [cyan]http://localhost:{status_port}/status[/]"

    console.print(
        Panel(
            f"[bold cyan]WatchDiff[/] monitoring [green]{url}[/]\n"
            f"Target:    [yellow]{target or 'full page'}[/]  "
            f"Interval:  [yellow]{interval}s[/]  "
            f"Jitter:    [yellow]{jitter}[/]\n"
            f"Diff mode: [yellow]{diff_mode}[/]  "
            f"Browser:   [yellow]{browser}[/]  "
            f"Cooldown:  [yellow]{cooldown_label}[/]\n"
            f"Retries:   [yellow]{retries}[/]  "
            f"Dry-run:   {dry_run_label}  "
            f"Status alerts: {status_change_label}"
            f"{status_line}\n"
            f"Press [bold]Ctrl+C[/] to stop.",
            title="WatchDiff",
        )
    )

    if status_port > 0:
        wd.start(block=False)
        wd.start_status_server(port=status_port)
        try:
            while True:
                import time as _time  # noqa: PLC0415
                _time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        wd.start(block=True)


@app.command("compare")
def cmd_compare(
    url_a: str             = typer.Argument(..., help="First URL (treated as 'before')."),
    url_b: str             = typer.Argument(..., help="Second URL (treated as 'after')."),
    target: str | None     = _TARGET_OPT,
    diff_mode: str         = typer.Option("line", "--diff-mode",
                                          help="Diff mode: line | semantic | word | json | rss."),
    browser: bool          = typer.Option(False, "--browser", help="Use headless browser."),
    timeout: int           = typer.Option(15, "--timeout", help="HTTP timeout in seconds."),
    ignore_selector: list[str] = typer.Option([], "--ignore-selector",
                                              help="CSS selector to strip (repeatable)."),
    ignore_pattern: list[str]  = typer.Option([], "--ignore-pattern",
                                              help="Regex pattern to strip (repeatable)."),
    proxy: list[str]           = typer.Option([], "--proxy",
                                              help="Proxy URL (repeatable)."),
    user_agent: list[str]      = typer.Option([], "--user-agent",
                                              help="User-Agent string (repeatable)."),
    output_json: bool      = typer.Option(False, "--json", help="Output raw JSON."),
    verbose: bool          = _VERBOSE_OPT,
) -> None:
    """Fetch two URLs and compare their content."""
    _setup_logging(verbose)

    wd     = WatchDiff()
    report = wd.compare_urls(
        url_a, url_b,
        target           = target,
        diff_mode        = diff_mode,
        browser          = browser,
        timeout          = timeout,
        ignore_selectors = ignore_selector or [],
        ignore_patterns  = ignore_pattern or [],
        proxies          = proxy or [],
        user_agents      = user_agent or [],
    )

    if output_json:
        typer.echo(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        _render_report(report)


@app.command("check")
def cmd_check(
    url: str                = _URL_ARG,
    target: str | None      = _TARGET_OPT,
    storage: str            = _STORAGE_OPT,
    verbose: bool           = _VERBOSE_OPT,
    log_format: str         = typer.Option("text", "--log-format",
                                           help="Log format: text | json.",
                                           envvar="WATCHDIFF_LOG_FORMAT"),
    output_json: bool       = typer.Option(False, "--json", help="Output raw JSON."),
    diff_mode: str          = typer.Option("line", "--diff-mode",
                                           help="Diff mode: line | semantic | word | json.",
                                           envvar="WATCHDIFF_DIFF_MODE"),
    browser: bool           = typer.Option(False, "--browser",
                                           help="Use headless browser.",
                                           envvar="WATCHDIFF_BROWSER"),
    cooldown: int           = typer.Option(0, "--cooldown",
                                           help="Min seconds between alerts (0 = off).",
                                           envvar="WATCHDIFF_COOLDOWN"),
    dry_run: bool           = typer.Option(False, "--dry-run",
                                           help="Fetch+diff without saving or alerting.",
                                           envvar="WATCHDIFF_DRY_RUN"),
    retries: int            = typer.Option(0, "--retries",
                                           help="HTTP retry attempts on transient errors.",
                                           envvar="WATCHDIFF_RETRIES"),
    ignore_numbers: bool    = typer.Option(False, "--ignore-numbers",
                                           help="Strip digit tokens before diffing.",
                                           envvar="WATCHDIFF_IGNORE_NUMBERS"),
    change_threshold: float = typer.Option(0.0, "--change-threshold",
                                           help="Min change ratio (0 = off).",
                                           envvar="WATCHDIFF_CHANGE_THRESHOLD"),
) -> None:
    """Run a single check and print the result."""
    _setup_logging(verbose, log_format)

    wd = WatchDiff(storage_dir=storage)
    wd.watch(
        url,
        target           = target,
        interval         = 0,
        diff_mode        = diff_mode,
        browser          = browser,
        cooldown         = cooldown,
        dry_run          = dry_run,
        retries          = retries,
        ignore_numbers   = ignore_numbers,
        change_threshold = change_threshold or None,
    )

    report = wd.check_once(url)

    if report is None:
        console.print("[yellow]First snapshot captured - nothing to compare yet.[/]")
        raise typer.Exit(0)

    if output_json:
        typer.echo(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        _render_report(report)


@app.command("diff")
def cmd_diff(
    url: str           = _URL_ARG,
    target: str | None = _TARGET_OPT,
    storage: str       = _STORAGE_OPT,
    output_json: bool  = typer.Option(False, "--json", help="Output raw JSON."),
) -> None:
    """Compare the last two stored snapshots for a URL."""
    from watchdiff.diff import DiffEngine
    from watchdiff.models import WatchConfig as _WatchConfig
    from watchdiff.store import Store

    store   = Store(storage)
    history = store.load_history(url, target, limit=2)

    if len(history) < 2:
        console.print(
            "[yellow]Not enough snapshots to compare.[/] "
            "Need at least 2 - run [bold]watchdiff check[/] first."
        )
        raise typer.Exit(0)

    before, after = history[-2], history[-1]
    engine        = DiffEngine()
    report        = engine.compare(before, after, _WatchConfig(url=url, target=target))

    if output_json:
        typer.echo(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        _render_report(report)


@app.command("status")
def cmd_status(
    storage: str            = _STORAGE_OPT,
    config_file: str | None = typer.Option(None, "--config", "-c",
                                            help="Config file to read URLs from."),
    output_json: bool       = typer.Option(False, "--json", help="Output raw JSON."),
) -> None:
    """Show last snapshot info for all watched URLs (reads from config file)."""
    from watchdiff.store import Store

    file_path = Path(config_file) if config_file else Path(_CONFIG_FILE)
    if not file_path.exists():
        console.print(
            f"[yellow]Config file {file_path} not found.[/] "
            "Create one with [bold]watchdiff init[/]."
        )
        raise typer.Exit(1)

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        console.print(f"[red]Failed to read config:[/] {exc}")
        raise typer.Exit(1)

    store    = Store(data.get("storage", storage))
    watchers = data.get("watchers", [])

    if not watchers:
        console.print("[yellow]No watchers defined.[/]")
        raise typer.Exit(0)

    table = Table(title="WatchDiff Status", show_lines=True)
    table.add_column("Label",         style="cyan")
    table.add_column("URL")
    table.add_column("Target",        style="dim")
    table.add_column("Last snapshot", style="green")
    table.add_column("Snapshots",     justify="right")

    rows = []
    for w in watchers:
        url_w    = w["url"]
        target_w = w.get("target")
        label_w  = w.get("label") or url_w
        snaps    = store.load_history(url_w, target_w, limit=9999)
        latest   = snaps[-1] if snaps else None
        rows.append({
            "label":         label_w,
            "url":           url_w,
            "target":        target_w,
            "last_snapshot": latest.captured_at.isoformat() if latest else None,
            "snapshots":     len(snaps),
        })

    if output_json:
        typer.echo(json.dumps(rows, indent=2, ensure_ascii=False))
        return

    for row in rows:
        table.add_row(
            row["label"],
            row["url"],
            row["target"] or "full page",
            row["last_snapshot"][:19].replace("T", " ") if row["last_snapshot"] else "-",
            str(row["snapshots"]),
        )

    console.print(table)


@app.command("history")
def cmd_history(
    url: str           = _URL_ARG,
    target: str | None = _TARGET_OPT,
    storage: str       = _STORAGE_OPT,
    limit: int         = _LIMIT_OPT,
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
    table.add_column("Checksum",    style="dim")
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
    url: str           = _URL_ARG,
    target: str | None = _TARGET_OPT,
    storage: str       = _STORAGE_OPT,
    limit: int         = _LIMIT_OPT,
) -> None:
    """Show diff reports for a URL."""
    from watchdiff.store import Store

    store = Store(storage)
    rpts  = store.load_reports(url, target, limit=limit)

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


@app.command("export")
def cmd_export(
    url: str               = _URL_ARG,
    target: str | None     = _TARGET_OPT,
    storage: str           = _STORAGE_OPT,
    output: str | None     = typer.Option(None, "--output", "-o",
                                          help="Output file path (prints to stdout if omitted)."),
    export_type: str       = typer.Option("reports", "--type",
                                          help="What to export: reports | snapshots."),
    export_format: str     = typer.Option("csv", "--format",
                                          help="Output format: csv | xlsx."),
    limit: int             = typer.Option(500, "--limit", "-n",
                                          help="Max entries to export."),
) -> None:
    """Export snapshot history or diff reports to CSV or XLSX."""
    from watchdiff.exporter import Exporter  # noqa: PLC0415
    from watchdiff.store import Store        # noqa: PLC0415
    from pathlib import Path as _Path        # noqa: PLC0415

    if export_type not in ("reports", "snapshots"):
        console.print("[red]--type must be 'reports' or 'snapshots'[/]")
        raise typer.Exit(1)

    if export_format not in ("csv", "xlsx"):
        console.print("[red]--format must be 'csv' or 'xlsx'[/]")
        raise typer.Exit(1)

    store    = Store(storage)
    exporter = Exporter(store)

    if export_format == "csv":
        if export_type == "reports":
            result = exporter.reports_csv(url, target, limit=limit,
                                          dest=_Path(output) if output else None)
        else:
            result = exporter.snapshots_csv(url, target, limit=limit,
                                            dest=_Path(output) if output else None)
        if not output:
            typer.echo(result)
        else:
            console.print(f"[green]Exported[/] {export_type} to [yellow]{output}[/]")
    else:
        dest = _Path(output) if output else _Path(f"{export_type}.xlsx")
        if export_type == "reports":
            path = exporter.reports_xlsx(url, target, limit=limit, dest=dest)
        else:
            path = exporter.snapshots_xlsx(url, target, limit=limit, dest=dest)
        console.print(f"[green]Exported[/] {export_type} to [yellow]{path}[/]")


@app.command("db")
def cmd_db(
    connection_string: str       = typer.Argument(..., help="DB connection string (sqlite:///app.db, postgresql://..., mysql://...)."),
    table: str                   = typer.Argument(..., help="Table name to monitor."),
    diff_mode: str               = typer.Option("row",  "--diff-mode", "-m",
                                                help="Diff mode: row | schema | aggregate | value.",
                                                envvar="WATCHDIFF_DB_DIFF_MODE"),
    interval: int                = typer.Option(60,     "--interval",  "-i",
                                                help="Seconds between checks.",
                                                envvar="WATCHDIFF_DB_INTERVAL"),
    label: str | None            = typer.Option(None,   "--label",     help="Human-readable name."),
    query: str | None            = typer.Option(None,   "--query",     "-q",
                                                help="Custom SQL query (overrides default SELECT *)."),
    primary_key: list[str]       = typer.Option([],     "--pk",
                                                help="Primary key column (repeatable)."),
    ignore_column: list[str]     = typer.Option([],     "--ignore-column",
                                                help="Column to exclude from diff (repeatable)."),
    threshold: float             = typer.Option(0.0,    "--threshold",
                                                help="Aggregate % threshold to trigger alert (0 = off).",
                                                envvar="WATCHDIFF_DB_THRESHOLD"),
    cooldown: float              = typer.Option(0.0,    "--cooldown",
                                                help="Min seconds between alerts (0 = off).",
                                                envvar="WATCHDIFF_DB_COOLDOWN"),
    dry_run: bool                = typer.Option(False,  "--dry-run",
                                                help="Fetch+diff without saving or alerting.",
                                                envvar="WATCHDIFF_DRY_RUN"),
    max_snapshots: int           = typer.Option(0,      "--max-snapshots",
                                                help="Max snapshots to keep (0 = unlimited).",
                                                envvar="WATCHDIFF_MAX_SNAPSHOTS"),
    webhook: list[str]           = typer.Option([],     "--webhook", "-w",
                                                help="Webhook URL (repeatable).",
                                                envvar="WATCHDIFF_WEBHOOK"),
    storage: str                 = _STORAGE_OPT,
    verbose: bool                = _VERBOSE_OPT,
    output_json: bool            = typer.Option(False, "--json", help="Output change reports as JSON."),
) -> None:
    """Monitor a database table for changes."""
    _setup_logging(verbose)

    def _print_db_report(report: object) -> None:  # report: DbDiffReport
        if output_json:
            typer.echo(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))  # type: ignore[attr-defined]
        else:
            _render_db_report(report)

    wd = WatchDiff(storage_dir=storage)
    wd.watch_db(
        connection_string,
        table,
        diff_mode       = diff_mode,
        interval        = interval,
        label           = label,
        query           = query,
        primary_key     = primary_key or None,
        ignore_columns  = ignore_column or None,
        threshold       = threshold or None,
        cooldown        = cooldown,
        dry_run         = dry_run,
        max_snapshots   = max_snapshots or None,
        webhooks        = webhook or [],
        on_change       = _print_db_report,
    )

    dry_run_label = "[yellow]dry-run[/]" if dry_run else "off"
    console.print(
        Panel(
            f"[bold cyan]WatchDiff DB[/] monitoring [green]{table}[/]\n"
            f"Connection: [yellow]{connection_string}[/]\n"
            f"Mode: [yellow]{diff_mode}[/]  Interval: [yellow]{interval}s[/]  "
            f"Dry-run: {dry_run_label}\n"
            f"Press [bold]Ctrl+C[/] to stop.",
            title="WatchDiff DB",
        )
    )
    wd.start(block=True)


@app.command("clear")
def cmd_clear(
    url: str           = _URL_ARG,
    target: str | None = _TARGET_OPT,
    storage: str       = _STORAGE_OPT,
    yes: bool          = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
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

    _validate_config(data, path)

    storage  = data.get("storage", ".watchdiff")
    watchers = data.get("watchers", [])

    if not watchers:
        console.print("[yellow]No watchers defined in config file.[/]")
        raise typer.Exit(0)

    from watchdiff.models import (  # noqa: PLC0415
        ActiveBetween, BrowserOptions, EmailConfig, FailurePolicy, MaintenanceWindow, SmtpConfig,
    )

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

        email_cfg = None
        raw_email = w.get("email")
        if raw_email:
            raw_smtp = raw_email.get("smtp", {})
            smtp = SmtpConfig(
                host     = raw_smtp.get("host", ""),
                port     = int(raw_smtp.get("port", 587)),
                user     = raw_smtp.get("user", ""),
                password = raw_smtp.get("password", ""),
                secure   = raw_smtp.get("secure"),
            )
            email_cfg = EmailConfig(
                to      = raw_email.get("to", ""),
                smtp    = smtp,
                from_   = raw_email.get("from"),
                subject = raw_email.get("subject"),
            )

        maintenance_windows_cfg = [
            MaintenanceWindow(from_=mw["from"], to=mw["to"])
            for mw in (w.get("maintenance_windows") or [])
        ]

        active_between_cfg = None
        raw_ab = w.get("active_between")
        if raw_ab:
            active_between_cfg = ActiveBetween(
                from_    = raw_ab.get("from", "00:00"),
                to       = raw_ab.get("to", "23:59"),
                days     = raw_ab.get("days"),
                timezone = raw_ab.get("timezone"),
            )

        failure_policy_cfg = None
        raw_fp = w.get("failure_policy")
        if raw_fp:
            failure_policy_cfg = FailurePolicy(
                consecutive_failures = raw_fp.get("consecutive_failures", 3),
                recovery_checks      = raw_fp.get("recovery_checks", 1),
                respect_retry_after  = raw_fp.get("respect_retry_after", False),
            )

        wd.watch(
            w["url"],
            target                   = w.get("target"),
            interval                 = w.get("interval", 300),
            label                    = w.get("label"),
            headers                  = w.get("headers", {}),
            timeout                  = w.get("timeout", 15),
            ignore_selectors         = w.get("ignore_selectors", []),
            ignore_patterns          = w.get("ignore_patterns", []),
            webhooks                 = w.get("webhooks", []),
            webhook_retries          = w.get("webhook_retries", 3),
            diff_mode                = w.get("diff_mode", "line"),
            browser                  = w.get("browser", False),
            browser_options          = bo,
            proxies                  = w.get("proxies", []),
            user_agents              = w.get("user_agents", []),
            cooldown                 = w.get("cooldown", 0),
            retries                  = w.get("retries", 0),
            retry_delay              = w.get("retry_delay", 1.0),
            jitter                   = w.get("jitter", 0.0),
            dry_run                  = w.get("dry_run", False),
            max_snapshots            = w.get("max_snapshots"),
            change_threshold         = w.get("change_threshold"),
            ignore_numbers           = w.get("ignore_numbers", False),
            alert_if_no_change_after = w.get("alert_if_no_change_after"),
            alert_on_status_change   = w.get("alert_on_status_change", False),
            schedule                 = w.get("schedule"),
            confirm_after            = w.get("confirm_after"),
            json_path                = w.get("json_path"),
            email                    = email_cfg,
            id                       = w.get("id"),
            maintenance_windows      = maintenance_windows_cfg or None,
            active_between           = active_between_cfg,
            failure_policy           = failure_policy_cfg,
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


def _render_db_report(report: object) -> None:
    lines = []
    try:
        summary = report.summary()  # type: ignore[attr-defined]
        changes = report.changes    # type: ignore[attr-defined]
    except AttributeError:
        console.print(str(report))
        return

    lines.append(f"[bold]{summary}[/]\n")
    for change in changes[:20]:
        kind = change.kind.value
        if kind == "inserted":
            lines.append(f"  [green][+][/] {change.row}")
        elif kind == "deleted":
            lines.append(f"  [red][-][/] {change.row}")
        elif kind == "updated":
            mods = ", ".join(
                f"{m.column}: {m.before!r} → {m.after!r}"
                for m in (change.modifications or [])
            )
            lines.append(f"  [yellow][~][/] row {change.row_key}: {mods}")
        elif kind == "schema_changed":
            lines.append(f"  [cyan][S][/] {change.column}: {change.context}")
        elif kind == "threshold_exceeded":
            lines.append(f"  [magenta][T][/] {change.context}")
        elif kind == "value_changed":
            lines.append(f"  [yellow][V][/] {change.before!r} → {change.after!r}")

    console.print(Panel("\n".join(lines), title="DB Changes", border_style="yellow"))


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
