"""User-configurable keymap provider.

Subclass of ``DefaultKeymapProvider`` that rewrites primary bindings for the
whitelisted set of rebindable actions (see ``REBINDABLE_ACTIONS``) based on a
dict loaded from ``settings.json``. Everything outside the whitelist — chords,
leader menus, vim motions — stays at its default binding by design.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import Any

from sqlit.core.keymap import (
    REBINDABLE_ACTIONS,
    ActionKeyDef,
    DefaultKeymapProvider,
)
from sqlit.shared.core.debug_events import emit_debug_event


def _warn(message: str) -> None:
    print(f"[sqlit] keymap override: {message}", file=sys.stderr)


def load_overrides_from_settings() -> dict[str, Any]:
    """Read the raw ``keymap.overrides`` dict from ``settings.json``.

    Tolerant of malformed top-level sections: a non-dict ``keymap`` value or
    a non-dict ``overrides`` value returns ``{}`` with a stderr warning
    rather than crashing startup.
    """
    from sqlit.domains.shell.store.settings import SettingsStore

    keymap_section = SettingsStore.get_instance().get("keymap", {})
    if not isinstance(keymap_section, dict):
        _warn(f"ignoring non-dict 'keymap' section: {type(keymap_section).__name__}")
        return {}
    overrides = keymap_section.get("overrides", {})
    if not isinstance(overrides, dict):
        _warn(
            f"ignoring non-dict 'keymap.overrides' section: "
            f"{type(overrides).__name__}"
        )
        return {}
    return overrides


def _validate_overrides(raw: Any) -> dict[str, str]:
    """Filter ``raw`` to a clean ``{action: key}`` dict.

    Emits stderr warnings and drops entries that are not on the whitelist,
    not string-keyed, or have a non-string / empty value.
    """
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, str] = {}
    for action, key in raw.items():
        if not isinstance(action, str):
            _warn(f"dropping non-string action {action!r}")
            continue
        if action not in REBINDABLE_ACTIONS:
            _warn(
                f"action {action!r} is not rebindable "
                f"(allowed: {sorted(REBINDABLE_ACTIONS)})"
            )
            continue
        if not isinstance(key, str) or not key.strip():
            _warn(f"dropping malformed override for {action!r}: {key!r}")
            continue
        clean[action] = key.strip()
    return clean


class ConfigurableKeymapProvider(DefaultKeymapProvider):
    """Keymap provider that applies user-supplied overrides on top of the default."""

    def __init__(self, overrides: Any) -> None:
        super().__init__()
        self._overrides: dict[str, str] = _validate_overrides(overrides)

    @property
    def applied_overrides(self) -> dict[str, str]:
        """Overrides that passed validation and are actually in effect."""
        return dict(self._overrides)

    def _build_action_keys(self) -> list[ActionKeyDef]:
        base = super()._build_action_keys()
        if not self._overrides:
            return base

        target_actions = set(self._overrides.keys())
        # Resolve the context of each overriding action from the default
        # keymap. Collision detection is scoped to that same context — a
        # pane-focus key reuse in an unrelated context (e.g. `q` inside the
        # value-view modal) is not a real conflict.
        action_context: dict[str, str | None] = {}
        for entry in base:
            if entry.primary and entry.action in target_actions:
                action_context.setdefault(entry.action, entry.context)
        # key -> set of contexts where that key is displacing a default
        displace_contexts: dict[str, set[str | None]] = {}
        for action, key in self._overrides.items():
            ctx = action_context.get(action)
            displace_contexts.setdefault(key, set()).add(ctx)

        result: list[ActionKeyDef] = []
        for entry in base:
            if entry.primary and entry.action in target_actions:
                new_key = self._overrides[entry.action]
                emit_debug_event(
                    "keymap_override",
                    category="keybinding",
                    action=entry.action,
                    old_key=entry.key,
                    new_key=new_key,
                )
                result.append(replace(entry, key=new_key))
                continue
            if (
                entry.primary
                and entry.action not in target_actions
                and entry.key in displace_contexts
                and entry.context in displace_contexts[entry.key]
            ):
                _warn(
                    f"displaced default binding {entry.key!r} "
                    f"(action={entry.action!r}, context={entry.context!r})"
                )
                continue
            result.append(entry)

        # Inject entries for whitelisted actions that ship without a default key.
        existing_actions = {e.action for e in result if e.primary}
        for action, key in self._overrides.items():
            if action in existing_actions:
                continue
            emit_debug_event(
                "keymap_override",
                category="keybinding",
                action=action,
                old_key=None,
                new_key=key,
            )
            result.append(ActionKeyDef(key=key, action=action, context=None, primary=True))
        return result
