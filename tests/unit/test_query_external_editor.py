"""Unit tests for the query external-editor mixin."""

from __future__ import annotations

import shutil
from typing import Any
from unittest.mock import MagicMock

import pytest

from sqlit.domains.query.ui.mixins.query_external_editor import (
    QueryExternalEditorMixin,
)


class FakeHost(QueryExternalEditorMixin):
    """Minimal host exposing the attributes the mixin touches."""

    def __init__(self, text: str) -> None:
        self.query_input = MagicMock()
        self.query_input.text = text
        self.query_input.cursor_location = (0, 0)
        self.app = MagicMock()
        # `with self.app.suspend(): ...` — context manager no-op.
        self.app.suspend.return_value.__enter__ = lambda _self: None
        self.app.suspend.return_value.__exit__ = lambda _self, *a: False
        self._query_worker: Any = None
        self._autocomplete_visible = False
        self._hide_autocomplete_called = False
        self._exit_insert_called = False
        self._undo_pushes = 0
        self.notifications: list[tuple[str, str]] = []

    def notify(self, msg: str, *, severity: str = "information", **_: Any) -> None:
        self.notifications.append((msg, severity))

    def _hide_autocomplete(self) -> None:
        self._hide_autocomplete_called = True
        self._autocomplete_visible = False

    def _push_undo_state(self) -> None:
        self._undo_pushes += 1

    def action_exit_insert_mode(self) -> None:
        self._exit_insert_called = True


def _has_bash() -> bool:
    return shutil.which("bash") is not None


def _has_true_false() -> bool:
    return shutil.which("true") is not None and shutil.which("false") is not None


def test_returns_early_while_query_running() -> None:
    host = FakeHost("SELECT 1")
    host._query_worker = object()
    host.action_edit_in_external_editor()
    assert host.query_input.text == "SELECT 1"
    assert any("running" in msg.lower() for msg, _ in host.notifications)


def test_rejects_blank_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    host = FakeHost("SELECT 1")
    monkeypatch.setenv("VISUAL", "   ")
    monkeypatch.delenv("EDITOR", raising=False)
    host.action_edit_in_external_editor()
    assert any(severity == "error" for _, severity in host.notifications)


def test_rejects_unparseable_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    host = FakeHost("SELECT 1")
    monkeypatch.setenv("VISUAL", 'vi "unterminated')
    monkeypatch.delenv("EDITOR", raising=False)
    host.action_edit_in_external_editor()
    assert any("invalid" in msg.lower() for msg, _ in host.notifications)


@pytest.mark.skipif(not _has_bash(), reason="bash required")
def test_replaces_buffer_on_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    host = FakeHost("SELECT 1")
    monkeypatch.setenv("EDITOR", "bash -c 'printf SELECT\\ 2 > \"$1\"' _")
    monkeypatch.delenv("VISUAL", raising=False)
    host.action_edit_in_external_editor()
    assert host.query_input.text == "SELECT 2"
    assert host._undo_pushes == 1
    assert any("updated" in msg.lower() for msg, _ in host.notifications)


@pytest.mark.skipif(not _has_true_false(), reason="coreutils required")
def test_preserves_buffer_on_non_zero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    host = FakeHost("SELECT 1")
    monkeypatch.setenv("EDITOR", "false")
    monkeypatch.delenv("VISUAL", raising=False)
    host.action_edit_in_external_editor()
    assert host.query_input.text == "SELECT 1"
    assert host._undo_pushes == 0
    assert any("status" in msg.lower() for msg, _ in host.notifications)


@pytest.mark.skipif(not _has_true_false(), reason="coreutils required")
def test_no_change_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    host = FakeHost("SELECT 1")
    monkeypatch.setenv("EDITOR", "true")  # exit 0, no write
    monkeypatch.delenv("VISUAL", raising=False)
    host.action_edit_in_external_editor()
    assert host.query_input.text == "SELECT 1"
    assert host._undo_pushes == 0
    assert any("no changes" in msg.lower() for msg, _ in host.notifications)


@pytest.mark.skipif(not _has_bash(), reason="bash required")
def test_closes_autocomplete_and_exits_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    host = FakeHost("SELECT 1")
    host._autocomplete_visible = True
    monkeypatch.setenv("EDITOR", "bash -c 'printf SELECT\\ 3 > \"$1\"' _")
    monkeypatch.delenv("VISUAL", raising=False)
    host.action_edit_in_external_editor()
    assert host._hide_autocomplete_called
    assert host._exit_insert_called
    assert host.query_input.text == "SELECT 3"


@pytest.mark.skipif(not _has_bash(), reason="bash required")
def test_visual_preferred_over_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    host = FakeHost("SELECT 1")
    monkeypatch.setenv("VISUAL", "bash -c 'printf VISUAL > \"$1\"' _")
    monkeypatch.setenv("EDITOR", "bash -c 'printf EDITOR > \"$1\"' _")
    host.action_edit_in_external_editor()
    assert host.query_input.text == "VISUAL"
