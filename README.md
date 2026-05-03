# WatchDiff

**Lightweight web change monitoring - clean diffs, structured alerts, no AI required.**

WatchDiff watches web pages and tells you **exactly what changed**, in plain language.  
No noisy HTML diffs. No external services. No AI black boxes.


## Why WatchDiff?

Most change detection tools compare raw HTML - which means every minor script reload or ad rotation triggers a false positive. WatchDiff strips the noise first, then diffs only the content that matters.

- **Deterministic** - same input always produces the same output
- **Human-readable diffs** - "Price changed: $19 → $24", not a wall of HTML
- **Zero external services** - snapshots stored locally as JSON
- **Async-ready** - sync and async schedulers included
- **Configurable** - target any CSS selector, ignore patterns, set webhooks


## Install

```bash
pip install watchdiff-core
```

Or with [uv](https://github.com/astral-sh/uv):

```bash
uv add watchdiff-core
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
# One-shot check
watchdiff check https://example.com --target .price

# Continuous monitoring (Ctrl+C to stop)
watchdiff run https://example.com --target .price --interval 60

# Snapshot history
watchdiff history https://example.com

# Diff reports
watchdiff reports https://example.com

# Clear stored data
watchdiff clear https://example.com
```


## How it works

Every check runs through a fixed pipeline:

```
Fetcher → Cleaner → Parser → DiffEngine → Store → Notifier
```

1. **Fetcher** - downloads the page via `httpx` (sync or async)
2. **Cleaner** - strips scripts, styles, ads, and tracking noise
3. **Parser** - extracts the target CSS selector (or full body)
4. **DiffEngine** - compares content using Python's `difflib.SequenceMatcher`
5. **Store** - persists snapshots and reports as local JSON files
6. **Notifier** - fires callbacks and/or webhooks on detected changes


## API reference

### `WatchDiff`

```python
wd = WatchDiff(storage_dir=".watchdiff")  # default storage directory
```

#### `.watch(url, *, ...)`

Register a URL to monitor. All keyword arguments are optional.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | - | URL to watch |
| `target` | `str \| None` | `None` | CSS selector (e.g. `.price`). `None` = full page |
| `interval` | `int` | `300` | Seconds between checks |
| `label` | `str \| None` | URL | Human-readable name shown in logs |
| `headers` | `dict` | `{}` | Extra HTTP headers |
| `timeout` | `int` | `15` | Request timeout in seconds |
| `ignore_selectors` | `list[str]` | `[]` | CSS selectors to strip before diffing |
| `ignore_patterns` | `list[str]` | `[]` | Regex patterns to strip from text |
| `on_change` | `Callable \| list` | `None` | Callback(s) fired on each change |
| `webhooks` | `list[str]` | `[]` | Webhook URLs to POST on change |
| `min_changes` | `int` | `1` | Minimum number of changes to trigger alert |

All methods are **chainable**:

```python
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

Async variant - use inside an existing event loop (FastAPI, aiohttp, etc.).

```python
import asyncio
asyncio.run(wd.start_async())
```

#### `.check_once(url)`

Run a single immediate check without starting the scheduler loop.

```python
report = wd.check_once("https://example.com")
if report:
    print(report.summary())
```

---

### `DiffReport`

```python
report.url           # str
report.target        # str | None
report.label         # str
report.has_changes   # bool
report.added         # list[Change]
report.removed       # list[Change]
report.modified      # list[Change]
report.changes       # list[Change]  (all changes)
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

change.human()  # "[~] Changed: '$19.00' → '$24.00'"
```

## Webhooks

WatchDiff auto-detects the target service and adapts the payload format:

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

## Async usage

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

## CLI reference

```
Usage: watchdiff [COMMAND] [OPTIONS]

Commands:
  run       Start continuous monitoring
  check     Run a single check and print the result
  history   Show snapshot history for a URL
  reports   Show diff reports for a URL
  clear     Delete all stored data for a URL

Options (shared):
  --target   -t   CSS selector to watch
  --storage  -s   Storage directory (default: .watchdiff)
  --interval -i   Seconds between checks (run only)
  --limit    -n   Number of entries to show (history/reports)
  --verbose  -v   Enable debug logging
  --json         Output raw JSON (check only)
  --yes      -y   Skip confirmation (clear only)
```

## Use cases

- **E-commerce** - track product prices and stock availability
- **News monitoring** - detect article updates or new publications
- **Documentation** - alert when API docs change
- **Public APIs** - watch JSON endpoints for schema or value changes
- **Compliance** - audit changes on public-facing pages over time


## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).

You are free to use, study, modify, and distribute this software under the terms of the GPL v3.
Any derivative work must also be distributed under the same license.
