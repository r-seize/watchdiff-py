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
| Retry on failure | `retries=3, retry_delay=1.0` |
| Diff at word or paragraph level | `diff_mode="word"` or `diff_mode="semantic"` |
| Diff a JSON endpoint | `diff_mode="json"` |
| Monitor an RSS/Atom feed | `diff_mode="rss"` |
| Skip number-only changes | `ignore_numbers=True` |
| Test without saving | `dry_run=True` |
| Alert if a page stops changing | `alert_if_no_change_after=86400` |
| Limit stored history | `max_snapshots=50` |
| Pause / resume a watcher | `.pause(url)` / `.resume(url)` |
| Live watcher status | `.status()` |
| HTTP status API + Prometheus | `.start_status_server(port=9090)` |
| Archive HTML on change | `archive_html=True` |
| Screenshot on change | `screenshot_on_change=True, browser=True` |
| Detect change spikes | `change_spike_window=60, change_spike_threshold=5` |
| Alert on HTTP status change | `alert_on_status_change=True` (200→503, 503→200, etc.) |
| Compare two different URLs | `.compare_urls(url_a, url_b)` / `watchdiff compare <urlA> <urlB>` |
| Persist to SQLite | `WatchDiff(store=SqliteStore(".watchdiff.db"))` |
| Export history | `.export_reports_csv(url)` / `.export_reports_xlsx(url)` |
| CLI one-liner | `watchdiff run https://example.com --target .price --interval 60` |
| Compare last two snapshots | `watchdiff diff https://example.com` |
| Multi-URL config file | `watchdiff init` then edit `watchdiff.config.json` |

## Quick navigation

