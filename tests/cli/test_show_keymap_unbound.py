"""Test that `sqlit config show-keymap` lists unbound rebindable actions."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from sqlit.domains.shell.cli.config import run_show_keymap


def _capture_show_keymap(settings: dict | None = None) -> str:
    buf = StringIO()
    with (
        patch("sqlit.core.configurable_keymap.load_overrides_from_settings", return_value=(settings or {}).get("overrides", {})),
        patch("sys.stdout", buf),
    ):
        run_show_keymap()
    return buf.getvalue()


def test_show_keymap_lists_unbound_resize_actions() -> None:
    """Without overrides, the 4 resize_pane_* actions appear as (unbound)."""
    output = _capture_show_keymap()
    for action in (
        "resize_pane_left",
        "resize_pane_right",
        "resize_pane_up",
        "resize_pane_down",
    ):
        assert action in output, f"{action} missing from show-keymap output"
    assert "(unbound)" in output


def test_show_keymap_shows_overridden_resize_action() -> None:
    """When override is present, action shows the bound key with an asterisk."""
    output = _capture_show_keymap({"overrides": {"resize_pane_right": "ctrl+right"}})
    # Find the line for resize_pane_right; should contain ctrl+right
    lines = [line for line in output.splitlines() if "resize_pane_right" in line]
    assert lines, "resize_pane_right row missing"
    row = lines[0]
    assert "ctrl+right" in row
    assert "*" in row
