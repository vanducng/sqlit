"""CLI subcommand handlers for ``sqlit config ...``."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def resolve_editor() -> str | None:
    """Pick an editor command: $VISUAL → $EDITOR → `vi` on PATH."""
    for env in ("VISUAL", "EDITOR"):
        value = os.environ.get(env, "").strip()
        if value:
            return value
    if shutil.which("vi"):
        return "vi"
    return None


def run_edit() -> int:
    """Open settings.json in the user's editor, creating it if missing."""
    from sqlit.domains.shell.store.settings import SettingsStore

    path = SettingsStore.get_instance().file_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}\n")
    editor = resolve_editor()
    if editor is None:
        print("No editor found. Set $EDITOR or $VISUAL.", file=sys.stderr)
        return 1
    return subprocess.run([editor, str(path)]).returncode


def run_show_keymap() -> int:
    """Print the resolved primary keymap, flagging user overrides with ``*``."""
    from sqlit.core.configurable_keymap import (
        ConfigurableKeymapProvider,
        load_overrides_from_settings,
    )
    from sqlit.core.keymap import REBINDABLE_ACTIONS, DefaultKeymapProvider

    overrides = load_overrides_from_settings()
    provider = (
        ConfigurableKeymapProvider(overrides)
        if overrides
        else DefaultKeymapProvider()
    )
    rows: list[tuple[str, str, str, str]] = [
        (k.key, k.action, k.context or "", "*" if k.action in overrides else "")
        for k in provider.get_action_keys()
        if k.primary
    ]
    rows.sort(key=lambda r: (r[1] not in REBINDABLE_ACTIONS, r[1]))
    _print_table(rows, ("KEY", "ACTION", "CONTEXT", "OVERRIDDEN"))
    return 0


def _print_table(
    rows: list[tuple[str, str, str, str]],
    headers: tuple[str, str, str, str],
) -> None:
    widths = [
        max(len(h), *(len(str(r[i])) for r in rows)) if rows else len(h)
        for i, h in enumerate(headers)
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for r in rows:
        print(fmt.format(*r))
