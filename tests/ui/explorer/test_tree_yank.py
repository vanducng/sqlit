"""Smoke test for the explorer tree yank (`ty`) leader menu wiring.

Verifies the end-to-end action dispatch without relying on the 350 ms
leader-menu timer (directly invoking the actions keeps the test fast and
non-flaky, per phase-03 step 4).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sqlit.core.input_context import InputContext
from sqlit.core.key_router import resolve_action
from sqlit.core.vim import VimMode
from sqlit.domains.explorer.domain.tree_nodes import TableNode
from sqlit.domains.shell.app.main import SSMSTUI
from sqlit.domains.shell.state import UIStateMachine

from ..mocks import (
    MockConnectionStore,
    MockSettingsStore,
    build_test_services,
    create_test_connection,
)


class _FakeDialect:
    """Minimal dialect that double-quotes identifiers (matches sqlite/pg)."""

    def quote_identifier(self, name: str) -> str:
        return f'"{name}"'

    def build_select_query(
        self, table: str, limit: int, database: str | None = None, schema: str | None = None
    ) -> str:
        parts = [f'"{p}"' for p in (database, schema, table) if p]
        return f"SELECT * FROM {'.'.join(parts)} LIMIT {limit}"

    def format_table_name(self, schema: str | None, table: str) -> str:
        return f'"{schema}"."{table}"' if schema else f'"{table}"'


def _build_app() -> SSMSTUI:
    services = build_test_services(
        connection_store=MockConnectionStore([create_test_connection("test-db", "sqlite")]),
        settings_store=MockSettingsStore({"theme": "tokyo-night"}),
    )
    return SSMSTUI(services=services)


def _install_fake_cursor(app: SSMSTUI, monkeypatch: pytest.MonkeyPatch, cursor_node: object) -> None:
    """Replace the `object_tree` property with a fake so the resolver sees our node."""
    fake_tree = SimpleNamespace(cursor_node=cursor_node)
    monkeypatch.setattr(type(app), "object_tree", property(lambda _self: fake_tree))
    app.current_provider = SimpleNamespace(dialect=_FakeDialect())  # type: ignore[assignment]


def _tree_focused_context() -> InputContext:
    """Build an InputContext representing a focused explorer tree."""
    return InputContext(
        focus="explorer",
        vim_mode=VimMode.NORMAL,
        leader_pending=False,
        leader_menu="leader",
        tree_filter_active=False,
        tree_multi_select_active=False,
        tree_visual_mode_active=False,
        autocomplete_visible=False,
        results_filter_active=False,
        value_view_active=False,
        value_view_tree_mode=False,
        value_view_is_json=False,
        query_executing=False,
        modal_open=False,
        has_connection=True,
        current_connection_name="test-db",
        tree_node_kind="table",
        tree_node_connection_name=None,
        tree_node_connection_selected=False,
        last_result_is_error=False,
        has_results=False,
    )


def test_y_key_resolves_to_ty_leader_key_in_tree_focused_state() -> None:
    """Regression: `y` in tree focused state must dispatch `ty_leader_key`.

    Key routing only fires when the active state whitelists the target action.
    """
    sm = UIStateMachine()
    ctx = _tree_focused_context()
    is_allowed = lambda name: sm.check_action(ctx, name)

    assert resolve_action("y", ctx, is_allowed=is_allowed) == "ty_leader_key"


@pytest.mark.asyncio
async def test_ty_leader_key_marks_ty_menu_pending() -> None:
    """Pressing `y` in tree context marks the ty leader pending."""
    app = _build_app()
    async with app.run_test(size=(100, 35)):
        app.action_ty_leader_key()
        assert app._leader_pending is True
        assert app._leader_pending_menu == "ty"
        app._cancel_leader_pending()


@pytest.mark.asyncio
async def test_ty_yank_qualified_copies_quoted_fqn(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ty` menu `y` action copies the dialect-quoted qualified name."""
    app = _build_app()
    async with app.run_test(size=(100, 35)):
        copied: list[str] = []
        app._copy_text = lambda text: copied.append(text) or True  # type: ignore[assignment]
        table_node = TableNode(database=None, schema="public", name="users")
        _install_fake_cursor(app, monkeypatch, SimpleNamespace(data=table_node))

        app.action_ty_yank_qualified()

        assert copied == ['"public"."users"']


@pytest.mark.asyncio
async def test_ty_yank_name_copies_bare_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ty` menu `n` action copies only the bare node name."""
    app = _build_app()
    async with app.run_test(size=(100, 35)):
        copied: list[str] = []
        app._copy_text = lambda text: copied.append(text) or True  # type: ignore[assignment]
        table_node = TableNode(database=None, schema="public", name="users")
        _install_fake_cursor(app, monkeypatch, SimpleNamespace(data=table_node))

        app.action_ty_yank_name()

        assert copied == ["users"]


@pytest.mark.asyncio
async def test_ty_yank_select_copies_select_snippet(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ty` menu `s` action copies a SELECT ... LIMIT 100 snippet for a table."""
    app = _build_app()
    async with app.run_test(size=(100, 35)):
        copied: list[str] = []
        app._copy_text = lambda text: copied.append(text) or True  # type: ignore[assignment]
        table_node = TableNode(database=None, schema="public", name="users")
        _install_fake_cursor(app, monkeypatch, SimpleNamespace(data=table_node))

        app.action_ty_yank_select()

        assert copied == ['SELECT * FROM "public"."users" LIMIT 100']


@pytest.mark.asyncio
async def test_ty_yank_on_empty_cursor_skips_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no cursor node exists, ty actions notify and do not copy."""
    app = _build_app()
    async with app.run_test(size=(100, 35)):
        copied: list[str] = []
        app._copy_text = lambda text: copied.append(text) or True  # type: ignore[assignment]
        _install_fake_cursor(app, monkeypatch, None)

        app.action_ty_yank_name()
        app.action_ty_yank_qualified()

        assert copied == []
