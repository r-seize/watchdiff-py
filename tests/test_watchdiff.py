"""
WatchDiff - unit tests.
"""

from __future__ import annotations


import pytest

from watchdiff.cleaner import Cleaner
from watchdiff.diff import DiffEngine
from watchdiff.models import ChangeType, Snapshot, WatchConfig
from watchdiff.parser import Parser
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