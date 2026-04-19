"""Load a user-supplied keymap provider at startup.

Setting the env var ``SQLIT_KEYMAP_MODULE`` to a Python module path lets a
user customize keybindings without forking the app. The referenced module
must import :mod:`sqlit.core.keymap` (``KeymapProvider``,
``DefaultKeymapProvider``, ``set_keymap``) and call ``set_keymap(...)`` at
import time — or expose a top-level callable named ``install_keymap()`` that
does the same. See ``docs/demos`` for examples once one exists.

This is deliberately a programmatic escape hatch (matching how sqlit
extends via provider packages and mock adapters) rather than a declarative
TOML settings file — consistent with the project's "no preferences" ethos.
"""

from __future__ import annotations

import importlib
import os
import sys


def bootstrap_user_keymap(env_var: str = "SQLIT_KEYMAP_MODULE") -> None:
    """Import the user's keymap module if ``env_var`` is set.

    Silent no-op when the env var is unset. Any ImportError or callable
    failure is surfaced on stderr but must not crash the TUI — we fall back
    to the default keymap in that case.
    """
    module_path = os.environ.get(env_var, "").strip()
    if not module_path:
        return

    try:
        module = importlib.import_module(module_path)
    except Exception as exc:  # surface any import failure
        print(
            f"[sqlit] Failed to import {env_var}={module_path!r}: {exc}",
            file=sys.stderr,
        )
        return

    install = getattr(module, "install_keymap", None)
    if callable(install):
        try:
            install()
        except Exception as exc:
            print(
                f"[sqlit] {module_path}.install_keymap() raised: {exc}",
                file=sys.stderr,
            )
