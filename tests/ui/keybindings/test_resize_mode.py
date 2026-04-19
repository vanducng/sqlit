"""Tests for the pane resize mode (<space>r leader + arrows)."""

from __future__ import annotations

import pytest

from sqlit.core.keymap import get_keymap
from sqlit.domains.shell.app.main import SSMSTUI
from sqlit.domains.shell.state.layout_state import (
    DEFAULT_QUERY_PCT,
    DEFAULT_SIDEBAR_WIDTH,
    STEP,
    LayoutState,
)

from ..mocks import MockConnectionStore, MockSettingsStore, build_test_services


def _make_app(settings: dict | None = None) -> SSMSTUI:
    services = build_test_services(
        connection_store=MockConnectionStore(),
        settings_store=MockSettingsStore(settings or {"theme": "tokyo-night"}),
    )
    return SSMSTUI(services=services)


class TestLayoutStateInitFromSettings:
    def test_defaults_when_missing(self):
        app = _make_app({"theme": "tokyo-night"})
        assert app._layout_state.sidebar_width == DEFAULT_SIDEBAR_WIDTH
        assert app._layout_state.query_height_pct == DEFAULT_QUERY_PCT

    def test_loads_from_settings(self):
        app = _make_app({"layout": {"sidebar_width": 50, "query_height_pct": 30}})
        assert app._layout_state.sidebar_width == 50
        assert app._layout_state.query_height_pct == 30

    def test_corrupt_falls_back(self):
        app = _make_app({"layout": "garbage-string"})
        assert app._layout_state.sidebar_width == DEFAULT_SIDEBAR_WIDTH


class TestResizeModeFlag:
    @pytest.mark.asyncio
    async def test_leader_r_enters_resize_mode(self):
        keymap = get_keymap()
        leader_key = keymap.action("leader_key")
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press(leader_key, "r")
            await pilot.pause()
            assert app._resize_mode_active is True

    @pytest.mark.asyncio
    async def test_arrow_in_resize_mode_resizes_sidebar(self):
        keymap = get_keymap()
        leader_key = keymap.action("leader_key")
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            # Focus explorer first so sidebar pane is the resize target
            app.action_focus_explorer()
            await pilot.pause()
            before = app._layout_state.sidebar_width
            await pilot.press(leader_key, "r", "right", "right")
            await pilot.pause()
            assert app._layout_state.sidebar_width == before + 2 * STEP

    @pytest.mark.asyncio
    async def test_non_arrow_exits_resize_mode(self):
        keymap = get_keymap()
        leader_key = keymap.action("leader_key")
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press(leader_key, "r")
            await pilot.pause()
            assert app._resize_mode_active is True
            await pilot.press("x")
            await pilot.pause()
            assert app._resize_mode_active is False


class TestPersistRoundTrip:
    def test_persist_writes_to_settings(self):
        store = MockSettingsStore({"theme": "tokyo-night"})
        services = build_test_services(
            connection_store=MockConnectionStore(),
            settings_store=store,
        )
        app = SSMSTUI(services=services)
        app._layout_state = LayoutState(sidebar_width=42, query_height_pct=60)
        app._persist_layout()
        saved = store.get("layout", {})
        assert saved == {"sidebar_width": 42, "query_height_pct": 60}

    def test_round_trip_via_new_instance(self):
        store = MockSettingsStore({"theme": "tokyo-night"})
        services1 = build_test_services(
            connection_store=MockConnectionStore(),
            settings_store=store,
        )
        app1 = SSMSTUI(services=services1)
        app1._layout_state = LayoutState(sidebar_width=55, query_height_pct=70)
        app1._persist_layout()

        services2 = build_test_services(
            connection_store=MockConnectionStore(),
            settings_store=store,
        )
        app2 = SSMSTUI(services=services2)
        assert app2._layout_state.sidebar_width == 55
        assert app2._layout_state.query_height_pct == 70


class TestInsertModeGuard:
    @pytest.mark.asyncio
    async def test_insert_mode_blocks_resize(self):
        """When focused on query in INSERT mode, _do_resize must no-op."""
        from sqlit.core.vim import VimMode

        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.action_focus_query()
            app.vim_mode = VimMode.INSERT
            await pilot.pause()
            before = app._layout_state.query_height_pct
            app.action_resize_pane_down()
            await pilot.pause()
            # No change because INSERT-mode in query pane is guarded
            assert app._layout_state.query_height_pct == before

    @pytest.mark.asyncio
    async def test_tree_filter_blocks_resize_when_focused_in_sidebar(self):
        """Active tree-filter input must block resize when focus is in sidebar."""
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.action_focus_explorer()
            app._tree_filter_visible = True
            await pilot.pause()
            before = app._layout_state.sidebar_width
            app.action_resize_pane_right()
            await pilot.pause()
            assert app._layout_state.sidebar_width == before

    @pytest.mark.asyncio
    async def test_tree_filter_does_not_block_other_panes(self):
        """Tree filter open in sidebar must NOT block resize when focus is in query."""
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app._tree_filter_visible = True  # filter open in sidebar
            app.action_focus_query()  # but focus is in query
            await pilot.pause()
            before = app._layout_state.query_height_pct
            app.action_resize_pane_down()
            await pilot.pause()
            assert app._layout_state.query_height_pct == before + 2

    @pytest.mark.asyncio
    async def test_results_filter_blocks_resize_when_focused_in_results(self):
        """Active results-filter input must block resize when focus is in results."""
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.action_focus_results()
            app._results_filter_visible = True
            await pilot.pause()
            before = app._layout_state.query_height_pct
            app.action_resize_pane_up()
            await pilot.pause()
            assert app._layout_state.query_height_pct == before

    @pytest.mark.asyncio
    async def test_results_filter_does_not_block_other_panes(self):
        """Results filter open must NOT block sidebar resize."""
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app._results_filter_visible = True
            app.action_focus_explorer()
            await pilot.pause()
            before = app._layout_state.sidebar_width
            app.action_resize_pane_right()
            await pilot.pause()
            assert app._layout_state.sidebar_width == before + 2


class TestModalClearsResizeMode:
    @pytest.mark.asyncio
    async def test_modal_open_clears_resize_mode(self):
        """If a modal opens while resize mode is active, the flag must clear."""
        from textual.screen import ModalScreen
        from textual.widgets import Static

        class _FakeModal(ModalScreen):
            def compose(self):
                yield Static("modal")

        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app._resize_mode_active = True
            await app.push_screen(_FakeModal())
            await pilot.pause()
            # Send any key — on_key sees modal_open and clears the flag
            await pilot.press("a")
            await pilot.pause()
            assert app._resize_mode_active is False


class TestValidateActions:
    def test_no_missing_handlers(self):
        from sqlit.core.action_validation import validate_actions

        app = _make_app()
        missing = validate_actions(app)
        assert missing == [], f"Missing handlers: {missing}"
