# WatchDiff

[![PyPI version](https://img.shields.io/pypi/v/watchdiff-core?color=blue)](https://pypi.org/project/watchdiff-core/)
[![Python versions](https://img.shields.io/pypi/pyversions/watchdiff-core)](https://pypi.org/project/watchdiff-core/)
[![CI](https://github.com/r-seize/watchdiff-py/actions/workflows/ci.yml/badge.svg)](https://github.com/r-seize/watchdiff-py/actions/workflows/ci.yml)
[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0-blue)](https://www.gnu.org/licenses/gpl-3.0)

**Lightweight web change monitoring - clean diffs, structured alerts, no AI required.**

WatchDiff watches web pages and tells you **exactly what changed**, in plain language.  
No noisy HTML diffs. No external services. No AI black boxes.

## At a glance

| What you want | How |
|---|---|
| Monitor a URL for changes | `.watch(url, target=".price", interval=300)` + `.start()` |
| Target a specific element | `target=".price"` (CSS) or `target="//span[@class='p']"` (XPath) |
| Get notified on change | `on_change=lambda r: print(r.summary())` or `webhooks=["https://discord.com/..."]` |
| Render JS-heavy pages | `browser=True` (requires `pip install "watchdiff-core[browser]"`) |
| Avoid notification spam | `cooldown=3600` (min seconds between alerts per URL) |
| Rotate proxies / UAs | `proxies=[...]`, `user_agents=[...]` |
| Diff at paragraph level | `diff_mode="semantic"` |
| Persist to SQLite | `WatchDiff(store=SqliteStore(".watchdiff.db"))` |
| Export history | `.export_reports_csv(url)` / `.export_reports_xlsx(url)` |
| CLI one-liner | `watchdiff run https://example.com --target .price --interval 60` |
| Multi-URL config file | `watchdiff init` then edit `watchdiff.config.json` |

### Quick navigation

- [Install](#install)
- [Quick start](#quick-start)
- [Feature details](#features)
  - [JS-heavy pages (Playwright)](#javascript-pages-with-playwright)
  - [Proxy and User-Agent rotation](#proxy-rotation-and-user-agent-rotation)
  - [Semantic diff mode](#semantic-diff-mode)
  - [XPath selectors](#xpath-selectors)
  - [SQLite storage backend](#sqlite-storage-backend)
  - [CSV and XLSX export](#csv-and-xlsx-export)
  - [Alert cooldown](#cooldown-anti-spam)
  - [Config file](#config-file-workflow-watchdiff-init)
- [API reference](#api-reference)
- [Webhooks](#webhooks)
- [CLI reference](#cli-reference)
- [Use cases](#use-cases)

## Why WatchDiff?

Most change detection tools compare raw HTML — which means every minor script reload or ad rotation triggers a false positive. WatchDiff strips the noise first, then diffs only the content that matters.

- **Deterministic** — same input always produces the same output
- **Human-readable diffs** — "Price changed: $19 → $24", not a wall of HTML
- **Zero external services** — snapshots stored locally (JSON or SQLite)
- **Async-ready** — sync and async schedulers included
- **Python 3.9+** — works on Debian Bullseye, Bookworm, and Trixie


## Install

```bash
pip install watchdiff-core
```

Or with [uv](https://github.com/astral-sh/uv):

```bash
uv add watchdiff-core
```

### Optional extras

```bash
# JavaScript / SPA pages (Playwright headless browser)
pip install "watchdiff-core[browser]"
playwright install chromium

# XLSX export
pip install "watchdiff-core[xlsx]"

# Everything at once
pip install "watchdiff-core[all]"
```

## Quick start

### Python API

```python
from watchdiff import WatchDiff

wd = WatchDiff()

wd.watch(
    "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
    target=".price_color",
    interval=60,
    label="Book price",
    on_change=lambda r: print(r.summary()),
)

wd.start()
```

### CLI

```bash
# Generate a config file
watchdiff init

# Run from config file
watchdiff run --config watchdiff.config.json

# One-shot check
watchdiff check https://example.com --target .price

# Continuous monitoring (Ctrl+C to stop)
watchdiff run https://example.com --target .price --interval 60

# Snapshot history and reports
watchdiff history https://example.com
watchdiff reports https://example.com

# Clear stored data
watchdiff clear https://example.com
```


## Features

### JavaScript pages with Playwright

For pages that render content via JavaScript (SPAs, React, Vue, etc.), use the headless browser mode:

```bash
pip install "watchdiff-core[browser]"
playwright install chromium
```

```python
from watchdiff import WatchDiff
from watchdiff.models import BrowserOptions

wd = WatchDiff()
wd.watch(
    "https://spa.example.com/pricing",
    target=".price",
    browser=True,
    browser_options=BrowserOptions(
        wait_for="networkidle",       # wait until network is quiet
        wait_for_selector=".price",   # also wait for this element to appear
        timeout=30000,                # ms - max wait time
    ),
)
wd.start()
```

`wait_for` accepts:
- `"load"` — default, waits for the `load` event
- `"domcontentloaded"` — faster, waits for DOM only
- `"networkidle"` — waits until no network requests for 500ms


### Proxy rotation and User-Agent rotation

Avoid blocks with automatic rotation on every request:

```python
wd.watch(
    "https://example.com",
    proxies=[
        "http://proxy1.example.com:8080",
        "http://proxy2.example.com:8080",
        "socks5://proxy3.example.com:1080",
    ],
    user_agents=[
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 ...",
    ],
)
```

If `user_agents` is empty, WatchDiff rotates automatically among **4 built-in modern UA strings** (Chrome, Safari, Firefox, Chrome Linux). No configuration required.

Proxies also work in browser mode — Playwright passes the selected proxy to Chromium.


### Semantic diff mode

By default, WatchDiff diffs line by line. In **semantic mode**, it extracts meaningful HTML blocks — `<p>`, `<h1>`-`<h6>`, `<li>`, `<td>`, `<th>`, `<blockquote>` — and diffs those instead. This gives cleaner results on content-heavy pages where a single paragraph change doesn't shift dozens of lines.

```python
wd.watch(
    "https://blog.example.com/article",
    diff_mode="semantic",   # "line" (default) or "semantic"
)
```

If no semantic blocks are found, the engine falls back to line mode automatically.

In the CLI:

```bash
watchdiff check https://blog.example.com/article --diff-mode semantic
watchdiff run   https://blog.example.com/article --diff-mode semantic --interval 3600
```


### XPath selectors

`target` accepts both **CSS selectors** and **XPath expressions**. XPath is detected automatically by a leading `/` or `(`:

```python
# CSS selector (default)
wd.watch("https://example.com", target=".price")
wd.watch("https://example.com", target="#main > h1")

# XPath expressions
wd.watch("https://example.com", target="//div[@class='price']")
wd.watch("https://example.com", target="//table//tr[td[1]='Revenue']/td[2]")
wd.watch("https://example.com", target="(//h2)[1]")         # first <h2> only
wd.watch("https://example.com", target="//p[contains(@class,'intro')]")
```

XPath is implemented via `lxml` (already a dependency — no extra install needed).


### SQLite storage backend

By default, WatchDiff stores data as JSON files. For larger datasets or concurrent access, switch to the built-in SQLite backend — no extra dependencies required:

```python
from watchdiff import WatchDiff
from watchdiff.store import SqliteStore

wd = WatchDiff(store=SqliteStore(".watchdiff.db"))
wd.watch("https://example.com").start()
```

`SqliteStore` is a **drop-in replacement** for the default `Store` — same interface, same behaviour. It runs in WAL mode for concurrent-read safety.


### CSV and XLSX export

Export your snapshot history and diff reports to CSV (no dependencies) or XLSX (requires `openpyxl`):

```python
from watchdiff import WatchDiff

wd = WatchDiff()
wd.watch("https://example.com", target=".price")

# CSV - always available, returns the CSV string
csv_text = wd.export_reports_csv("https://example.com", dest="reports.csv")
csv_text = wd.export_snapshots_csv("https://example.com", dest="snapshots.csv")

# XLSX - requires: pip install "watchdiff-core[xlsx]"
path = wd.export_reports_xlsx("https://example.com", dest="reports.xlsx")
path = wd.export_snapshots_xlsx("https://example.com", dest="snapshots.xlsx")
```

All export methods accept:
- `url` — the watched URL
- `target` — CSS/XPath filter (optional, `None` = full page)
- `limit` — max rows to include (default 500)
- `dest` — file path to write (optional for CSV, required for XLSX)


### Cooldown anti-spam

Use `cooldown` to set a minimum delay in seconds between two alerts for the same URL. Useful when a page changes frequently but you don't want to be notified on every single check.

```python
wd.watch(
    "https://news.example.com/live",
    target=".headline",
    interval=30,         # check every 30 seconds
    cooldown=600,        # but alert at most every 10 minutes
    on_change=lambda r: print(r.summary()),
)
```

Important: **changes are still detected and stored** during the cooldown period. Only the alerts (callbacks, webhooks) are suppressed. The full history remains available via `.history()` and `.reports()`.

`cooldown=0` (default) disables the feature — every change triggers an alert immediately.

In the CLI:

```bash
watchdiff run https://news.example.com --interval 30 --cooldown 600
```

In `watchdiff.config.json`:

```json
{
  "url": "https://news.example.com/live",
  "interval": 30,
  "cooldown": 600
}
```


### Config file workflow (`watchdiff init`)

Generate a ready-to-edit config file, then run all your watchers in one command:

```bash
watchdiff init
# Created watchdiff.config.json
```

Edit `watchdiff.config.json`:

```json
{
  "storage": ".watchdiff",
  "watchers": [
    {
      "url": "https://store.example.com/product/42",
      "target": ".price",
      "interval": 300,
      "label": "Product 42 price",
      "diff_mode": "line",
      "browser": false,
      "cooldown": 0,
      "webhooks": ["https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN"],
      "proxies": [],
      "user_agents": [],
      "ignore_selectors": [".cookie-banner", "#ad-container"],
      "ignore_patterns": ["\\d+ views"],
      "timeout": 15,
      "headers": {}
    },
    {
      "url": "https://blog.example.com/changelog",
      "target": "//article//p",
      "interval": 3600,
      "label": "Changelog",
      "diff_mode": "semantic",
      "browser": false,
      "webhooks": []
    }
  ]
}
```

Run:

```bash
# Explicit path
watchdiff run --config watchdiff.config.json

# Auto-discovery: if watchdiff.config.json exists in CWD, this also works
watchdiff run
```


## API reference

### `WatchDiff`

```python
from watchdiff import WatchDiff
from watchdiff.store import SqliteStore

wd = WatchDiff()                              # JSON store in .watchdiff/
wd = WatchDiff(storage_dir="/data/watchdiff") # custom JSON store path
wd = WatchDiff(store=SqliteStore("db.sqlite"))  # SQLite store
```

#### `.watch(url, *, ...)`

Register a URL to monitor. All keyword arguments are optional. Returns `self` (chainable).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | - | URL to watch |
| `target` | `str \| None` | `None` | CSS selector or XPath. `None` = full page |
| `interval` | `int` | `300` | Seconds between checks |
| `label` | `str \| None` | URL | Human-readable name shown in logs |
| `headers` | `dict` | `{}` | Extra HTTP headers |
| `timeout` | `int` | `15` | Request timeout in seconds |
| `ignore_selectors` | `list[str]` | `[]` | CSS selectors to strip before diffing |
| `ignore_patterns` | `list[str]` | `[]` | Regex patterns to strip from text |
| `on_change` | `Callable \| list` | `None` | Callback(s) fired on each change |
| `webhooks` | `list[str]` | `[]` | Webhook URLs to POST on change |
| `min_changes` | `int` | `1` | Minimum number of changes to trigger alert |
| `diff_mode` | `str` | `"line"` | `"line"` or `"semantic"` |
| `browser` | `bool` | `False` | Use Playwright headless browser |
| `browser_options` | `BrowserOptions \| None` | `None` | Fine-tune Playwright behaviour |
| `proxies` | `list[str]` | `[]` | Proxy URLs - one picked randomly per request |
| `user_agents` | `list[str]` | `[]` | UA strings - rotated per request (built-ins used if empty) |
| `cooldown` | `int` | `0` | Min seconds between two alerts for this URL (0 = disabled) |

```python
# Chainable
wd.watch("https://site.com/product", target=".price", interval=300) \
  .watch("https://site.com/stock",   target=".availability") \
  .on_change(lambda r: print(r.summary())) \
  .start()
```

#### `.on_change(callback)`

Register a global callback called whenever **any** watched URL changes.

```python
def handle(report):
    print(report.summary())
    for change in report.changes:
        print(change.human())

wd.on_change(handle)
```

#### `.start(block=True)`

Start the synchronous scheduler. Blocks until `Ctrl+C` by default.  
Pass `block=False` to run in the background (daemon threads).

#### `await .start_async()`

Async variant — use inside an existing event loop (FastAPI, aiohttp, etc.):

```python
import asyncio
from watchdiff import WatchDiff

async def main():
    wd = WatchDiff()
    wd.watch("https://example.com", target="h1", interval=30)
    wd.on_change(lambda r: print(r.summary()))
    await wd.start_async()

asyncio.run(main())
```

#### `.check_once(url)`

Run a single immediate check without starting the scheduler loop:

```python
report = wd.check_once("https://example.com")
if report:
    print(report.summary())
```

#### `.history(url, limit=20)` / `.reports(url, limit=20)` / `.clear(url)`

Access stored data programmatically:

```python
snaps   = wd.history("https://example.com", limit=10)
reports = wd.reports("https://example.com", limit=10)
wd.clear("https://example.com")
```

### `DiffReport`

```python
report.url           # str
report.target        # str | None
report.label         # str
report.has_changes   # bool
report.added         # list[Change]
report.removed       # list[Change]
report.modified      # list[Change]
report.changes       # list[Change]  - all changes
report.compared_at   # datetime

report.summary()     # "[Book price] 1 modified - 2024-01-15 10:30:00 UTC"
report.as_dict()     # JSON-serialisable dict
```

### `Change`

```python
change.kind     # ChangeType.ADDED | REMOVED | MODIFIED | UNCHANGED
change.before   # str | None  - previous value
change.after    # str | None  - new value
change.context  # str | None  - surrounding text hint

change.human()  # "[~] Changed: '$19.00' - '$24.00'"
```

## Webhooks

WatchDiff auto-detects the target service and adapts the payload:

| Service | Detection | Payload |
|---|---|---|
| Discord | `discord.com` in URL | `{"content": "..."}` (2000-char limit) |
| Slack | `hooks.slack.com` in URL | `{"text": "..."}` |
| Custom | anything else | full `report.as_dict()` |

```python
wd.watch(
    "https://example.com",
    webhooks=[
        "https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN",
        "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK",
        "https://your-api.com/watchdiff-hook",
    ],
)
```

## CLI reference

```
Usage: watchdiff [COMMAND] [OPTIONS]

Commands:
  init      Generate a watchdiff.config.json template
  run       Start continuous monitoring (URL or config file)
  check     Run a single check and print the result
  history   Show snapshot history for a URL
  reports   Show diff reports for a URL
  clear     Delete all stored data for a URL

Options for run / check:
  --target      -t   CSS selector or XPath to watch
  --storage     -s   Storage directory (default: .watchdiff)
  --interval    -i   Seconds between checks (run only)
  --config      -c   Path to a watchdiff.config.json file
  --diff-mode        Diff strategy: line (default) | semantic
  --browser          Use headless browser (requires playwright)
  --cooldown         Min seconds between alerts (0 = disabled)
  --verbose     -v   Enable debug logging

Options for history / reports:
  --limit       -n   Number of entries to show (default 20)

Options for clear:
  --yes         -y   Skip confirmation prompt

Options for check:
  --json             Output raw JSON instead of formatted output
```

## Use cases

- **E-commerce** — track product prices and stock availability
- **News monitoring** — detect article updates or new publications
- **Documentation** — alert when API docs or changelogs change
- **Public APIs** — watch JSON endpoints for schema or value changes
- **SPA / React apps** — monitor JS-rendered content with `browser=True`
- **Compliance** — audit changes on public-facing pages over time
- **Research** — collect snapshots for longitudinal content analysis


## Contributing

Missing a feature? Found a bug? Pull requests are welcome on [GitHub](https://github.com/r-seize/watchdiff-py).

If you want a feature that is not yet in the project, open an issue or submit a PR directly - contributions of any size are appreciated.

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).

You are free to use, study, modify, and distribute this software under the terms of the GPL v3.  
Any derivative work must also be distributed under the same license.
