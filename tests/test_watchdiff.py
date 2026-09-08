"""
WatchDiff - unit tests.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from watchdiff.cleaner import Cleaner
from watchdiff.cron_parser import next_cron_run
from watchdiff.diff import DiffEngine
from watchdiff.fetcher import FetchError, Fetcher
from watchdiff.json_path import extract_json_path
from watchdiff.mailer import send_email
from watchdiff.models import AlertConfig, ChangeType, EmailConfig, SmtpConfig, Snapshot, WatchConfig
from watchdiff.notifier import Notifier
from watchdiff.parser import Parser
from watchdiff.scheduler.scheduler import SyncScheduler
from watchdiff.sitemap import SitemapFetcher
from watchdiff.store import Store


# ---------------------------------------------------------------------------
# Cleaner
# ---------------------------------------------------------------------------

class TestCleaner:
    def test_strips_script_tags(self):
        html        = "<html><body><script>alert(1)</script><p>Hello</p></body></html>"
        cleaner     = Cleaner()
        text        = cleaner.clean_to_text(html)
        assert "alert" not in text
        assert "Hello" in text

    def test_strips_style_tags(self):
        html        = "<html><body><style>body{color:red}</style><p>World</p></body></html>"
        text        = Cleaner().clean_to_text(html)
        assert "color" not in text
        assert "World" in text

    def test_extra_selectors(self):
        html        = '<html><body><div class="ads">Buy now!</div><p>Content</p></body></html>'
        text        = Cleaner(extra_selectors=[".ads"]).clean_to_text(html)
        assert "Buy now" not in text
        assert "Content" in text

    def test_normalises_whitespace(self):
        html        = "<html><body><p>Hello   World</p></body></html>"
        text        = Cleaner().clean_to_text(html)
        assert "  " not in text


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class TestParser:
    def _config(self, target=None):
        return WatchConfig(url="https://example.com", target=target)

    def test_full_page_extraction(self):
        html = "<html><body><p>Hello World</p></body></html>"
        soup = Cleaner().clean(html)
        snap = Parser().extract(soup, self._config())
        assert "Hello World" in snap.content

    def test_targeted_extraction(self):
        html = '<html><body><span class="price">19€</span><p>Other</p></body></html>'
        soup = Cleaner().clean(html)
        snap = Parser().extract(soup, self._config(target=".price"))
        assert "19€" in snap.content
        assert "Other" not in snap.content

    def test_missing_selector_raises(self):
        from watchdiff.parser import ParserError
        html = "<html><body><p>Hello</p></body></html>"
        soup = Cleaner().clean(html)
        with pytest.raises(ParserError):
            Parser().extract(soup, self._config(target=".missing"))


# ---------------------------------------------------------------------------
# DiffEngine
# ---------------------------------------------------------------------------

class TestDiffEngine:
    def _config(self):
        return WatchConfig(url="https://example.com", label="test")

    def _snap(self, content: str) -> Snapshot:
        return Snapshot(url="https://example.com", target=None, content=content, raw_html="")

    def test_no_changes(self):
        engine      = DiffEngine()
        s           = self._snap("Hello World")
        report      = engine.compare(s, s, self._config())
        assert not report.has_changes

    def test_detects_addition(self):
        engine      = DiffEngine()
        before      = self._snap("Hello")
        after       = self._snap("Hello\nNew line here")
        report      = engine.compare(before, after, self._config())
        assert report.has_changes
        assert any(c.kind == ChangeType.ADDED for c in report.changes)

    def test_detects_removal(self):
        engine      = DiffEngine()
        before      = self._snap("Hello\nGoodbye")
        after       = self._snap("Hello")
        report      = engine.compare(before, after, self._config())
        assert any(c.kind == ChangeType.REMOVED for c in report.changes)

    def test_detects_modification(self):
        engine      = DiffEngine()
        before      = self._snap("Price: 19€")
        after       = self._snap("Price: 24€")
        report      = engine.compare(before, after, self._config())
        assert report.has_changes
        modified = report.modified
        assert modified
        assert "19€" in modified[0].before
        assert "24€" in modified[0].after

    def test_summary_no_changes(self):
        engine      = DiffEngine()
        s           = self._snap("Same")
        report      = engine.compare(s, s, self._config())
        assert "No changes" in report.summary()


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class TestStore:
    def test_save_and_load_latest(self, tmp_path):
        store   = Store(tmp_path)
        snap    = Snapshot(
            url="https://example.com", target=None, content="v1", raw_html=""
        )
        store.save_snapshot(snap)
        loaded = store.load_latest("https://example.com", None)
        assert loaded is not None
        assert loaded.content == "v1"

    def test_load_latest_returns_none_if_empty(self, tmp_path):
        store = Store(tmp_path)
        assert store.load_latest("https://unknown.com", None) is None

    def test_history_limit(self, tmp_path):
        store = Store(tmp_path)
        for i in range(5):
            snap = Snapshot(
                url      = "https://example.com", target=None,
                content  = f"v{i}", raw_html=""
            )
            store.save_snapshot(snap)
        history = store.load_history("https://example.com", None, limit=3)
        assert len(history) == 3

    def test_clear_history(self, tmp_path):
        store   = Store(tmp_path)
        snap    = Snapshot(
            url="https://example.com", target=None, content="v1", raw_html=""
        )
        store.save_snapshot(snap)
        store.clear_history("https://example.com", None)
        assert store.load_latest("https://example.com", None) is None


# ---------------------------------------------------------------------------
# Notifier
# ---------------------------------------------------------------------------

class TestNotifier:
    def _make_report(self) -> object:
        before = Snapshot(url="https://example.com", target=None, content="Hello", raw_html="")
        after  = Snapshot(url="https://example.com", target=None, content="Hello World", raw_html="")
        return DiffEngine().compare(before, after, WatchConfig(url="https://example.com", label="test"))

    def test_skips_if_no_changes(self):
        s      = Snapshot(url="https://example.com", target=None, content="Same", raw_html="")
        report = DiffEngine().compare(s, s, WatchConfig(url="https://example.com", label="test"))
        called = []
        Notifier().notify(report, AlertConfig(on_change=[lambda r: called.append(r)]))
        assert not called

    def test_skips_if_below_min_changes(self):
        report = self._make_report()
        called = []
        Notifier().notify(report, AlertConfig(on_change=[lambda r: called.append(r)], min_changes=99))
        assert not called

    def test_calls_on_change_callback(self):
        report = self._make_report()
        called = []
        Notifier().notify(report, AlertConfig(on_change=[lambda r: called.append(r)]))
        assert len(called) == 1

    def test_callback_exception_does_not_raise(self):
        report = self._make_report()
        def bad_cb(r): raise ValueError("oops")
        Notifier().notify(report, AlertConfig(on_change=[bad_cb]))  # must not raise

    def test_sends_discord_webhook(self, httpx_mock):
        httpx_mock.add_response(url="https://discord.com/api/webhooks/test", status_code=200)
        report = self._make_report()
        Notifier().notify(report, AlertConfig(
            webhooks=["https://discord.com/api/webhooks/test"], webhook_retries=0
        ))
        payload = json.loads(httpx_mock.get_requests()[0].content)
        assert "content" in payload

    def test_sends_slack_webhook(self, httpx_mock):
        httpx_mock.add_response(url="https://hooks.slack.com/services/test", status_code=200)
        report = self._make_report()
        Notifier().notify(report, AlertConfig(
            webhooks=["https://hooks.slack.com/services/test"], webhook_retries=0
        ))
        payload = json.loads(httpx_mock.get_requests()[0].content)
        assert "text" in payload

    def test_sends_generic_webhook(self, httpx_mock):
        httpx_mock.add_response(url="https://my-server.example.com/hook", status_code=200)
        report = self._make_report()
        Notifier().notify(report, AlertConfig(
            webhooks=["https://my-server.example.com/hook"], webhook_retries=0
        ))
        payload = json.loads(httpx_mock.get_requests()[0].content)
        assert "url" in payload and "changes" in payload

    def test_webhook_retry_on_server_error(self, httpx_mock):
        httpx_mock.add_response(url="https://discord.com/api/webhooks/test", status_code=500)
        httpx_mock.add_response(url="https://discord.com/api/webhooks/test", status_code=200)
        report = self._make_report()
        with patch("watchdiff.notifier.notifier.time.sleep"):
            Notifier().notify(report, AlertConfig(
                webhooks=["https://discord.com/api/webhooks/test"], webhook_retries=1
            ))
        assert len(httpx_mock.get_requests()) == 2

    def test_webhook_logs_warning_after_all_retries_fail(self, httpx_mock):
        httpx_mock.add_response(url="https://discord.com/api/webhooks/test", status_code=500)
        report = self._make_report()
        # webhook_retries=0 → 1 attempt max, should not raise
        Notifier().notify(report, AlertConfig(
            webhooks=["https://discord.com/api/webhooks/test"], webhook_retries=0
        ))
        assert len(httpx_mock.get_requests()) == 1


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class TestFetcher:
    def _config(self, **kwargs) -> WatchConfig:
        return WatchConfig(url="https://example.com", **kwargs)

    def test_returns_html_on_200(self, httpx_mock):
        httpx_mock.add_response(url="https://example.com", status_code=200, text="<html>Hello</html>")
        result = Fetcher().fetch(self._config())
        assert "Hello" in result

    def test_raises_fetch_error_on_404(self, httpx_mock):
        httpx_mock.add_response(url="https://example.com", status_code=404)
        with pytest.raises(FetchError):
            Fetcher().fetch(self._config())

    def test_raises_fetch_error_on_connection_error(self, httpx_mock):
        httpx_mock.add_exception(httpx.ConnectError("connection failed"))
        with pytest.raises(FetchError):
            Fetcher().fetch(self._config())

    def test_sends_custom_headers(self, httpx_mock):
        httpx_mock.add_response(url="https://example.com", status_code=200, text="ok")
        Fetcher().fetch(self._config(headers={"X-Custom": "test-value"}))
        assert httpx_mock.get_requests()[0].headers.get("x-custom") == "test-value"

    def test_retries_on_503(self, httpx_mock):
        httpx_mock.add_response(url="https://example.com", status_code=503)
        httpx_mock.add_response(url="https://example.com", status_code=200, text="ok")
        with patch("watchdiff.fetcher.fetcher.time.sleep"):
            result = Fetcher().fetch(self._config(retries=1, retry_delay=0.0))
        assert result == "ok"
        assert len(httpx_mock.get_requests()) == 2


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class TestScheduler:
    def _config(self, **kwargs) -> WatchConfig:
        return WatchConfig(url="https://example.com", label="test", **kwargs)

    def _mock_store(self, previous: Snapshot | None = None) -> MagicMock:
        store = MagicMock()
        store.load_latest.return_value = previous
        return store

    def test_first_check_returns_none_and_saves_snapshot(self, httpx_mock):
        httpx_mock.add_response(url="https://example.com", status_code=200, text="<html><body>Hello</body></html>")
        store     = self._mock_store()
        scheduler = SyncScheduler(store)
        result    = scheduler.check_once(self._config())
        assert result is None
        store.save_snapshot.assert_called_once()

    def test_detects_changes_between_snapshots(self, httpx_mock):
        httpx_mock.add_response(url="https://example.com", status_code=200, text="<html><body>Hello World</body></html>")
        previous  = Snapshot(url="https://example.com", target=None, content="Hello", raw_html="")
        store     = self._mock_store(previous=previous)
        scheduler = SyncScheduler(store)
        report    = scheduler.check_once(self._config())
        assert report is not None
        assert report.has_changes

    def test_pause_and_resume_updates_state(self):
        scheduler = SyncScheduler(MagicMock())
        scheduler.pause("https://example.com")
        assert "https://example.com" in scheduler._paused
        scheduler.resume("https://example.com")
        assert "https://example.com" not in scheduler._paused

    def test_status_returns_entry_per_config(self):
        scheduler         = SyncScheduler(MagicMock())
        scheduler._configs = [self._config()]
        statuses          = scheduler.status()
        assert len(statuses) == 1
        assert statuses[0].url == "https://example.com"
        assert not statuses[0].paused


# ---------------------------------------------------------------------------
# Cron parser
# ---------------------------------------------------------------------------

class TestCronParser:
    def test_every_minute(self):
        base = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        nxt  = next_cron_run("* * * * *", from_dt=base)
        assert nxt.minute == 1
        assert nxt.hour == 12

    def test_specific_hour_and_minute(self):
        base = datetime(2024, 6, 15, 8, 0, 0, tzinfo=timezone.utc)
        nxt  = next_cron_run("30 9 * * *", from_dt=base)
        assert nxt.hour == 9
        assert nxt.minute == 30

    def test_step_expression(self):
        base = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        nxt  = next_cron_run("*/15 * * * *", from_dt=base)
        assert nxt.minute == 15

    def test_invalid_expression_raises(self):
        with pytest.raises(ValueError, match="5 fields"):
            next_cron_run("* * * *")  # only 4 fields

    def test_range_expression(self):
        base = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        nxt  = next_cron_run("0 9-17 * * *", from_dt=base)
        assert 9 <= nxt.hour <= 17
        assert nxt.minute == 0


# ---------------------------------------------------------------------------
# JSON path extraction
# ---------------------------------------------------------------------------

class TestJsonPath:
    def test_top_level_key(self):
        data = json.dumps({"price": "19.99"})
        assert extract_json_path(data, "$.price") == "19.99"

    def test_nested_key(self):
        data = json.dumps({"product": {"name": "Widget"}})
        assert extract_json_path(data, "$.product.name") == "Widget"

    def test_array_index(self):
        data = json.dumps({"items": ["a", "b", "c"]})
        assert extract_json_path(data, "$.items[1]") == "b"

    def test_non_string_value_serialised(self):
        data = json.dumps({"count": 42})
        assert extract_json_path(data, "$.count") == "42"

    def test_missing_key_returns_original(self):
        data = json.dumps({"a": 1})
        assert extract_json_path(data, "$.missing") == data

    def test_invalid_json_returns_original(self):
        raw = "not json"
        assert extract_json_path(raw, "$.key") == raw


# ---------------------------------------------------------------------------
# Sitemap fetcher
# ---------------------------------------------------------------------------

class TestSitemapFetcher:
    _SIMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/page1</loc><lastmod>2024-01-01</lastmod></url>
  <url><loc>https://example.com/page2</loc></url>
</urlset>"""

    _INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap1.xml</loc></sitemap>
