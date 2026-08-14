# WatchDiff

[![PyPI version](https://img.shields.io/pypi/v/watchdiff-core?color=blue)](https://pypi.org/project/watchdiff-core/)
[![Python versions](https://img.shields.io/pypi/pyversions/watchdiff-core)](https://pypi.org/project/watchdiff-core/)
[![CI](https://github.com/r-seize/watchdiff-py/actions/workflows/ci.yml/badge.svg)](https://github.com/r-seize/watchdiff-py/actions/workflows/ci.yml)
[![License: BSD-2-Clause](https://img.shields.io/badge/license-BSD--2--Clause-blue)](LICENSE)

**Lightweight web change monitoring - clean diffs, AI summaries, file/API/SSL monitoring, structured alerts.**

WatchDiff watches web pages, files, APIs, databases, and SSL certificates - then tells you exactly what changed, in plain language or via an AI-generated summary.

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
| Monitor a local file | `.watch_file("/etc/nginx/nginx.conf", interval=30)` |
| Monitor a REST API | `.watch_api("https://api.example.com/prices", expected_status=200)` |
| Track API response time | `track_response_time=True` → `report.response_time_ms` |
| Monitor SSL certificate | `.watch_cert("example.com", warn_days_before_expiry=14)` |
| Alert only on condition | `alert_if=lambda r: any("ERROR" in (c.after or "") for c in r.changes)` |
| Fire checks on a schedule | `schedule="0 9 * * *"` (cron expression) |
| Confirm change before alerting | `confirm_after=30` (flapping detection) |
| Monitor a sitemap for URL changes | `.watch_sitemap("https://example.com/sitemap.xml")` |
| Watch one JSON field only | `json_path="$.data.price"` |
| Monitor authenticated pages | `cookies={"session": "abc123", "csrftoken": "xyz"}` |
| Send email on change | `alert=AlertConfig(email=EmailConfig(to="...", smtp=SmtpConfig(...)))` |
| AI summary of changes | `ai_summary=True, ai_provider=AiProvider(type="gemini", api_key="...")` |
| Customize the AI prompt | `ai_prompt="Summarize in French."` or `ai_prompt=lambda r: ...` |
| Compare two different URLs | `.compare_urls(url_a, url_b)` / `watchdiff compare <urlA> <urlB>` |
| Monitor a database table | `.watch_db("sqlite:///app.db", "orders")` |
| DB diff mode | `diff_mode="row"` \| `"schema"` \| `"aggregate"` \| `"value"` |
| Monitor PostgreSQL / MySQL | `"postgresql://user:pass@host/db"` / `"mysql://user:pass@host/db"` |
| Persist to SQLite | `WatchDiff(store=SqliteStore(".watchdiff.db"))` |
| Export history | `.export_reports_csv(url)` / `.export_reports_xlsx(url)` |
| CLI one-liner | `watchdiff run https://example.com --target .price --interval 60` |
| Compare last two snapshots | `watchdiff diff https://example.com` |
| Multi-URL config file | `watchdiff init` then edit `watchdiff.config.json` |

## Quick navigation

- [Install](#install)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
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
  - [Database monitoring](#database-monitoring)
  - [SQLite storage backend](#sqlite-storage-backend)
  - [CSV and XLSX export](#csv-and-xlsx-export)
  - [Config file](#config-file-workflow)
  - [AI summaries](#ai-summaries)
  - [File monitoring](#file-monitoring)
  - [API monitoring](#api-monitoring)
  - [SSL certificate monitoring](#ssl-certificate-monitoring)
  - [Condition-based alerts](#condition-based-alerts---alert_if)
  - [Cron scheduling](#cron-scheduling)
  - [Flapping detection](#flapping-detection)
  - [Sitemap monitoring](#sitemap-monitoring)
  - [JSON path targeting](#json-path-targeting)
  - [Cookie-based authentication](#cookie-based-authentication)
  - [Email alerts](#email-alerts)
- [API reference](#api-reference)
  - [`.watch()`](#watchurl--)
  - [`.watch_db()`](#watch_dbconnection_string-table--)
  - [`.watch_file()`](#watch_filepath--)
  - [`.watch_api()`](#watch_apiurl--)
  - [`.watch_cert()`](#watch_certhost--port443-warning_days30-)
  - [`.watch_sitemap()`](#watch_sitemapurl--)
  - [`.start()` / `start_async()`](#startblock--startasync)
  - [`.stop()` / pause / resume / status](#stop--pause--resume--status)
  - [`DiffReport`](#diffreport)
  - [`Change`](#change)
  - [`Snapshot`](#snapshot)
  - [`WatcherStatus`](#watcherstatus)
  - [`SilenceInfo`](#silenceinfo)
  - [`AlertConfig`](#alertconfig)
  - [`BrowserOptions`](#browseroptions)
  - [`DbDiffReport`](#dbdiffreport)
  - [`DbChange`](#dbchange)
  - [`DbWatcherStatus`](#dbwatcherstatus)
  - [`SchemaChangeInfo` / `ThresholdInfo`](#schemachangeinfo--thresholdinfo)
- [CLI reference](#cli-reference)
- [Environment variables](#environment-variables)
- [Advanced usage](#advanced-usage)
- [Use cases](#use-cases)

## Why WatchDiff?

Most change detection tools compare raw HTML — which means every minor script reload or ad rotation triggers a false positive. WatchDiff strips the noise first, then diffs only the content that matters.

- **Deterministic** — same input always produces the same output
- **Human-readable diffs** — "Price changed: $19 → $24", not a wall of HTML
- **Zero external services** — snapshots stored locally (JSON or SQLite)
- **Async-ready** — sync and async schedulers included
- **Python 3.9+** — works on Debian Bullseye, Bookworm, and Trixie

## Also available for TypeScript / Node.js

A TypeScript port of this library is available on npm: [watchdiff-core](https://www.npmjs.com/package/watchdiff-core)

```bash
npm install watchdiff-core
```

Same pipeline, same concepts, same diff output - native TypeScript implementation.

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

# PostgreSQL monitoring
pip install "watchdiff-core[postgres]"

# MySQL monitoring
pip install "watchdiff-core[mysql]"

# PostgreSQL + MySQL
pip install "watchdiff-core[db]"

# Everything at once
pip install "watchdiff-core[all]"
```

> **Note:** SQLite monitoring works with zero extra dependencies — it uses Python's built-in `sqlite3` module.

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

### Quick start — Database monitoring

```python
from watchdiff import WatchDiff

wd = WatchDiff()

# SQLite (zero extra deps)
wd.watch_db(
    "sqlite:///app.db",
    "orders",
    diff_mode="row",
    primary_key=["id"],
    interval=30,
    on_change=lambda r: print(r.summary()),
)

# PostgreSQL (requires: pip install "watchdiff-core[postgres]")
wd.watch_db(
    "postgresql://user:pass@localhost/mydb",
    "products",
    diff_mode="aggregate",
    query="SELECT COUNT(*) AS total FROM products",
    threshold=5.0,        # alert only when row count changes by >5%
    on_change=lambda r: print(r.summary()),
)

wd.start()
```

```bash
# CLI — monitor a SQLite table
watchdiff db sqlite:///app.db orders --diff-mode row --pk id --interval 30

# CLI — monitor a Postgres aggregate with a threshold
watchdiff db "postgresql://user:pass@localhost/mydb" products \
    --diff-mode aggregate --query "SELECT COUNT(*) FROM products" \
    --threshold 5
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

## How it works

### Web pipeline

Every web check runs through a fixed pipeline:

```
Fetcher / BrowserFetcher → Cleaner → Parser → DiffEngine → Store → Notifier
```

1. **Fetcher** — downloads the page via `httpx`, with proxy/UA rotation and optional retry
2. **BrowserFetcher** — optional Playwright path for JS-rendered pages
3. **Cleaner** — strips scripts, styles, ads and tracking noise (`beautifulsoup4`)
4. **Parser** — extracts the target CSS selector or XPath expression (or full body)
5. **DiffEngine** — compares content in line, word, semantic, JSON or RSS mode
6. **Store** — persists snapshots and reports as JSON files or SQLite
7. **Notifier** — fires callbacks and webhooks on detected changes

### Database pipeline

Every database check runs through a parallel pipeline:

```
DbFetcher (SQLite / PostgreSQL / MySQL) → DbDiffEngine → Store → callbacks / webhooks
```

1. **DbFetcher** — executes `SELECT * FROM <table>` (or a custom query) via the appropriate driver adapter
2. **DbDiffEngine** — compares snapshots in one of four modes: `row`, `schema`, `aggregate`, or `value`
3. **Store** — serialises the row snapshot to JSON and saves it via the existing `Store` interface
4. **Dispatch** — fires `on_change`, `on_schema_change`, `on_threshold` callbacks and webhooks on detected changes


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

### Database monitoring

Monitor SQLite, PostgreSQL, and MySQL tables for row-level changes, schema changes, aggregate threshold crossings, or single-value changes.

#### Diff modes

| Mode | What it detects | Best for |
|---|---|---|
| `"row"` | Inserted / deleted / updated rows (by PK or full-row hash) | Tables with discrete records |
| `"schema"` | Added / removed columns, type changes, nullability changes | Schema migrations |
| `"aggregate"` | Scalar query value change by % threshold | `COUNT(*)`, `SUM(amount)`, etc. |
| `"value"` | Any change to a single scalar value | Config tables, single-cell queries |

#### Quick examples

```python
from watchdiff import WatchDiff

wd = WatchDiff()

# Row mode — track inserts, deletes, and updates
wd.watch_db(
    "sqlite:///app.db", "orders",
    diff_mode="row",
    primary_key=["id"],
    interval=30,
    alert_on_insert=True,
    alert_on_delete=True,
    alert_on_update=True,
    ignore_columns=["updated_at"],   # skip timestamp columns
    on_change=lambda r: print(r.summary()),
)

# Schema mode — alert on column additions or type changes
wd.watch_db(
    "postgresql://user:pass@localhost/mydb", "products",
    diff_mode="schema",
    on_schema_change=lambda info: print(f"Schema changed: {info.changes}"),
)

# Aggregate mode — alert when COUNT(*) changes by more than 10%
wd.watch_db(
    "mysql://user:pass@localhost/mydb", "events",
    diff_mode="aggregate",
    query="SELECT COUNT(*) AS total FROM events",
    threshold=10.0,
    on_threshold=lambda info: print(
        f"Row count changed {info.change_percent:.1f}% "
        f"({info.previous_value:.0f} → {info.current_value:.0f})"
    ),
)

# Value mode — alert when a config value changes
wd.watch_db(
    "sqlite:///settings.db", "config",
    diff_mode="value",
    query="SELECT value FROM config WHERE key = 'feature_flag'",
    on_change=lambda r: print(r.summary()),
)

wd.start()
```

#### Callbacks

| Callback | Type | When fired |
|---|---|---|
| `on_change` | `Callable[[DbDiffReport], None]` | Any change in any mode |
| `on_schema_change` | `Callable[[SchemaChangeInfo], None]` | Schema change detected (schema mode) |
| `on_threshold` | `Callable[[ThresholdInfo], None]` | Aggregate threshold exceeded |
| `on_error` | `Callable[[Exception, DbWatchConfig], None]` | Fetch or diff error |

#### Async support

```python
import asyncio
from watchdiff import WatchDiff

async def main():
    wd = WatchDiff()
    wd.watch_db("sqlite:///app.db", "orders", primary_key=["id"],
                on_change=lambda r: print(r.summary()))
    await wd.start_async()

asyncio.run(main())
```

#### CLI

```bash
# Row mode with PK
watchdiff db sqlite:///app.db orders --diff-mode row --pk id --interval 30

# Schema change monitoring
watchdiff db "postgresql://user:pass@localhost/mydb" products --diff-mode schema

# Aggregate with threshold (alert when >5% change)
watchdiff db "mysql://user:pass@localhost/mydb" events \
    --diff-mode aggregate \
    --query "SELECT COUNT(*) FROM events" \
    --threshold 5.0

# Ignore columns, webhook alerts
watchdiff db sqlite:///app.db orders \
    --pk id \
    --ignore-column updated_at \
    --ignore-column created_at \
    --webhook https://discord.com/api/webhooks/...

# Output as JSON
watchdiff db sqlite:///app.db orders --pk id --json
```

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

## AI summaries

Add a natural-language summary to every change alert. WatchDiff sends the diff to your AI provider of choice and attaches the result to `DiffReport.ai_summary`.

### Auto-discovery (recommended)

Set one of the following environment variables - WatchDiff picks it up automatically:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export GEMINI_API_KEY="AIza..."
```

```python
wd.watch("https://example.com/prices", target=".price",
         ai_summary=True,  # provider auto-detected from env
         on_change=lambda r: print(r.ai_summary))
```

Priority order when multiple keys are set: `ANTHROPIC_API_KEY` → `OPENAI_API_KEY` → `GEMINI_API_KEY` / `GOOGLE_AI_API_KEY`.

### Explicit provider

```python
from watchdiff import AiProvider

wd.watch("https://example.com", ai_summary=True,
         ai_provider=AiProvider(type="gemini",    api_key="...", model="gemini-3.1-flash-lite"))
wd.watch("https://example.com", ai_summary=True,
         ai_provider=AiProvider(type="anthropic", api_key="...", model="claude-haiku-4-5-20251001"))
wd.watch("https://example.com", ai_summary=True,
         ai_provider=AiProvider(type="openai",    api_key="...", model="gpt-4o-mini"))
```

### OpenAI-compatible providers (Ollama, Mistral, Groq, ...)

```python
# Local Ollama
AiProvider(type="openai", base_url="http://localhost:11434/v1", model="llama3")

# Mistral
AiProvider(type="openai", api_key="...", base_url="https://api.mistral.ai/v1", model="mistral-small")

# Groq
AiProvider(type="openai", api_key="...", base_url="https://api.groq.com/openai/v1", model="llama3-8b-8192")
```

### Custom function (any provider, any library)

```python
import anthropic

client = anthropic.Anthropic()

wd.watch("https://example.com", ai_summary=True,
         ai_provider=AiProvider(
             type="custom",
             call_ai=lambda prompt: client.messages.create(
                 model="claude-opus-4-7",
                 max_tokens=200,
                 messages=[{"role": "user", "content": prompt}],
             ).content[0].text,
         ))
```

### Custom prompt

Override the default summary template with `ai_prompt` - pass a static string or a callable that receives the `DiffReport` and returns a prompt string.

```python
# Static prompt - replaces the full instruction sent to the AI
wd.watch_file("/tmp/prices.txt", ai_summary=True,
              ai_prompt="Summarize this change in French in one sentence.")

# Dynamic prompt - build the prompt from the diff report
wd.watch("https://example.com/stock", ai_summary=True,
         ai_prompt=lambda r: (
             f"You are monitoring {r.url}. "
             f"Explain in plain English what changed: "
             + ", ".join(c.after or c.before or "" for c in r.changes)
         ))
```

The prompt is sent as-is to the provider - no variable substitution happens automatically. Use the callable form to interpolate any data from the `DiffReport`.

### Built-in providers

| Provider | `type` | Default model |
|---|---|---|
| Google Gemini | `"gemini"` | `gemini-3.1-flash-lite` |
| Anthropic Claude | `"anthropic"` | `claude-haiku-4-5-20251001` |
| OpenAI / compatible | `"openai"` | `gpt-4o-mini` |
| Any custom function | `"custom"` | - |

### Error handling

AI failures are non-fatal - the watcher keeps running and fires its normal alerts.

| Error kind | What triggers it | Behaviour |
|---|---|---|
| `invalid_key` | 401 / 403 | AI disabled for this watcher for the rest of the session |
| `quota_exceeded` | 429 rate limit | Skips AI this check, retries next interval |
| `model_error` | 400 / unknown model | AI disabled - check your `model` value |
| `network_error` | DNS / timeout | Skips this check, retries next interval |

```python
from watchdiff import AiError

try:
    from watchdiff.ai_summarizer import generate_ai_summary
    summary = generate_ai_summary(report, provider)
except AiError as e:
    print(e.kind)          # AiErrorKind.QUOTA_EXCEEDED
    print(e.is_retryable)  # True  - retry next check
    print(e.is_permanent)  # False - don't disable
    print(e.status_code)   # 429
```

## File monitoring

Watch local files or config files for changes using the same diff pipeline as URL monitoring.

```python
wd.watch_file("/etc/nginx/nginx.conf", interval=30, diff_mode="line",
              on_change=lambda r: print("Config changed:", r.changes))

wd.watch_file("/var/log/app.log", interval=5,
              alert_if=lambda r: any("ERROR" in (c.after or "") for c in r.changes))

# With AI summary
wd.watch_file("/tmp/prices.txt", interval=2, ai_summary=True,
              on_change=lambda r: print(r.ai_summary))
```

## API monitoring

`watch_api()` is a convenience wrapper over `watch()` that defaults to JSON diff mode and tracks response time by default.

```python
wd.watch_api("https://api.example.com/v1/prices",
             interval=60,
             expected_status=200,
             on_change=lambda r: print(f"Response time: {r.response_time_ms:.0f}ms, diff: {r.changes}"))
```

`report.response_time_ms` is populated on every check (enabled by default on `watch_api()`).

## SSL certificate monitoring

Alert before a certificate expires or when it is silently replaced (renewal, infrastructure change).

```python
wd.watch_cert("example.com",
              warn_days_before_expiry=30,
              alert_on_expiry=True,
              alert_on_change=True,
              webhooks=["https://discord.com/api/webhooks/..."],
              on_expiry=lambda i: print(f"{i.hostname} expires in {i.days_until_expiry} days"),
              on_change=lambda i: print(f"Cert replaced - new expiry {i.current_valid_to}"))

# Check status
print(wd.get_cert_statuses())
# [CertWatcherStatus(hostname="example.com", days_until_expiry=12, is_expiring_soon=True, ...)]
```

Default options: `port=443`, `interval=86400` (24h), `warn_days_before_expiry=30`.

## Condition-based alerts - alert_if

Suppress alerts unless a custom condition is met. `alert_if` is evaluated after diffing and before dispatching webhooks/callbacks - avoids noisy alerts without sacrificing monitoring coverage.

```python
# Only alert when the price drops below a threshold
wd.watch("https://shop.example.com/product", target=".price",
         alert_if=lambda r: any(
             float((c.after or "0").replace(",", ".").strip("€$ ")) < 25
             for c in r.changes if c.after
         ))

# Only alert on critical log lines
wd.watch_file("/var/log/app.log",
              alert_if=lambda r: any(
                  ("CRITICAL" in (c.after or "") or "FATAL" in (c.after or ""))
                  for c in r.changes
              ))

# Only alert when a JSON API field exceeds a threshold
wd.watch_api("https://api.example.com/stats",
             alert_if=lambda r: any(
                 c.context == "errorRate" and float(c.after or 0) > 5
                 for c in r.changes
             ))
```

## Cron scheduling

Use a 5-field cron expression instead of a fixed interval. The watcher fires at each matching time instead of every N seconds.

```python
# Every day at 9am
wd.watch("https://example.com/prices", schedule="0 9 * * *",
         on_change=lambda r: print("Morning check:", r.changes))

# Every Monday and Friday at 8:30am
wd.watch("https://example.com/report", schedule="30 8 * * 1,5")

# Every 15 minutes during business hours (Mon-Fri, 9am-6pm)
wd.watch("https://api.example.com/stock", schedule="*/15 9-18 * * 1-5")
```

Supported syntax: `*`, specific values, lists (`1,3,5`), ranges (`1-5`), and steps (`*/5`, `1-5/2`). When `schedule` is set, `interval` is ignored.

```python
from watchdiff import next_cron_run
from datetime import datetime

next_run = next_cron_run("0 9 * * *", datetime(2026, 1, 1, 8, 0))
# datetime(2026, 1, 1, 9, 0)
```

## Flapping detection

Re-verify a change before firing alerts. If the content reverts within `confirm_after` seconds, the alert is suppressed.

```python
wd.watch("https://example.com/status",
         confirm_after=30,  # wait 30s then re-check before alerting
         on_change=lambda r: print("Confirmed change:", r.changes))
```

Useful for pages with transient content (A/B tests, live scores, dashboards) where a single-check spike should not trigger an alert.

## Sitemap monitoring

Watch a `sitemap.xml` for added or removed URLs. Handles sitemap index files automatically.

```python
from watchdiff import WatchDiff

wd = WatchDiff()
wd.watch_sitemap(
    "https://example.com/sitemap.xml",
    interval=3600,
    on_added=lambda entries: print("New URLs:", [e.url for e in entries]),
    on_removed=lambda entries: print("Removed:", [e.url for e in entries]),
    on_change=lambda r: print(f"{len(r.added)} added, {len(r.removed)} removed"),
)
wd.start()

# Check status
for s in wd.get_sitemap_statuses():
    print(s.url, s.entry_count, s.changes_count)
```

`SitemapEntry` fields: `url`, `lastmod`, `changefreq`, `priority`.

## JSON path targeting

Extract a specific value from a JSON response before diffing. Only the targeted field is compared.

```python
# Only watch the "price" field, ignore all other fields
wd.watch_api("https://api.example.com/product/42",
             json_path="$.data.price",
             on_change=lambda r: print("Price changed:", r.changes))

# Nested path with array index
wd.watch_api("https://api.example.com/leaderboard",
             json_path="$.entries[0].score")
```

Supports `$`, `.key`, and `[n]` notation. Use standalone:

```python
from watchdiff import extract_json_path

value = extract_json_path('{"data": {"price": 42.5}}', "$.data.price")
# "42.5"
```

## Cookie-based authentication

Pass cookies with every request to monitor pages that require a login session. Cookies are merged into the outgoing `Cookie` header on top of any `headers` you supply.

```python
wd.watch("https://app.example.com/dashboard",
         cookies={"session": "your-session-token", "csrftoken": "your-csrf-token"},
         interval=300,
         on_change=lambda r: print(r.changes))
```

Combine `cookies` with `headers` — the cookie string is appended to any existing `Cookie` header:

```python
wd.watch_api("https://api.example.com/account",
             headers={"Authorization": "Bearer token123"},
             cookies={"_ga": "GA1.1.0000000000.0000000000"},
             json_path="$.balance",
             interval=60)
```

> Tip: copy cookie values from your browser's DevTools → Network tab → Request Headers.

## Email alerts

Send email notifications via SMTP when a change is detected. Uses Python stdlib `smtplib` — no extra dependency required.

```python
from watchdiff import WatchDiff
from watchdiff.models import AlertConfig, EmailConfig, SmtpConfig

wd = WatchDiff()
wd.watch("https://example.com/prices",
         alert=AlertConfig(
             on_change=[],
             webhooks=[],
             min_changes=1,
             email=EmailConfig(
                 to="alerts@example.com",
                 smtp=SmtpConfig(
                     host="smtp.gmail.com",
                     port=465,
                     user="you@gmail.com",
                     password="app-password",
                 ),
             ),
         ))
wd.start()
```

Optional fields: `from_` (defaults to `user@host`), `subject` (defaults to `"[WatchDiff] Change detected: {label}"`). Multiple recipients: `to=["a@x.com", "b@x.com"]`.

Port `465` uses SSL from the start (`SMTP_SSL`). Other ports use `STARTTLS`.

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
| `cookies` | `dict[str, str]` | `{}` | Cookies sent with every request — merged into the `Cookie` header (e.g. `{"session": "abc"}`) |
| `alert` | `AlertConfig \| None` | `None` | Full alert config — use instead of `on_change`/`webhooks` to include email or fine-tune retries |
| `alert_if` | `Callable[[DiffReport], bool] \| None` | `None` | Custom gate - only alert when this function returns `True` |
| `expected_status` | `int \| None` | `None` | Fire `on_error` when actual HTTP status differs from this value |
| `track_response_time` | `bool` | `False` | Record response time in milliseconds in `DiffReport.response_time_ms` |
| `ai_summary` | `bool` | `False` | Generate an AI natural-language summary of detected changes |
| `ai_provider` | `AiProvider \| None` | `None` | AI provider to use. Auto-detected from env vars when `None` |
| `ai_prompt` | `str \| Callable[[DiffReport], str] \| None` | `None` | Custom prompt sent to the AI instead of the default template |
| `schedule` | `str \| None` | `None` | 5-field cron expression. Overrides `interval` when set. |
| `confirm_after` | `int \| None` | `None` | Re-verify after N seconds before alerting (flapping detection) |
| `json_path` | `str \| None` | `None` | JSON path expression to extract a sub-value before diffing (e.g. `"$.data.price"`) |

```python
# Chainable
wd.watch("https://site.com/product", target=".price", interval=300) \
  .watch("https://site.com/stock",   target=".availability") \
  .on_change(lambda r: print(r.summary())) \
  .start()
```

#### `.watch_db(connection_string, table, *, ...)`

Register a database table to monitor. Returns `self` (chainable).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `connection_string` | `str` | — | `"sqlite:///app.db"`, `"postgresql://user:pass@host/db"`, `"mysql://user:pass@host/db"` |
| `table` | `str` | — | Table name to watch |
| `diff_mode` | `str` | `"row"` | `"row"` \| `"schema"` \| `"aggregate"` \| `"value"` |
| `interval` | `int` | `300` | Seconds between checks |
| `label` | `str \| None` | `table` | Human-readable name shown in logs |
| `query` | `str \| None` | `None` | Custom SQL; overrides default `SELECT * FROM <table>` |
| `primary_key` | `list[str] \| None` | `None` | Columns used as row identity in `row` mode |
| `ignore_columns` | `list[str] \| None` | `None` | Columns excluded from row comparison |
| `alert_on_insert` | `bool` | `True` | Fire alert when rows are inserted |
| `alert_on_delete` | `bool` | `True` | Fire alert when rows are deleted |
| `alert_on_update` | `bool` | `True` | Fire alert when rows are updated |
| `threshold` | `float \| None` | `None` | Minimum % change to alert in `aggregate` mode (0 = any change) |
| `cooldown` | `float` | `0.0` | Min seconds between two alerts (0 = disabled) |
| `dry_run` | `bool` | `False` | Fetch+diff without saving or dispatching alerts |
| `max_snapshots` | `int \| None` | `None` | Prune history to this many entries after each save |
| `webhooks` | `list[str]` | `[]` | Webhook URLs to POST on change |
| `webhook_retries` | `int` | `3` | Retry attempts per webhook |
| `on_change` | `Callable[[DbDiffReport], None] \| None` | `None` | Called with `DbDiffReport` on any change |
| `on_schema_change` | `Callable[[SchemaChangeInfo], None] \| None` | `None` | Called when a schema change is detected |
| `on_threshold` | `Callable[[ThresholdInfo], None] \| None` | `None` | Called when aggregate threshold is exceeded |
| `on_error` | `Callable[[Exception, DbWatchConfig], None] \| None` | `None` | Called with `(exc, config)` on error |

```python
from watchdiff import WatchDiff

wd = WatchDiff()
wd.watch_db("sqlite:///app.db", "orders",
            diff_mode="row", primary_key=["id"], interval=30,
            ignore_columns=["updated_at"],
            on_change=lambda r: print(r.summary()))
wd.start()
```

#### `.watch_file(path, *, ...)`

Watch a local file for changes. Accepts all the same options as `.watch()` (except browser-related ones). The path is converted to a `file://` URL internally. Content is compared as raw text, bypassing the HTML cleaner.

```python
wd.watch_file("/etc/nginx/nginx.conf", interval=30, diff_mode="line",
              on_change=lambda r: print("Config changed:", r.changes))

wd.watch_file("/var/log/app.log", interval=5,
              alert_if=lambda r: any("ERROR" in (c.after or "") for c in r.changes))

wd.watch_file("/tmp/prices.txt", interval=2, ai_summary=True,
              on_change=lambda r: print(r.ai_summary))
```

#### `.watch_api(url, *, ...)`

Convenience wrapper over `.watch()` pre-configured for JSON API monitoring: sets `diff_mode="json"`, `track_response_time=True`, and `expected_status=200` by default.

```python
wd.watch_api("https://api.example.com/prices",
             interval=60,
             on_change=lambda r: print(f"API changed, responded in {r.response_time_ms:.0f}ms"))

# Alert when response time exceeds 500ms
wd.watch_api("https://api.example.com/health",
             interval=30,
             alert_if=lambda r: (r.response_time_ms or 0) > 500)
```

#### `.watch_cert(host, *, port=443, warning_days=30, ...)`

Monitor an SSL/TLS certificate for expiry and fingerprint changes.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `hostname` | `str` | — | Hostname to connect to |
| `port` | `int` | `443` | TLS port |
| `interval` | `int` | `86400` | Seconds between checks |
| `label` | `str \| None` | `hostname:port` | Human-readable name |
| `warn_days_before_expiry` | `int` | `30` | Days before expiry to start firing `on_expiry` |
| `alert_on_change` | `bool` | `True` | Fire `on_change` when cert fingerprint changes |
| `alert_on_expiry` | `bool` | `True` | Fire `on_expiry` when cert is nearing expiry |
| `on_expiry` | `Callable \| None` | `None` | Called with `CertExpiryInfo` when expiry is approaching |
| `on_change` | `Callable \| None` | `None` | Called with `CertChangeInfo` when fingerprint changes |
| `on_error` | `Callable \| None` | `None` | Called with `(exc, config)` on fetch error |

```python
wd.watch_cert("api.example.com",
              warn_days_before_expiry=14,
              on_expiry=lambda i: print(f"Cert expires in {i.days_until_expiry} days"),
              on_change=lambda i: print("Cert fingerprint changed!", i.current_fingerprint))

statuses = wd.get_cert_statuses()  # list[CertWatcherStatus]
for s in statuses:
    print(s.hostname, s.last_check_at, s.days_until_expiry, s.is_expiring_soon)
```

#### `.watch_sitemap(url, *, ...)`

Monitor a `sitemap.xml` for added or removed URLs. Handles sitemap index files automatically.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | — | URL of the sitemap.xml |
| `interval` | `int` | `3600` | Seconds between checks |
| `label` | `str` | URL | Human-readable name |
| `headers` | `dict` | `{}` | Extra HTTP headers |
| `timeout` | `int` | `15` | HTTP timeout in seconds |
| `on_added` | `Callable \| None` | `None` | Called with `list[SitemapEntry]` when new URLs appear |
| `on_removed` | `Callable \| None` | `None` | Called with `list[SitemapEntry]` when URLs disappear |
| `on_change` | `Callable \| None` | `None` | Called with `SitemapDiffReport` on any change |
| `on_error` | `Callable \| None` | `None` | Called with `Exception` on fetch error |

```python
wd.watch_sitemap(
    "https://example.com/sitemap.xml",
    interval=3600,
    on_added=lambda entries: print("New URLs:", [e.url for e in entries]),
    on_removed=lambda entries: print("Removed:", [e.url for e in entries]),
)

for s in wd.get_sitemap_statuses():
    print(s.url, s.entry_count, s.changes_count, s.last_check_at)
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

#### `.start(block=True)` / `await .start_async()` / `.stop()`

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

Call `.stop()` to stop all running schedulers (URL watchers and DB watchers) when running with `block=False`:

```python
wd.start(block=False)
# ... do other work ...
wd.stop()
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

#### `.pause(url)` / `.resume(url)` / `.status()` / `.db_status()`

Control watchers and inspect their state after `start(block=False)`:

```python
wd.start(block=False)

# URL watchers
wd.pause("https://example.com")
wd.resume("https://example.com")
for s in wd.status():
    print(s.label, s.checks_count, s.changes_count, s.errors_count, s.paused)

# DB watchers
for s in wd.db_status():
    print(s.table, s.diff_mode, s.checks_count, s.changes_count, s.errors_count)
```

#### `.history(url)` / `.reports(url)` / `.clear(url)`

```python
snaps   = wd.history("https://example.com", limit=10)
reports = wd.reports("https://example.com", limit=10)
wd.clear("https://example.com")
```

### `DiffReport`

```python
report.url              # str
report.target           # str | None
report.label            # str
report.has_changes      # bool
report.added            # list[Change]
report.removed          # list[Change]
report.modified         # list[Change]
report.changes          # list[Change] — all changes
report.compared_at      # datetime
report.ai_summary       # str | None — populated when ai_summary=True
report.response_time_ms # float | None — populated when track_response_time=True

report.summary()        # "[Book price] 1 modified - 2024-01-15 10:30:00 UTC"
report.as_dict()        # JSON-serialisable dict
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

### `Snapshot`

```python
snap.url          # str
snap.target       # str | None
snap.content      # str — cleaned plain-text content
snap.raw_html     # str — raw HTML of the extracted zone
snap.captured_at  # datetime — UTC timestamp
snap.checksum     # str — SHA-256 of content

snap.is_identical_to(other)  # bool — compare by checksum
```

### `WatcherStatus`

Returned by `.status()`:

```python
status.url             # str
status.label           # str
status.target          # str | None
status.interval        # int — seconds between checks
status.paused          # bool
status.last_check_at   # datetime | None
status.next_check_at   # datetime | None
status.last_change_at  # datetime | None
status.checks_count    # int
status.changes_count   # int
status.errors_count    # int
status.last_status_code # int — last known HTTP status (0 = unknown)

status.as_dict()       # JSON-serialisable dict
```

### `SilenceInfo`

Passed to the `on_silence` callback:

```python
info.url                      # str
info.label                    # str
info.seconds_since_last_change # float
```

### `AlertConfig`

```python
from watchdiff import AlertConfig

AlertConfig(
    on_change=[lambda r: print(r.summary())],  # list of callbacks
    webhooks=["https://hooks.slack.com/..."],
    min_changes=1,
    webhook_retries=3,
    email=EmailConfig(...),   # optional — requires SmtpConfig
)
```

### `BrowserOptions`

```python
from watchdiff import BrowserOptions

BrowserOptions(
    wait_for="networkidle",     # "load" | "domcontentloaded" | "networkidle"
    wait_for_selector=".price", # wait for CSS selector before capturing
    timeout=30000,              # ms — Playwright page.goto timeout
)
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

### `DbDiffReport`

Returned by `on_change` and `DbDiffEngine.compare()`:

```python
report.connection_string  # str — DB connection string
report.table              # str — table name
report.label              # str — human-readable label
report.diff_mode          # DbDiffMode — mode used for comparison
report.changes            # list[DbChange] — all detected changes
report.before             # DbSnapshot — snapshot before
report.after              # DbSnapshot — snapshot after
report.compared_at        # datetime — UTC timestamp of comparison

report.has_changes        # bool — True if any changes were detected
report.summary()          # str — e.g. "orders: 2 inserted, 1 deleted"
report.as_dict()          # JSON-serialisable dict
```

### `DbChange`

Individual change within a `DbDiffReport`:

```python
change.kind          # DbChangeKind — see values below
change.row           # dict | None — full row (inserted/deleted)
change.row_key       # str | None — serialised PK value
change.modifications # list[RowModification] | None — updated fields
change.column        # str | None — column name (schema mode)
change.before        # Any — value/type before
change.after         # Any — value/type after
change.context       # str | None — human hint (e.g. "column added")
```

`DbChangeKind` values: `"inserted"`, `"deleted"`, `"updated"`, `"schema_changed"`, `"threshold_exceeded"`, `"value_changed"`.

`RowModification` fields: `column` (str), `before` (Any), `after` (Any).

### `DbWatcherStatus`

Returned by `.db_status()`:

```python
from watchdiff import DbWatcherStatus

status.connection_string  # str
status.table              # str
status.label              # str
status.diff_mode          # str — "row", "schema", "aggregate", or "value"
status.interval           # int — seconds between checks
status.paused             # bool
status.last_check_at      # datetime | None
status.next_check_at      # datetime | None
status.last_change_at     # datetime | None
status.checks_count       # int
status.changes_count      # int
status.errors_count       # int

status.as_dict()          # JSON-serialisable dict
```

### `SchemaChangeInfo` / `ThresholdInfo`

Passed to `on_schema_change` and `on_threshold` callbacks respectively:

```python
# SchemaChangeInfo — from on_schema_change
info.connection_string  # str
info.table              # str
info.label              # str
info.changes            # list[DbChange] — schema-related changes only

# ThresholdInfo — from on_threshold
info.connection_string  # str
info.table              # str
info.label              # str
info.previous_value     # float — scalar value before
info.current_value      # float — scalar value after
info.change_percent     # float — percentage change (absolute)
info.threshold          # float — configured threshold
```

### DB helper functions

```python
from watchdiff import (
    make_db_watch_config,  # build a DbWatchConfig from kwargs
    db_snapshot_key,       # stable store key for a (connection, table) pair
    db_has_changes,        # bool — True if a DbDiffReport has any changes
    db_report_summary,     # str — human-readable summary of a DbDiffReport
)

key     = db_snapshot_key("sqlite:///app.db", "orders")   # "db::a3f1c2::orders"
cfg     = make_db_watch_config("sqlite:///app.db", "orders", diff_mode="row")
has     = db_has_changes(report)    # True | False
summary = db_report_summary(report) # "orders: 1 inserted"
```

## CLI reference

```
Commands:
  init      Generate a watchdiff.config.json template
  run       Start continuous monitoring (URL or config file)
  db        Monitor a database table for changes
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

Options for db:
  --diff-mode        -m   row | schema | aggregate | value (default row)
  --interval         -i   Seconds between checks (default 60)
  --label                 Human-readable name for logs
  --query            -q   Custom SQL query (overrides default SELECT *)
  --pk                    Primary key column (repeatable)
  --ignore-column         Column to exclude from diff (repeatable)
  --threshold             Aggregate % threshold to trigger alert (0 = off)
  --cooldown              Min seconds between alerts (0 = off)
  --dry-run               Fetch+diff without saving or alerting
  --max-snapshots         Max snapshots to keep (0 = unlimited)
  --webhook          -w   Webhook URL (repeatable)
  --storage          -s   Storage directory
  --json                  Output change reports as JSON
  --verbose          -v   Enable debug logging

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
| `WATCHDIFF_DB_INTERVAL` | `watchdiff db --interval` | `30` |
| `WATCHDIFF_DB_DIFF_MODE` | `watchdiff db --diff-mode` | `row` |
| `WATCHDIFF_DB_THRESHOLD` | `watchdiff db --threshold` | `5.0` |
| `WATCHDIFF_DB_COOLDOWN` | `watchdiff db --cooldown` | `300` |

```dockerfile
# Docker example
ENV WATCHDIFF_STORAGE=/data/.watchdiff
ENV WATCHDIFF_LOG_FORMAT=json
ENV WATCHDIFF_STATUS_PORT=9090
CMD ["watchdiff", "run", "--config", "/app/watchdiff.config.json"]
```

## Advanced usage

### Use individual pipeline stages

All internal modules are exported and fully typed:

```python
from watchdiff import (
    Fetcher, BrowserFetcher, Cleaner, Parser, DiffEngine,
    Store, SqliteStore, Notifier,
    WatchConfig, Snapshot,
)

config  = WatchConfig(url="https://example.com", target=".price", diff_mode="word")
fetcher = BrowserFetcher() if config.browser else Fetcher()
html    = fetcher.fetch(config)

soup     = Cleaner().clean(html)
snapshot = Parser().extract(soup, config)

store    = Store(".watchdiff")
previous = store.load_latest(config.url, config.target)
if previous:
    report = DiffEngine().compare(previous, snapshot, config)
    print(report.summary())

store.save_snapshot(snapshot)
```

### Custom store implementation

Implement the same interface as `Store` to use your own storage backend:

```python
from watchdiff import WatchDiff, Snapshot, DiffReport

class RedisStore:
    def save_snapshot(self, snapshot: Snapshot) -> None: ...
    def load_latest(self, url: str, target: str | None) -> Snapshot | None: ...
    def load_history(self, url: str, target: str | None, limit: int = 50) -> list[Snapshot]: ...
    def clear_history(self, url: str, target: str | None) -> None: ...
    def save_report(self, report: DiffReport) -> None: ...
    def load_reports(self, url: str, target: str | None, limit: int = 50) -> list[dict]: ...

wd = WatchDiff(store=RedisStore())
wd.watch("https://example.com")
wd.start()
```

### Production-ready config

```python
from watchdiff import WatchDiff, SqliteStore, AlertConfig, EmailConfig, SmtpConfig

wd = WatchDiff(store=SqliteStore(".watchdiff.db"))

wd.watch(
    "https://shop.example.com/product/42",
    target=".price",
    label="Product 42 price",
    interval=120,
    jitter=0.15,
    retries=3,
    retry_delay=2.0,
    cooldown=1800,
    max_snapshots=200,
    change_threshold=0.01,
    diff_mode="word",
    alert_if_no_change_after=604800,   # 1 week silence = page may be broken
    webhooks=[
        "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK",
        "https://ntfy.sh/my-price-monitor",
    ],
    on_error=lambda err, cfg: logger.error({"url": cfg.url, "err": str(err)}),
    on_silence=lambda info: logger.warning(
        f"{info.label} has not changed in {info.seconds_since_last_change / 86400:.1f} days"
    ),
)

wd.start()
```

### Integrate with a server shutdown hook

```python
import signal
from watchdiff import WatchDiff

wd = WatchDiff()
wd.watch("https://example.com")
wd.start(block=False)

signal.signal(signal.SIGTERM, lambda *_: wd.stop())
```


## Use cases

- **Database monitoring** — detect row inserts/deletes/updates, schema migrations, or count threshold crossings
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

This project is licensed under the [BSD 2-Clause License](LICENSE).

Copyright (c) 2026, WatchDiff Contributors. Free to use in open-source and commercial projects.
