"""Tests for results-filter saved-snapshot + paste/Ctrl+U behaviors.

These tests exercise the mixin methods directly (bypassing widget composition)
so they stay pure-unit and don't need a mounted Textual app.
"""

from __future__ import annotations

from textual.events import Key

from sqlit.domains.connections.ui.screens.connection_picker.screen import ConnectionPickerScreen
from sqlit.domains.explorer.ui.mixins.tree_filter import TreeFilterMixin
from sqlit.domains.results.ui.mixins.results_filter import ResultsFilterMixin


class _PasteEvent:
    """Minimal stand-in for textual.events.Paste."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.prevented = False
        self.stopped = False

    def prevent_default(self) -> None:
        self.prevented = True

    def stop(self) -> None:
        self.stopped = True


class _ResultsFilterFake(ResultsFilterMixin):
    """Minimal stand-in implementing the surface ResultsFilterMixin touches.

    Inherits from the mixin so `super()` calls inside the mixin resolve cleanly.
    """

    def __init__(self, rows: int = 5) -> None:
        self._last_result_columns: list[str] = ["id", "name"]
        self._last_result_rows: list[tuple] = [(i, f"row-{i}") for i in range(rows)]
        self._results_filter_visible = False
        self._results_filter_text = ""
        self._results_filter_row_texts: list[str] = []
        self._results_filter_row_texts_lower: list[str] = []
        self._results_filter_matches: list = []
        self._results_filter_match_index = 0
        self._results_filter_matching_rows: list[tuple] = []
        self._results_filter_original_columns: list[str] = []
        self._results_filter_original_rows: list[tuple] = []
        self._results_filter_saved_rows: list[tuple] | None = None
        self._results_filter_saved_columns: list[str] | None = None
        self._results_filter_prior_commit_rows: list[tuple] | None = None
        self._results_filter_stacked = False
        self._results_filter_target_section = None
        self._results_filter_target_table = None
        self._scheduled = False

    # Helpers the mixin reaches for
    def _replace_results_table(self, *a, **kw) -> None: pass
    def _restore_results_table(self) -> None: pass
    def _prime_results_filter_cache(self, *a, **kw) -> None: pass
    def _update_footer_bindings(self) -> None: pass
    def _schedule_filter_update(self) -> None: self._scheduled = True
    def _get_active_stacked_results_target(self): return (None, None)
    def notify(self, *a, **kw) -> None: pass

    @property
    def results_filter_input(self):
        class _I:
            def show(self): pass
            def hide(self): pass
            def set_filter(self, *a, **kw): pass
        return _I()

    @property
    def results_table(self):
        class _T:
            has_focus = True
            def focus(self): pass
        return _T()

    @property
    def results_area(self):
        class _A:
            def has_class(self, n): return False
            def add_class(self, n): pass
            def remove_class(self, n): pass
        return _A()


class TestResultsFilterSnapshot:
    def test_accept_then_reopen_restores_full_view(self):
        f = _ResultsFilterFake(rows=5)
        ResultsFilterMixin.action_results_filter(f)
        f._results_filter_text = "row-1"
        f._results_filter_matching_rows = [(1, "row-1")]
        ResultsFilterMixin.action_results_filter_accept(f)
        assert len(f._last_result_rows) == 1
        assert f._results_filter_saved_rows == [(i, f"row-{i}") for i in range(5)]

        # Reopen — full view restored
        ResultsFilterMixin.action_results_filter(f)
        assert len(f._last_result_rows) == 5
        # Prior-commit stash captured the previous filtered subset
        assert f._results_filter_prior_commit_rows == [(1, "row-1")]

    def test_escape_after_reopen_preserves_prior_commit(self):
        """Commit, reopen, type nothing, Escape → prior commit kept (NOT lost)."""
        f = _ResultsFilterFake(rows=5)
        ResultsFilterMixin.action_results_filter(f)
        f._results_filter_text = "row-1"
        f._results_filter_matching_rows = [(1, "row-1")]
        ResultsFilterMixin.action_results_filter_accept(f)
        committed = list(f._last_result_rows)
        assert len(committed) == 1

        # Reopen, type nothing, Escape
        ResultsFilterMixin.action_results_filter(f)
        assert len(f._last_result_rows) == 5  # full view shown
        ResultsFilterMixin.action_results_filter_close(f)
        assert f._last_result_rows == committed
        # Saved snapshot stays so a future `/` can still restore the full view
        assert f._results_filter_saved_rows is not None

    def test_escape_first_open_clears_snapshot(self):
        """Open `/`, type nothing, Escape on first open → snapshot stays None."""
        f = _ResultsFilterFake(rows=5)
        ResultsFilterMixin.action_results_filter(f)
        ResultsFilterMixin.action_results_filter_close(f)
        assert f._results_filter_saved_rows is None
        assert f._results_filter_prior_commit_rows is None

    def test_reopen_after_snapshot_cleared_uses_fresh_rows(self):
        """After snapshot cleared (new query), `/` reopens against fresh rows."""
        f = _ResultsFilterFake(rows=3)
        ResultsFilterMixin.action_results_filter(f)
        f._results_filter_text = "row-0"
        f._results_filter_matching_rows = [(0, "row-0")]
        ResultsFilterMixin.action_results_filter_accept(f)
        assert f._results_filter_saved_rows is not None

        # Simulate fresh-results cleanup (mirrors query_results.py:324-327)
        f._last_result_columns = ["a"]
        f._last_result_rows = [(1,), (2,), (3,)]
        f._results_filter_saved_rows = None
        f._results_filter_saved_columns = None
        f._results_filter_prior_commit_rows = None

        ResultsFilterMixin.action_results_filter(f)
        assert f._results_filter_original_rows == [(1,), (2,), (3,)]


class TestResultsFilterCtrlU:
    def test_ctrl_u_clears_filter_text(self):
        f = _ResultsFilterFake(rows=5)
        f._results_filter_visible = True
        f._results_filter_text = "row-1"
        ResultsFilterMixin.on_key(f, Key(key="ctrl+u", character=None))
        assert f._results_filter_text == ""
        assert f._scheduled is True

    def test_ctrl_u_noop_when_filter_inactive(self):
        f = _ResultsFilterFake(rows=5)
        f._results_filter_visible = False
        f._results_filter_text = ""
        ResultsFilterMixin.on_key(f, Key(key="ctrl+u", character=None))
        assert f._scheduled is False


class TestResultsFilterPaste:
    def test_paste_appends_when_visible(self):
        f = _ResultsFilterFake(rows=5)
        f._results_filter_visible = True
        f._results_filter_text = "ro"
        event = _PasteEvent("w-1")
        ResultsFilterMixin.on_paste(f, event)
        assert f._results_filter_text == "row-1"
        assert event.prevented and event.stopped

    def test_paste_collapses_newlines_to_spaces(self):
        f = _ResultsFilterFake(rows=5)
        f._results_filter_visible = True
        event = _PasteEvent("foo\nbar\nbaz")
        ResultsFilterMixin.on_paste(f, event)
        assert f._results_filter_text == "foo bar baz"

    def test_paste_ignored_when_inactive(self):
        f = _ResultsFilterFake(rows=5)
        f._results_filter_visible = False
        event = _PasteEvent("ignored")
        ResultsFilterMixin.on_paste(f, event)
        assert f._results_filter_text == ""

    def test_paste_empty_bubbles_up(self):
        f = _ResultsFilterFake(rows=5)
        f._results_filter_visible = True
        event = _PasteEvent("\n\n  ")
        ResultsFilterMixin.on_paste(f, event)
        # Empty paste bubbles to parent rather than being silently consumed
        assert f._results_filter_text == ""
        assert event.prevented is False
        assert event.stopped is False


class _TreeFilterFake(TreeFilterMixin):
    def __init__(self, *, visible: bool, typing: bool, text: str = "") -> None:
        self._tree_filter_visible = visible
        self._tree_filter_typing = typing
        self._tree_filter_text = text
        self._updated = False

    def _update_tree_filter(self) -> None:
        self._updated = True


class TestTreeFilterPaste:
    def test_paste_appends_when_active(self):
        f = _TreeFilterFake(visible=True, typing=True, text="pre")
        event = _PasteEvent("fix")
        TreeFilterMixin.on_paste(f, event)
        assert f._tree_filter_text == "prefix"
        assert event.prevented and event.stopped
        assert f._updated is True

    def test_paste_ignored_when_inactive(self):
        f = _TreeFilterFake(visible=False, typing=False, text="untouched")
        event = _PasteEvent("ignored")
        TreeFilterMixin.on_paste(f, event)
        assert f._tree_filter_text == "untouched"
        assert f._updated is False

    def test_paste_collapses_multiline_to_spaces(self):
        f = _TreeFilterFake(visible=True, typing=True, text="")
        event = _PasteEvent("foo\nbar\r\nbaz")
        TreeFilterMixin.on_paste(f, event)
        assert f._tree_filter_text == "foo bar baz"
        assert f._updated is True

    def test_paste_empty_bubbles_up(self):
        """Empty/whitespace-only paste must not be silently swallowed."""
        f = _TreeFilterFake(visible=True, typing=True, text="kept")
        event = _PasteEvent("   \n   ")
        TreeFilterMixin.on_paste(f, event)
        # Filter text unchanged, event NOT prevented (bubbles to parent)
        assert f._tree_filter_text == "kept"
        assert event.prevented is False
        assert event.stopped is False


class TestConnectionPickerPaste:
    def test_paste_appends_when_filter_active(self):
        screen = ConnectionPickerScreen.__new__(ConnectionPickerScreen)

        class _FilterState:
            active = True
            text = "abc"

        screen._filter_state = _FilterState()  # type: ignore[attr-defined]
        screen._update_filter_display = lambda: None  # type: ignore[attr-defined,method-assign]
        screen._update_list = lambda: None  # type: ignore[attr-defined,method-assign]
        event = _PasteEvent("def\nghi")
        screen.on_paste(event)  # type: ignore[arg-type]
        assert screen._filter_state.text == "abcdef ghi"
        assert event.prevented and event.stopped

    def test_paste_noop_when_filter_inactive(self):
        screen = ConnectionPickerScreen.__new__(ConnectionPickerScreen)

        class _FilterState:
            active = False
            text = "untouched"

        screen._filter_state = _FilterState()  # type: ignore[attr-defined]
        event = _PasteEvent("ignored")
        screen.on_paste(event)  # type: ignore[arg-type]
        assert screen._filter_state.text == "untouched"
