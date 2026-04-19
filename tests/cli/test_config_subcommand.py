"""E2E tests for `sqlit config edit` and `sqlit config show-keymap`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(
    *args: str,
    env_overrides: dict[str, str] | None = None,
    unset: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in unset:
        env.pop(key, None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "sqlit.cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_config_edit_creates_missing_file(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    assert not settings.exists()
    result = _run(
        "config",
        "edit",
        env_overrides={
            "SQLIT_SETTINGS_PATH": str(settings),
            "EDITOR": "true",
            "VISUAL": "",
        },
    )
    assert result.returncode == 0, result.stderr
    assert settings.exists()
    assert json.loads(settings.read_text()) == {}


def test_config_edit_opens_existing_file(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    payload = {"keymap": {"overrides": {"focus_explorer": "1"}}}
    settings.write_text(json.dumps(payload))
    result = _run(
        "config",
        "edit",
        env_overrides={
            "SQLIT_SETTINGS_PATH": str(settings),
            "EDITOR": "true",
            "VISUAL": "",
        },
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(settings.read_text()) == payload


def test_config_edit_no_editor_available(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    # Point PATH at an empty dir so `vi` is unavailable.
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    result = _run(
        "config",
        "edit",
        env_overrides={
            "SQLIT_SETTINGS_PATH": str(settings),
            "EDITOR": "",
            "VISUAL": "",
            "PATH": str(empty_bin),
        },
    )
    assert result.returncode == 1
    assert "No editor" in result.stderr or "editor" in result.stderr.lower()


def test_config_show_keymap_default(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    result = _run(
        "config",
        "show-keymap",
        env_overrides={"SQLIT_SETTINGS_PATH": str(settings)},
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    header_joined = lines[0]
    assert "KEY" in header_joined and "ACTION" in header_joined
    focus_explorer_lines = [ln for ln in lines if "focus_explorer" in ln]
    assert focus_explorer_lines, result.stdout
    assert focus_explorer_lines[0].split()[0] == "e"
    assert "*" not in focus_explorer_lines[0]


def test_config_show_keymap_with_override(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"keymap": {"overrides": {"focus_explorer": "1"}}})
    )
    result = _run(
        "config",
        "show-keymap",
        env_overrides={"SQLIT_SETTINGS_PATH": str(settings)},
    )
    assert result.returncode == 0, result.stderr
    focus_explorer_lines = [
        ln for ln in result.stdout.splitlines() if "focus_explorer" in ln
    ]
    assert focus_explorer_lines, result.stdout
    row = focus_explorer_lines[0]
    assert row.split()[0] == "1"
    assert "*" in row


def test_config_show_keymap_tolerates_malformed_settings(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"keymap": "broken"}))
    result = _run(
        "config",
        "show-keymap",
        env_overrides={"SQLIT_SETTINGS_PATH": str(settings)},
    )
    assert result.returncode == 0, result.stderr
    assert "focus_explorer" in result.stdout
    assert "non-dict" in result.stderr


def test_config_edit_handles_multiword_editor(tmp_path: Path) -> None:
    """EDITOR values like `code --wait` must be shlex-split, not passed as one exe."""
    settings = tmp_path / "settings.json"
    log = tmp_path / "editor.log"
    fake = tmp_path / "fakeeditor.sh"
    fake.write_text(
        f'#!/bin/sh\necho "argc=$#" >> {log}\nfor a in "$@"; do echo "$a" >> {log}; done\n'
    )
    fake.chmod(0o755)
    result = _run(
        "config",
        "edit",
        env_overrides={
            "SQLIT_SETTINGS_PATH": str(settings),
            # Multi-word command: first token is the script, `--flag` is an arg.
            "EDITOR": f"{fake} --flag",
            "VISUAL": "",
        },
    )
    assert result.returncode == 0, result.stderr
    lines = log.read_text().splitlines()
    # Expect 2 args: --flag + settings path (argc=2)
    assert lines[0] == "argc=2", lines
    assert lines[1] == "--flag"
    assert lines[2] == str(settings)


def test_config_show_keymap_does_not_flag_rejected_overrides(tmp_path: Path) -> None:
    """Non-whitelisted overrides should not get `*` in show-keymap output."""
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"keymap": {"overrides": {"quit": "Q"}}}))
    result = _run(
        "config",
        "show-keymap",
        env_overrides={"SQLIT_SETTINGS_PATH": str(settings)},
    )
    assert result.returncode == 0, result.stderr
    quit_lines = [ln for ln in result.stdout.splitlines() if " quit " in f" {ln} "]
    assert quit_lines, result.stdout
    assert "*" not in quit_lines[0]
    # Validator warning should still surface.
    assert "quit" in result.stderr


def test_config_show_keymap_output_is_sortable(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    result = _run(
        "config",
        "show-keymap",
        env_overrides={"SQLIT_SETTINGS_PATH": str(settings)},
    )
    assert result.returncode == 0
    # No ANSI escape codes — pipe-friendly plain stdout.
    assert "\x1b[" not in result.stdout
    # Pane-focus rows appear before any non-whitelisted action rows.
    lines = result.stdout.splitlines()
    action_order = []
    for ln in lines[2:]:  # skip header + separator
        parts = ln.split()
        if len(parts) >= 2:
            action_order.append(parts[1])
    focus_idx = [
        i for i, a in enumerate(action_order)
        if a in {"focus_explorer", "focus_query", "focus_results"}
    ]
    others_idx = [
        i for i, a in enumerate(action_order)
        if a not in {"focus_explorer", "focus_query", "focus_results"}
    ]
    assert focus_idx and others_idx
    assert max(focus_idx) < min(others_idx)