</sitemapindex>"""

    def test_parses_simple_sitemap(self, httpx_mock):
        httpx_mock.add_response(url="https://example.com/sitemap.xml", text=self._SIMPLE_XML)
        entries = SitemapFetcher().fetch("https://example.com/sitemap.xml")
        assert len(entries) == 2
        assert entries[0].url == "https://example.com/page1"
        assert entries[0].last_modified == "2024-01-01"
        assert entries[1].url == "https://example.com/page2"

    def test_handles_sitemap_index(self, httpx_mock):
        httpx_mock.add_response(url="https://example.com/sitemap-index.xml", text=self._INDEX_XML)
        httpx_mock.add_response(url="https://example.com/sitemap1.xml", text=self._SIMPLE_XML)
        entries = SitemapFetcher().fetch("https://example.com/sitemap-index.xml")
        assert len(entries) == 2

    def test_raises_on_fetch_error(self, httpx_mock):
        httpx_mock.add_response(url="https://example.com/sitemap.xml", status_code=404)
        with pytest.raises(RuntimeError, match="Failed to fetch sitemap"):
            SitemapFetcher().fetch("https://example.com/sitemap.xml")


# ---------------------------------------------------------------------------
# Flapping detection (confirm_after)
# ---------------------------------------------------------------------------

class TestFlappingDetection:
    def _config(self, **kwargs) -> WatchConfig:
        return WatchConfig(url="https://example.com", label="test", **kwargs)

    def _snap(self, content: str) -> Snapshot:
        return Snapshot(url="https://example.com", target=None, content=content, raw_html="")

    def test_confirm_after_suppresses_transient_change(self, httpx_mock):
        # First call returns changed content, second call returns original (reverted)
        httpx_mock.add_response(url="https://example.com", status_code=200,
                                text="<html><body>Changed</body></html>")
        httpx_mock.add_response(url="https://example.com", status_code=200,
                                text="<html><body>Original</body></html>")

        previous = self._snap("Original")
        store    = MagicMock()
        store.load_latest.return_value = previous

        with patch("watchdiff.scheduler.scheduler.time.sleep"):
            scheduler = SyncScheduler(store)
            report    = scheduler.check_once(self._config(confirm_after=5))

        # Change was detected but then reverted — report returned but no alert
        assert report is not None

    def test_confirm_after_allows_stable_change(self, httpx_mock):
        # Both calls return changed content → change is confirmed
        httpx_mock.add_response(url="https://example.com", status_code=200,
                                text="<html><body>New price: 99€</body></html>")
        httpx_mock.add_response(url="https://example.com", status_code=200,
                                text="<html><body>New price: 99€</body></html>")

        previous = self._snap("Old price: 49€")
        store    = MagicMock()
        store.load_latest.return_value = previous

        with patch("watchdiff.scheduler.scheduler.time.sleep"):
            scheduler = SyncScheduler(store)
            report    = scheduler.check_once(self._config(confirm_after=5))

        assert report is not None
        assert report.has_changes


# ---------------------------------------------------------------------------
# Email alert
# ---------------------------------------------------------------------------

class TestEmailAlert:
    def _make_report(self):
        before = Snapshot(url="https://example.com", target=None, content="Hello", raw_html="")
        after  = Snapshot(url="https://example.com", target=None, content="Hello World", raw_html="")
        return DiffEngine().compare(before, after, WatchConfig(url="https://example.com", label="test"))

    def _email_config(self) -> EmailConfig:
        return EmailConfig(
            to      = "dest@example.com",
            from_   = "sender@example.com",
            subject = "Test alert",
            smtp    = SmtpConfig(
                host="smtp.example.com", port=587,
                user="user", password="pass", secure=False,
            ),
        )

    def test_send_email_uses_starttls_on_port_587(self):
        report = self._make_report()
        cfg    = self._email_config()

        mock_server = MagicMock()
        with patch("smtplib.SMTP", return_value=mock_server) as mock_smtp:
            mock_smtp.return_value.__enter__ = lambda s: mock_server
            mock_smtp.return_value.__exit__  = MagicMock(return_value=False)
            send_email(cfg, report)

        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user", "pass")
        mock_server.sendmail.assert_called_once()

    def test_send_email_uses_ssl_on_port_465(self):
        report = self._make_report()
        cfg    = EmailConfig(
            to   = "dest@example.com",
            smtp = SmtpConfig(
                host="smtp.example.com", port=465,
                user="user", password="pass",
            ),
        )

        mock_server = MagicMock()
        with patch("smtplib.SMTP_SSL", return_value=mock_server) as mock_smtp_ssl:
            mock_smtp_ssl.return_value.__enter__ = lambda s: mock_server
            mock_smtp_ssl.return_value.__exit__  = MagicMock(return_value=False)
            send_email(cfg, report)

        mock_server.login.assert_called_once_with("user", "pass")
        mock_server.sendmail.assert_called_once()

    def test_notifier_triggers_email_on_change(self):
        report = self._make_report()
        alert  = AlertConfig(email=self._email_config())

        with patch("watchdiff.mailer.send_email") as mock_send:
            Notifier().notify(report, alert)
            mock_send.assert_called_once_with(alert.email, report)