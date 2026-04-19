"""Validate keymap and leader actions against the app surface."""

from __future__ import annotations

from typing import Any

from sqlit.core.input_context import InputContext
from sqlit.core.keymap import get_keymap
from sqlit.core.leader_commands import get_leader_commands

# Named guards that `ChordDef.guard` may reference. Kept here (not on a
# separate engine) because the chord dispatcher is currently inlined in
# QueryTextArea — this validator just checks the name is known.
KNOWN_CHORD_GUARDS: frozenset[str] = frozenset({
    "not_autocomplete_visible",
    "has_connection",
    "query_executing",
})


def evaluate_chord_guard(guard: str | None, ctx: InputContext) -> bool:
    """Evaluate a named ChordDef guard against the current input context.

    Unknown guard names fail closed so typos never allow a chord to fire.
    `validate_actions()` flags unknown names at startup.
    """
    if guard is None:
        return True
    if guard == "not_autocomplete_visible":
        return not ctx.autocomplete_visible
    if guard == "has_connection":
        return ctx.has_connection
    if guard == "query_executing":
        return ctx.query_executing
    return False


def validate_actions(app: Any) -> list[str]:
    missing: set[str] = set()

    for action_key in get_keymap().get_action_keys():
        action_name = f"action_{action_key.action}"
        if not hasattr(app, action_name):
            missing.add(action_name)

    for menu in ("leader", "delete", "yank", "change"):
        for cmd in get_leader_commands(menu):
            action_name = f"action_{cmd.binding_action}"
            if not hasattr(app, action_name):
                missing.add(action_name)

    for chord in get_keymap().get_chords():
        action_name = f"action_{chord.action}"
        if not hasattr(app, action_name):
            missing.add(action_name)
        if chord.guard is not None and chord.guard not in KNOWN_CHORD_GUARDS:
            missing.add(f"chord_guard:{chord.guard}")

    return sorted(missing)