- [Install](#install)
- [Quick start](#quick-start)
- [Features](#features)
  - [Diff modes](#diff-modes)
  - [RSS / Atom feeds](#rss--atom-feeds)
  - [JS-heavy pages (Playwright)](#javascript-pages-with-playwright)
  - [Proxy and User-Agent rotation](#proxy-rotation-and-user-agent-rotation)
  - [Retry and backoff](#retry-and-backoff)
  - [Webhooks](#webhooks)
  - [Cooldown anti-spam](#cooldown-anti-spam)
  - [Dry run](#dry-run)
  - [Jitter](#jitter)
  - [Ignore numbers](#ignore-numbers)
  - [Change threshold](#change-threshold)
  - [Max snapshots](#max-snapshots)
  - [Silence detection](#silence-detection)
  - [Error callback](#error-callback)
  - [Pause and resume](#pause-and-resume)
  - [Live status](#live-status)
  - [HTTP status server](#http-status-server)
  - [HTML archiving](#html-archiving)
  - [Screenshot on change](#screenshot-on-change)
  - [Change spike detection](#change-spike-detection)
  - [HTTP status code monitoring](#http-status-code-monitoring)
  - [URL comparison](#url-comparison)
  - [XPath selectors](#xpath-selectors)
  - [SQLite storage backend](#sqlite-storage-backend)
  - [CSV and XLSX export](#csv-and-xlsx-export)
  - [Config file](#config-file-workflow)
- [API reference](#api-reference)
- [CLI reference](#cli-reference)
- [Environment variables](#environment-variables)
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

# Compare last two snapshots
watchdiff diff https://example.com --target .price

# Compare two different URLs
watchdiff compare https://example.com/v1 https://example.com/v2

# Continuous monitoring (Ctrl+C to stop)
watchdiff run https://example.com --target .price --interval 60

# With status server on port 9090
watchdiff run https://example.com --interval 60 --status-port 9090

# Show status from config file
watchdiff status
watchdiff status --json

# Export history / reports
watchdiff export https://example.com                                     # CSV to stdout
watchdiff export https://example.com --output reports.csv               # write to file
watchdiff export https://example.com --type snapshots --output snap.csv # snapshots
watchdiff export https://example.com --format xlsx --output reports.xlsx # XLSX

# Snapshot history and reports
watchdiff history https://example.com
watchdiff reports https://example.com

# Clear stored data
watchdiff clear https://example.com
```

## Features

### Diff modes

WatchDiff supports five diff strategies, set with `diff_mode`:

| Mode | Description | Best for |
|---|---|---|
| `"line"` | Line-by-line diff (default) | Most pages |
| `"semantic"` | Block-level diff on `<p>`, `<h1>`–`<h6>`, `<li>`, `<td>`, `<th>`, `<blockquote>` | Articles, blogs |
| `"word"` | Word-level diff, coalesces replaced words into a single `modified` change | Short text, prices |
| `"json"` | Recursive key-path diff (`price`, `stock.available`); falls back to line if not valid JSON | JSON API endpoints |
| `"rss"` | Item-level diff for RSS 2.0 / Atom feeds (by `guid`/`id`); falls back to line | News feeds, podcasts |

```python
wd.watch("https://example.com/api/product/1", diff_mode="json")
wd.watch("https://blog.example.com/article",  diff_mode="semantic")
wd.watch("https://example.com/product",       diff_mode="word")
wd.watch("https://news.example.com/feed.xml", diff_mode="rss")
```

**JSON diff example** — instead of reporting the raw changed line, WatchDiff reports the exact key path:

```
[~] Changed at 'price': '19.99' -> '24.99'
[+] Added at 'badges.0': 'new'
[-] Removed at 'stock.warehouse_b': '42'
```

In the CLI:

```bash
watchdiff run   https://example.com/api/product --diff-mode json
watchdiff check https://example.com/api/product --diff-mode json
```

### RSS / Atom feeds

Monitor news feeds, podcast feeds, or any syndication format. WatchDiff diffs at the item level — each new, removed, or renamed entry is reported individually:

```python
wd.watch(
    "https://hnrss.org/frontpage",
    diff_mode="rss",
    interval=300,
    on_change=lambda r: print(r.summary()),
)
```

**Supported formats:**
- RSS 2.0 — keyed by `<guid>` (falls back to `<link>` then `<title>`)
- Atom — keyed by `<id>` (falls back to `<link href>` then `<title>`)

Uses Python stdlib `xml.etree.ElementTree` — zero extra dependencies.

```bash
watchdiff run https://hnrss.org/frontpage --diff-mode rss --interval 300
```

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
        wait_for="networkidle",      # wait until network is quiet
        wait_for_selector=".price",  # also wait for this element to appear
        timeout=30000,               # ms - max wait time
    ),
)
wd.start()
```

`wait_for` accepts `"load"` (default), `"domcontentloaded"`, or `"networkidle"`.

Proxies work in browser mode too — Playwright passes the selected proxy to Chromium automatically.

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

If `user_agents` is empty, WatchDiff rotates among 4 built-in modern UA strings (Chrome, Safari, Firefox, Chrome Linux) automatically.

### Retry and backoff

Automatically retry failed requests with exponential backoff. Retried status codes: `429`, `500`, `502`, `503`, `504`. Client errors (4xx, except 429) are never retried.

```python
wd.watch(
    "https://example.com",
    retries=3,       # number of retry attempts
    retry_delay=1.0, # base delay in seconds — doubles each attempt (1s, 2s, 4s)
)
```

Works in both sync and async modes.

### Webhooks

WatchDiff auto-detects the target service and adapts the payload:

| Service | Detection | Notes |
|---|---|---|
| Discord | `discord.com` in URL | `{"content": "..."}`, 2000-char limit |
| Slack | `hooks.slack.com` in URL | `{"text": "..."}`, 3000-char limit |
| Telegram | `api.telegram.org` in URL | `chat_id` extracted from URL query param |
| Microsoft Teams | `outlook.office.com`, `webhook.office.com`, `logic.azure.com` | MessageCard format |
| ntfy.sh | `ntfy.sh` or `ntfy.` in URL | `Title`, `Priority`, `Tags` sent as headers |
| Generic JSON | anything else | Full `report.as_dict()` payload |

```python
wd.watch(
    "https://example.com",
    webhooks=[
        "https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN",
        "https://hooks.slack.com/services/T.../B.../...",
        "https://api.telegram.org/botTOKEN/sendMessage?chat_id=123456",
        "https://ntfy.sh/my-topic",
        "https://your-api.com/hook",
    ],
)
```

**Telegram setup** — append `?chat_id=YOUR_CHAT_ID` to the bot URL:

```python
webhooks=["https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>"]
```

**ntfy.sh setup** — just use your topic URL. Title is set to the watcher label:

```python
webhooks=["https://ntfy.sh/my-watchdiff-alerts"]
```

### Cooldown anti-spam

Set a minimum delay in seconds between two alerts for the same URL. Changes are still detected and stored during the cooldown period — only callbacks and webhooks are suppressed.

```python
wd.watch(
    "https://news.example.com/live",
    target=".headline",
    interval=30,    # check every 30 seconds
    cooldown=600,   # alert at most every 10 minutes
    on_change=lambda r: print(r.summary()),
)
```

`cooldown=0` (default) disables it — every change triggers an alert immediately.

```bash
watchdiff run https://news.example.com --interval 30 --cooldown 600
```

### Dry run

Fetch and diff without saving snapshots, saving reports, or firing webhooks. The `on_change` callback still fires so you can test your setup before going live.

```python
wd.watch(
    "https://example.com",
    dry_run=True,
    on_change=lambda r: print("[DRY RUN]", r.summary()),
)
```

```bash
watchdiff run   https://example.com --dry-run
watchdiff check https://example.com --dry-run
```

### Jitter

Randomise the check interval by a fraction of itself to avoid thundering-herd patterns when many watchers run simultaneously. The effective interval is `interval ± interval * jitter * random`, minimum 1 second.

```python
wd.watch(
    "https://example.com",
    interval=300,
    jitter=0.2,  # ± 20% → effective interval between 240s and 360s
)
```

```bash
watchdiff run https://example.com --interval 300 --jitter 0.2
```

### Ignore numbers

Strip all digit tokens from the content before diffing. Useful when a page has counters, view counts, or timestamps that change constantly but are not relevant to your monitoring.

```python
wd.watch(
    "https://example.com/article",
    ignore_numbers=True,  # "1,234 views" and "42" become invisible to the diff
)
```

```bash
watchdiff run   https://example.com --ignore-numbers
watchdiff check https://example.com --ignore-numbers
```

### Change threshold

Ignore alerts when the ratio of changed content to total content is below a threshold. Useful to filter out minor fluctuations (e.g. a rotating quote widget) while still catching real changes.

```python
wd.watch(
    "https://example.com",
    change_threshold=0.05,  # only alert if at least 5% of content changed
)
```

The ratio is computed as `total_changed_characters / len(content_before)`.

```bash
watchdiff run https://example.com --change-threshold 0.05
```

### Max snapshots

Automatically prune the snapshot history to keep only the most recent N entries after each save. Works with both the JSON store and SqliteStore.

```python
wd.watch(
    "https://example.com",
    max_snapshots=100,  # keep only the last 100 snapshots
)
```

In `watchdiff.config.json`:

```json
{
  "url": "https://example.com",
  "max_snapshots": 100
}
```

### Silence detection

Fire a callback when a page has not changed for N seconds. Useful to detect when a live feed or dashboard has gone stale. The callback fires once per silence period and resets as soon as a change is detected.

```python
from watchdiff.models import SilenceInfo

def on_silence(info: SilenceInfo) -> None:
    print(f"[ALERT] {info.label} has not changed for {info.seconds_since_last_change:.0f}s")

wd.watch(
    "https://live.example.com/feed",
    interval=60,
    alert_if_no_change_after=3600,  # fire if no change for 1 hour
    on_silence=on_silence,
)
```

`SilenceInfo` fields: `url`, `label`, `seconds_since_last_change`.

### Error callback

Receive a callback whenever a fetch fails, without crashing the watcher:

```python
def on_error(exc: Exception, config) -> None:
    print(f"[ERROR] {config.label}: {exc}")

wd.watch(
    "https://example.com",
    retries=3,
    on_error=on_error,
)
```

The callback fires after all retries are exhausted. The watcher continues running on the next interval.

### Pause and resume

Suspend and resume individual watchers at runtime without stopping the scheduler:

```python
wd.watch("https://example.com/product", interval=60, label="product")
wd.watch("https://example.com/news",    interval=30, label="news")

wd.start(block=False)  # must use block=False to keep control of the thread

# Later, from another thread or callback:
wd.pause("https://example.com/product")  # stop checking this URL
wd.resume("https://example.com/product") # resume it
```

Checks are skipped entirely while a watcher is paused. The watcher thread keeps running and will resume on the next interval tick after `resume()` is called.

### Live status

Query the live state of all registered watchers after starting the scheduler:

```python
wd.start(block=False)

statuses = wd.status()
for s in statuses:
    print(s.url, s.checks_count, s.changes_count, s.errors_count, s.paused, s.last_status_code)
```

`WatcherStatus` fields:

| Field | Type | Description |
|---|---|---|
| `url` | `str` | Watched URL |
| `label` | `str` | Human-readable label |
| `target` | `str \| None` | CSS/XPath target |
| `interval` | `int` | Configured interval in seconds |
| `paused` | `bool` | Whether the watcher is currently paused |
| `last_check_at` | `datetime \| None` | Time of the last completed check |
| `next_check_at` | `datetime \| None` | Estimated time of the next check |
| `last_change_at` | `datetime \| None` | Time the last change was detected |
| `checks_count` | `int` | Total checks since start |
| `changes_count` | `int` | Total changes detected since start |
| `errors_count` | `int` | Total fetch/parse errors since start |
| `last_status_code` | `int` | Last HTTP status code (0 = unknown/unreachable) |

Returns an empty list if `.start()` has not been called yet.

### HTTP status server

Start an embedded HTTP server to expose live watcher state and Prometheus metrics. Uses Python stdlib `http.server` — zero extra dependencies.

```python
wd.watch("https://example.com", interval=60)
wd.start(block=False)
wd.start_status_server(port=9090)
```

**Endpoints:**

| Endpoint | Description |
|---|---|
| `GET /health` | Returns `{"status": "ok"}` — suitable for load-balancer health checks |
| `GET /status` | JSON array of `WatcherStatus` for all registered watchers |
| `GET /metrics` | Prometheus text format (scrape with Grafana, Prometheus, etc.) |

**Prometheus metrics exposed per watcher (`url` + `label` labels):**

```
watchdiff_checks_total{url="...",label="..."} 42
watchdiff_changes_total{url="...",label="..."} 3
watchdiff_errors_total{url="...",label="..."} 0
watchdiff_paused{url="...",label="..."} 0
watchdiff_interval_seconds{url="...",label="..."} 300
watchdiff_last_check_timestamp_seconds{url="...",label="..."} 1720000000.0
watchdiff_last_change_timestamp_seconds{url="...",label="..."} 1719999000.0
watchdiff_last_http_status{url="...",label="..."} 200
```

```bash
watchdiff run https://example.com --interval 60 --status-port 9090
# Status API: http://localhost:9090/status
# Metrics:    http://localhost:9090/metrics
```

To stop the server programmatically:

```python
wd.stop_status_server()
```

### HTML archiving

Save the full raw HTML to disk every time a change is detected. Files are stored in `<storage>/.watchdiff/archive/` with a timestamped filename.

```python
wd.watch(
    "https://example.com",
    archive_html=True,
)
```

File naming: `<url_md5_8chars>_<YYYYMMDDTHHMMSS>.html`

Archiving is skipped in `dry_run` mode. Works with both `browser=True` and regular HTTP fetching.

```bash
watchdiff run https://example.com --archive-html
```

### Screenshot on change

Capture a full-page PNG screenshot whenever a change is detected. Requires `browser=True` (Playwright).

```bash
pip install "watchdiff-core[browser]"
playwright install chromium
```

```python
wd.watch(
    "https://example.com/dashboard",
    browser=True,
    screenshot_on_change=True,
)
```

Screenshots are saved next to HTML archives in `<storage>/.watchdiff/archive/` with the same timestamp: `<url_md5_8chars>_<YYYYMMDDTHHMMSS>.png`

```bash
watchdiff run https://example.com --browser --screenshot
```

### Change spike detection

Fire a callback when too many changes happen in a short time window — useful to detect page instability, bot mitigation resets, or CDN cache thrashing.

```python
from watchdiff.models import SpikeInfo

def on_spike(info: SpikeInfo) -> None:
    print(f"[SPIKE] {info.label}: {info.changes_in_window} changes in {info.window_seconds}s")

wd.watch(
    "https://example.com",
    change_spike_window=60,     # rolling window in seconds
    change_spike_threshold=5,   # alert if 5+ changes detected in window
    on_spike=on_spike,
)
```

`SpikeInfo` fields: `url`, `label`, `changes_in_window`, `window_seconds`.

The spike alert fires at most once per window to avoid repeated callbacks.

```bash
watchdiff run https://example.com --spike-window 60 --spike-threshold 5
```

### HTTP status code monitoring

Alert when the HTTP status code of a URL changes — detect outages (200→503), maintenance pages (200→503), or recoveries (503→200) independently of content changes.

```python
from watchdiff import WatchDiff, StatusChangeInfo

def on_status_change(info: StatusChangeInfo) -> None:
    print(f"[STATUS] {info.label}: {info.previous_status} → {info.current_status}")

wd = WatchDiff()
wd.watch(
    "https://example.com",
    interval=60,
    alert_on_status_change=True,          # enable status change detection
    on_status_change=on_status_change,    # optional callback
    webhooks=["https://ntfy.sh/my-alerts"],  # webhook fires on status change too
)
wd.start()
```

**How it works:**
- Status `0` means the URL is unreachable (network error, DNS failure, timeout)
- The first check initialises the baseline — no alert is fired
- Subsequent checks alert only when the code **changes** (e.g. 200 → 503, 503 → 200)
- When `webhooks` are configured, a webhook is sent with `context: "http_status"` in the change payload
- The current status is always visible in `.status()` as `last_status_code` and in the Prometheus metric `watchdiff_last_http_status`

`StatusChangeInfo` fields: `url`, `label`, `previous_status`, `current_status`.

```bash
watchdiff run https://example.com --alert-on-status-change --webhook https://ntfy.sh/my-alerts
```

### URL comparison

Fetch two different URLs and compare their content in one shot — without setting up a watcher or storing snapshots.

```python
wd = WatchDiff()
report = wd.compare_urls(
    "https://example.com/v1/api",
    "https://example.com/v2/api",
    diff_mode="json",
)
print(report.summary())
for change in report.changes:
    print(change.human())
```

From the CLI:

```bash
watchdiff compare https://example.com/v1 https://example.com/v2
watchdiff compare https://staging.example.com https://example.com --diff-mode semantic
watchdiff compare https://a.example.com https://b.example.com --json
```

### XPath selectors

`target` accepts both CSS selectors and XPath expressions. XPath is detected automatically by a leading `/` or `(`:

```python
# CSS selector (default)
wd.watch("https://example.com", target=".price")
wd.watch("https://example.com", target="#main > h1")

# XPath expressions
wd.watch("https://example.com", target="//div[@class='price']")
wd.watch("https://example.com", target="//table//tr[td[1]='Revenue']/td[2]")
wd.watch("https://example.com", target="(//h2)[1]")
wd.watch("https://example.com", target="//p[contains(@class,'intro')]")
```

XPath is implemented via `lxml` (already a dependency — no extra install needed).

### SQLite storage backend

By default, WatchDiff stores snapshots as JSON files. For larger datasets or concurrent access, use the built-in SQLite backend — no extra dependencies required:

```python
from watchdiff import WatchDiff
from watchdiff.store import SqliteStore

wd = WatchDiff(store=SqliteStore(".watchdiff.db"))
wd.watch("https://example.com").start()
```

`SqliteStore` is a drop-in replacement for the default `Store`. It runs in WAL mode for safe concurrent reads. Both stores expose `prune_snapshots(url, target, max)` — used automatically when `max_snapshots` is set.

### CSV and XLSX export

Export snapshot history and diff reports to CSV (no extra deps) or XLSX (requires `openpyxl`):

```python
wd = WatchDiff()
wd.watch("https://example.com", target=".price")

# CSV - returns the CSV string and optionally writes to file
csv_text = wd.export_reports_csv("https://example.com", dest="reports.csv")
csv_text = wd.export_snapshots_csv("https://example.com", dest="snapshots.csv")

# XLSX - requires: pip install "watchdiff-core[xlsx]"
path = wd.export_reports_xlsx("https://example.com", dest="reports.xlsx")
path = wd.export_snapshots_xlsx("https://example.com", dest="snapshots.xlsx")
```

All export methods accept `url`, `target` (optional), `limit` (default 500), and `dest`.

### Config file workflow

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
      "diff_mode": "word",
      "browser": false,
      "cooldown": 0,
      "retries": 3,
      "retry_delay": 1.0,
      "jitter": 0.1,
      "dry_run": false,
      "max_snapshots": 100,
      "change_threshold": null,
      "ignore_numbers": false,
      "alert_if_no_change_after": null,
      "webhooks": ["https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN"],
      "proxies": [],
      "user_agents": [],
      "ignore_selectors": [".cookie-banner", "#ad-container"],
      "ignore_patterns": ["\\d+ views"],
      "timeout": 15,
      "headers": {}
    },
    {
      "url": "https://hnrss.org/frontpage",
      "interval": 300,
      "label": "Hacker News",
      "diff_mode": "rss",
      "webhooks": ["https://ntfy.sh/my-alerts"]
    }
  ]
}
```

Config fields are validated on load — invalid URLs, unknown diff modes, out-of-range values, and wrong types are all caught with clear error messages before any monitoring starts.

```bash
# Explicit path
watchdiff run --config watchdiff.config.json

# Auto-discovery: if watchdiff.config.json exists in CWD
watchdiff run

# Show stored snapshot state for all watchers in the config
watchdiff status
watchdiff status --config watchdiff.config.json
```

## API reference

### `WatchDiff`

```python
from watchdiff import WatchDiff
from watchdiff.store import SqliteStore

wd = WatchDiff()                               # JSON store in .watchdiff/
wd = WatchDiff(storage_dir="/data/watchdiff")  # custom JSON store path
wd = WatchDiff(store=SqliteStore("db.sqlite")) # SQLite store
```

#### `.watch(url, *, ...)`

Register a URL to monitor. All keyword arguments are optional. Returns `self` (chainable).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | — | URL to watch |
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
| `webhook_retries` | `int` | `3` | Retry attempts for failed webhook deliveries (0 = no retry) |
| `diff_mode` | `str` | `"line"` | `"line"` \| `"semantic"` \| `"word"` \| `"json"` \| `"rss"` |
| `browser` | `bool` | `False` | Use Playwright headless browser |
| `browser_options` | `BrowserOptions \| None` | `None` | Fine-tune Playwright behaviour |
| `proxies` | `list[str]` | `[]` | Proxy URLs — one picked randomly per request |
| `user_agents` | `list[str]` | `[]` | UA strings — rotated per request |
| `cooldown` | `int` | `0` | Min seconds between two alerts (0 = disabled) |
| `retries` | `int` | `0` | HTTP retry attempts on transient errors |
| `retry_delay` | `float` | `1.0` | Base delay in seconds for exponential backoff |
| `jitter` | `float` | `0.0` | Interval randomisation fraction 0–1 |
| `dry_run` | `bool` | `False` | Fetch+diff without saving or sending webhooks |
| `max_snapshots` | `int \| None` | `None` | Prune history to this many entries after each save |
| `change_threshold` | `float \| None` | `None` | Min changed/total ratio to trigger alert |
| `ignore_numbers` | `bool` | `False` | Strip digit tokens before diffing |
| `alert_if_no_change_after` | `int \| None` | `None` | Fire `on_silence` if no change for N seconds |
| `on_error` | `Callable \| None` | `None` | Called with `(exc, config)` when fetch fails |
| `on_silence` | `Callable \| None` | `None` | Called with `SilenceInfo` when silence threshold hit |
| `archive_html` | `bool` | `False` | Save full HTML to disk on every change |
| `screenshot_on_change` | `bool` | `False` | Save PNG screenshot on change (requires `browser=True`) |
| `change_spike_window` | `int \| None` | `None` | Spike detection rolling window in seconds |
| `change_spike_threshold` | `int \| None` | `None` | Alert when this many changes occur in the window |
| `on_spike` | `Callable \| None` | `None` | Called with `SpikeInfo` when spike is detected |
| `alert_on_status_change` | `bool` | `False` | Alert when HTTP status code changes (200→503, etc.) |
| `on_status_change` | `Callable \| None` | `None` | Called with `StatusChangeInfo` on status code change |

```python
# Chainable
wd.watch("https://site.com/product", target=".price", interval=300) \
  .watch("https://site.com/stock",   target=".availability") \
  .on_change(lambda r: print(r.summary())) \
  .start()
```

#### `.on_change(callback)`

Register a global callback called whenever any watched URL changes:

```python
def handle(report):
    print(report.summary())
    for change in report.changes:
        print(change.human())

wd.on_change(handle)
```

#### `.start(block=True)` / `await .start_async()`

Start the synchronous scheduler. Blocks until `Ctrl+C` by default. Pass `block=False` to run in daemon threads and keep control of the main thread.

```python
# Async variant
import asyncio

async def main():
    wd = WatchDiff()
    wd.watch("https://example.com", target="h1", interval=30)
    wd.on_change(lambda r: print(r.summary()))
    await wd.start_async()

asyncio.run(main())
```

#### `.check_once(url)`

Run a single immediate check without starting the scheduler loop. Returns `None` on the very first check (baseline captured).

```python
wd.watch("https://example.com", target=".price")
report = wd.check_once("https://example.com")
if report:
    print(report.summary())
```

#### `.compare_urls(url_a, url_b, *, ...)`

Fetch two different URLs and compare them immediately. Does not store snapshots.

```python
report = wd.compare_urls(
    "https://example.com/v1",
    "https://example.com/v2",
    diff_mode="json",
    target=".content",
    browser=False,
    timeout=15,
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url_a` | `str` | — | First URL (treated as "before") |
| `url_b` | `str` | — | Second URL (treated as "after") |
| `target` | `str \| None` | `None` | CSS selector or XPath |
| `diff_mode` | `str` | `"line"` | Diff strategy |
| `browser` | `bool` | `False` | Use Playwright |
| `timeout` | `int` | `15` | HTTP timeout in seconds |
| `headers` | `dict \| None` | `None` | Extra HTTP headers |

#### `.start_status_server(port, host)` / `.stop_status_server()`

Start or stop the embedded HTTP status server:

```python
wd.start(block=False)
wd.start_status_server(port=9090)        # binds to 0.0.0.0:9090
wd.start_status_server(port=9090, host="127.0.0.1")

wd.stop_status_server()
```

#### `.pause(url)` / `.resume(url)` / `.status()`

Control watchers and inspect their state after `start(block=False)`:

```python
wd.start(block=False)
wd.pause("https://example.com")
wd.resume("https://example.com")
for s in wd.status():
    print(s.label, s.checks_count, s.changes_count, s.errors_count, s.paused)
```

#### `.history(url)` / `.reports(url)` / `.clear(url)`

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
report.changes       # list[Change] — all changes
report.compared_at   # datetime

report.summary()     # "[Book price] 1 modified - 2024-01-15 10:30:00 UTC"
report.as_dict()     # JSON-serialisable dict
```

### `Change`

```python
change.kind     # ChangeType.ADDED | REMOVED | MODIFIED | UNCHANGED
change.before   # str | None — previous value
change.after    # str | None — new value
change.context  # str | None — surrounding text hint

change.human()  # "[~] Changed: '$19.00' - '$24.00'"
str(change)     # same as .human()
```

### `SpikeInfo`

```python
info.url               # str
info.label             # str
info.changes_in_window # int — number of changes detected in the window
info.window_seconds    # int — the configured window size
```

### `StatusChangeInfo`

```python
info.url             # str
info.label           # str
info.previous_status # int — HTTP status code before the change (0 = was unreachable)
info.current_status  # int — HTTP status code after the change (0 = now unreachable)
```

### `StatusServer`

```python
from watchdiff import StatusServer

server = StatusServer(get_statuses=wd.status, port=9090)
server.start()
server.stop()
```

## CLI reference

```
Commands:
  init      Generate a watchdiff.config.json template
  run       Start continuous monitoring (URL or config file)
  compare   Fetch two URLs and compare their content
  check     Run a single check and print the result
  diff      Compare the last two stored snapshots for a URL
  export    Export history or reports to CSV or XLSX
  status    Show snapshot state for all watchers in a config file
  history   Show snapshot history for a URL
  reports   Show diff reports for a URL
  clear     Delete all stored data for a URL

Options for run:
  --target           -t   CSS selector or XPath
  --interval         -i   Seconds between checks (default 300)
  --storage          -s   Storage directory (default .watchdiff)
  --config           -c   Path to watchdiff.config.json
  --diff-mode             line | semantic | word | json | rss (default line)
  --browser               Use headless browser (requires playwright)
  --cooldown              Min seconds between alerts (0 = off)
  --dry-run               Fetch+diff without saving or alerting
  --retries               HTTP retry attempts on transient errors
  --jitter                Interval jitter fraction 0.0–1.0
  --max-snapshots         Max snapshots to keep (0 = unlimited)
  --change-threshold      Min change ratio 0.0–1.0 (0 = off)
  --ignore-numbers        Strip digit tokens before diffing
  --archive-html          Save full HTML to disk on every change
  --screenshot            Save PNG screenshot on change (requires --browser)
  --spike-window          Spike detection rolling window in seconds (0 = off)
  --spike-threshold       Number of changes to trigger a spike alert
  --status-port           Start HTTP status server on this port (0 = off)
  --alert-on-status-change  Alert when HTTP status code changes
  --alert-if-no-change    Fire silence alert after N seconds without change (0 = off)
  --proxy                 Proxy URL (repeatable)
  --user-agent            User-Agent string (repeatable)
  --webhook          -w   Webhook URL (repeatable)
  --log-format            Log format: text | json (default text)
  --verbose          -v   Enable debug logging
  --quiet            -q   Suppress change output

Options for compare:
  --target           -t   CSS selector or XPath
  --diff-mode             Diff strategy (default line)
  --browser               Use headless browser
  --timeout               HTTP timeout in seconds (default 15)
  --json                  Output raw JSON
  --verbose          -v   Enable debug logging

Options for check:
  same as run, plus:
  --log-format            Log format: text | json
  --json                  Output raw JSON instead of formatted output

Options for diff:
  --target           -t   CSS selector or XPath
  --storage          -s   Storage directory
  --json                  Output raw JSON

Options for export:
  --type                  What to export: reports | snapshots (default reports)
  --format                Output format: csv | xlsx (default csv)
  --output           -o   Output file path (prints to stdout if omitted)
  --limit            -n   Max entries to export (default 500)

Options for status:
  --storage          -s   Storage directory
  --config           -c   Config file to read URLs from
  --json                  Output raw JSON

Options for history / reports:
  --limit            -n   Number of entries to show (default 20)

Options for clear:
  --yes              -y   Skip confirmation prompt
```

## Environment variables

Every CLI option can be set via environment variable — useful for Docker, CI, and secrets managers.

| Variable | CLI equivalent | Example |
|---|---|---|
| `WATCHDIFF_STORAGE` | `--storage` | `.watchdiff` |
| `WATCHDIFF_WEBHOOK` | `--webhook` | `https://discord.com/api/webhooks/...` |
| `WATCHDIFF_INTERVAL` | `--interval` | `300` |
| `WATCHDIFF_DIFF_MODE` | `--diff-mode` | `word` |
| `WATCHDIFF_BROWSER` | `--browser` | `true` |
| `WATCHDIFF_COOLDOWN` | `--cooldown` | `3600` |
| `WATCHDIFF_DRY_RUN` | `--dry-run` | `true` |
| `WATCHDIFF_RETRIES` | `--retries` | `3` |
| `WATCHDIFF_JITTER` | `--jitter` | `0.2` |
| `WATCHDIFF_MAX_SNAPSHOTS` | `--max-snapshots` | `100` |
| `WATCHDIFF_CHANGE_THRESHOLD` | `--change-threshold` | `0.05` |
| `WATCHDIFF_IGNORE_NUMBERS` | `--ignore-numbers` | `true` |
| `WATCHDIFF_ARCHIVE_HTML` | `--archive-html` | `true` |
| `WATCHDIFF_SCREENSHOT` | `--screenshot` | `true` |
| `WATCHDIFF_SPIKE_WINDOW` | `--spike-window` | `60` |
| `WATCHDIFF_SPIKE_THRESHOLD` | `--spike-threshold` | `5` |
| `WATCHDIFF_STATUS_PORT` | `--status-port` | `9090` |
| `WATCHDIFF_ALERT_ON_STATUS_CHANGE` | `--alert-on-status-change` | `true` |
| `WATCHDIFF_ALERT_IF_NO_CHANGE` | `--alert-if-no-change` | `86400` |
| `WATCHDIFF_PROXY` | `--proxy` | `http://proxy:8080` |
| `WATCHDIFF_USER_AGENT` | `--user-agent` | `MyBot/1.0` |
| `WATCHDIFF_TARGET` | `--target` | `.price` |
| `WATCHDIFF_QUIET` | `--quiet` | `true` |
| `WATCHDIFF_LOG_FORMAT` | `--log-format` | `json` |
| `WATCHDIFF_VERBOSE` | `--verbose` | `true` |

```dockerfile
# Docker example
ENV WATCHDIFF_STORAGE=/data/.watchdiff
ENV WATCHDIFF_LOG_FORMAT=json
ENV WATCHDIFF_STATUS_PORT=9090
CMD ["watchdiff", "run", "--config", "/app/watchdiff.config.json"]
```

## Use cases

- **E-commerce** — track product prices, stock levels, and shipping estimates
- **News monitoring** — detect article updates or new publications on a live feed
- **RSS feeds** — get item-level alerts on new or changed entries with `diff_mode="rss"`
- **API monitoring** — watch JSON endpoints for schema or value changes with `diff_mode="json"`
- **Documentation** — alert when API docs, changelogs, or terms of service change
- **SPA / React apps** — monitor JS-rendered content with `browser=True`
- **Silence detection** — get alerted when a live dashboard or feed stops updating
- **Spike detection** — detect abnormal change rates (CDN issues, A/B tests, cache misses)
- **Compliance** — audit changes on public-facing pages over time, archive HTML evidence
- **Observability** — expose watcher metrics to Prometheus / Grafana via `/metrics`
- **Research** — collect snapshots for longitudinal content analysis

## Contributing

Missing a feature? Found a bug? Pull requests are welcome on [GitHub](https://github.com/r-seize/watchdiff-py).

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).

You are free to use, study, modify, and distribute this software under the terms of the GPL v3.
Any derivative work must also be distributed under the same license.
