"""Regression tests for <leader>f fullscreen toggle.

Ensure that inline width/height stamped by ``_apply_layout_state`` are cleared
on fullscreen entry (so the ``*-fullscreen`` CSS classes can win the cascade)
and re-applied from ``LayoutState`` on exit.

Inline styles are probed via ``widget.styles.inline.has_rule(...)`` — the
composite ``widget.styles`` merges CSS + inline and would mask the fix, since
the fullscreen CSS class itself sets ``width: 1fr`` / ``height: 1fr``.
"""

from __future__ import annotations

import pytest

from sqlit.domains.shell.app.main import SSMSTUI
from sqlit.domains.shell.state.layout_state import STEP

from ..mocks import MockConnectionStore, MockSettingsStore, build_test_services


def _make_app(settings: dict | None = None) -> SSMSTUI:
    services = build_test_services(
        connection_store=MockConnectionStore(),
        settings_store=MockSettingsStore(settings or {"theme": "tokyo-night"}),
    )
    return SSMSTUI(services=services)


class TestFullscreenEnterClearsInlineSizes:
    @pytest.mark.asyncio
    async def test_query_fullscreen_clears_inline_height(self):
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.action_focus_query()
            await pilot.pause()
            qa = app.query_one("#query-area")
            ra = app.query_one("#results-area")
            sidebar = app.query_one("#sidebar")
            # Sanity: _apply_layout_state stamped inline sizes on mount.
            assert qa.styles.inline.has_rule("height")
            assert ra.styles.inline.has_rule("height")
            assert sidebar.styles.inline.has_rule("width")

            app.action_toggle_fullscreen()
            await pilot.pause()

            assert app._fullscreen_mode == "query"
            assert app.screen.has_class("query-fullscreen")
            assert not qa.styles.inline.has_rule("height")
            assert not ra.styles.inline.has_rule("height")
            assert not sidebar.styles.inline.has_rule("width")

    @pytest.mark.asyncio
    async def test_explorer_fullscreen_clears_inline_width(self):
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.action_focus_explorer()
            await pilot.pause()
            sidebar = app.query_one("#sidebar")
            assert sidebar.styles.inline.has_rule("width")

            app.action_toggle_fullscreen()
            await pilot.pause()

            assert app._fullscreen_mode == "explorer"
            assert app.screen.has_class("explorer-fullscreen")
            assert not sidebar.styles.inline.has_rule("width")

    @pytest.mark.asyncio
    async def test_results_fullscreen_clears_inline_sizes(self):
        """Drive _set_fullscreen_mode directly — results pane focus depends on
        lazy-mounted data-table, so we exercise the code path without relying
        on action_toggle_fullscreen resolving the target."""
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            qa = app.query_one("#query-area")
            ra = app.query_one("#results-area")

            app._set_fullscreen_mode("results")
            await pilot.pause()

            assert app._fullscreen_mode == "results"
            assert app.screen.has_class("results-fullscreen")
            assert not qa.styles.inline.has_rule("height")
            assert not ra.styles.inline.has_rule("height")


class TestFullscreenExitRestoresLayout:
    @pytest.mark.asyncio
    async def test_exit_restores_layout_state(self):
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.action_focus_query()
            await pilot.pause()

            app.action_toggle_fullscreen()
            await pilot.pause()
            app.action_toggle_fullscreen()
            await pilot.pause()

            assert app._fullscreen_mode == "none"
            assert not app.screen.has_class("query-fullscreen")
            assert not app.screen.has_class("explorer-fullscreen")
            assert not app.screen.has_class("results-fullscreen")

            qa = app.query_one("#query-area")
            ra = app.query_one("#results-area")
            sidebar = app.query_one("#sidebar")
            assert qa.styles.inline.has_rule("height")
            assert ra.styles.inline.has_rule("height")
            assert sidebar.styles.inline.has_rule("width")

    @pytest.mark.asyncio
    async def test_resize_delta_preserved_across_fullscreen(self):
        """User resize must survive a fullscreen round-trip."""
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.action_focus_query()
            await pilot.pause()
            baseline = app._layout_state.query_height_pct
            app.action_resize_pane_down()
            app.action_resize_pane_down()
            await pilot.pause()
            bumped = baseline + 2 * STEP
            assert app._layout_state.query_height_pct == bumped

            app.action_toggle_fullscreen()
            await pilot.pause()
            app.action_toggle_fullscreen()
            await pilot.pause()

            assert app._layout_state.query_height_pct == bumped
