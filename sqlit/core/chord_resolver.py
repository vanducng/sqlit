"""Resolve timed key-sequence chords (e.g. vim 'jk' -> <esc>).

Chord definitions live on the KeymapProvider (`get_chords()`); the resolver
is a stateful state-machine that tracks one pending prefix at a time and
fires a match when the sequence completes within the per-chord timeout while
the declared binding context is active.

Design choices (kept deliberately small):

* Trailing-mode only. Each key keeps its normal side-effect (e.g. insertion
  into a TextArea). On completion the caller is told how many preceding
  characters to roll back (`ChordMatch.delete_chars`). Leading-mode chords
  (swallow the first key) are covered by the existing leader machinery.
* Single pending buffer, singleton resolver. The TUI has one active focus at
  a time so this is sufficient and avoids bookkeeping per-context buffers.
* Context/guard changes reset the buffer — a chord started in INSERT mode
  never completes after the user has switched back to NORMAL.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlit.core.binding_contexts import get_binding_contexts
from sqlit.core.input_context import InputContext
from sqlit.core.keymap import get_keymap

# Named guards for ChordDef.guard. Keep this list minimal and explicit.
CHORD_GUARDS: dict[str, Callable[[InputContext], bool]] = {
    "not_autocomplete_visible": lambda ctx: not ctx.autocomplete_visible,
    "has_connection": lambda ctx: ctx.has_connection,
    "query_executing": lambda ctx: ctx.query_executing,
}


@dataclass(frozen=True)
class ChordMatch:
    """Result of a completed chord.

    `action` — action name to dispatch (without the "action_" prefix).
    `delete_chars` — how many previously-handled keys the caller should
        roll back from whatever buffer they wrote to. For a 2-key chord in
        trailing mode this is typically `len(sequence) - 1` (the final key
        is assumed NOT to have been inserted yet — see `ChordResolver.feed`).
    """

    action: str
    delete_chars: int


class ChordResolver:
    """Stateful resolver for trailing-mode key sequences.

    Call `feed(key, ctx)` *before* the key takes its side-effect. If the
    result is a `ChordMatch`, the caller should:
      1. suppress the current key (do not insert it),
      2. delete `match.delete_chars` previously-inserted characters from its
         buffer, and
      3. dispatch `action_{match.action}` on the app.
    Otherwise the caller proceeds normally; the resolver has updated its
    internal state (and may be waiting for a follow-up key).
    """

    def __init__(self) -> None:
        self._buffer: list[str] = []
        self._deadline: float = 0.0
        self._context_snapshot: frozenset[str] = frozenset()

    def reset(self) -> None:
        self._buffer.clear()
        self._deadline = 0.0
        self._context_snapshot = frozenset()

    def feed(self, key: str, ctx: InputContext) -> ChordMatch | None:
        now = time.monotonic()
        active_contexts = frozenset(get_binding_contexts(ctx))

        # Drop a stale pending buffer if we timed out or switched context.
        if self._buffer and (
            now > self._deadline or self._context_snapshot != active_contexts
        ):
            self.reset()

        # Candidate chords: any whose context is currently active and whose
        # guard (if any) currently allows firing.
        candidates = [
            c for c in get_keymap().get_chords()
            if c.context in active_contexts and _guard_ok(c.guard, ctx)
        ]
        if not candidates:
            # Nothing to match — make sure state is clean.
            if self._buffer:
                self.reset()
            return None

        # Tentatively extend the buffer with the new key.
        tentative = [*self._buffer, key]

        # Full match?
        for chord in candidates:
            if list(chord.sequence) == tentative:
                self.reset()
                return ChordMatch(
                    action=chord.action,
                    delete_chars=len(chord.sequence) - 1,
                )

        # Prefix of a longer chord? Keep buffer alive with the smallest
        # timeout among the matching prefixes.
        prefix_timeouts = [
            c.timeout_ms
            for c in candidates
            if len(c.sequence) > len(tentative)
            and list(c.sequence[: len(tentative)]) == tentative
        ]
        if prefix_timeouts:
            self._buffer = tentative
            self._deadline = now + (min(prefix_timeouts) / 1000.0)
            self._context_snapshot = active_contexts
        else:
            # Not a prefix of anything — drop pending state.
            self.reset()

        return None


def _guard_ok(guard: str | None, ctx: InputContext) -> bool:
    if guard is None:
        return True
    fn = CHORD_GUARDS.get(guard)
    if fn is None:
        # Unknown guard name — fail closed so typos don't silently fire.
        return False
    return fn(ctx)


# Singleton resolver (mirrors the get_keymap() pattern).
_resolver: ChordResolver | None = None


def get_chord_resolver() -> ChordResolver:
    global _resolver
    if _resolver is None:
        _resolver = ChordResolver()
    return _resolver


def reset_chord_resolver() -> None:
    """Drop any pending state (used by tests and mode-change hooks)."""
    global _resolver
    _resolver = None
