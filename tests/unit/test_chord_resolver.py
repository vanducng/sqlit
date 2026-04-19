"""Unit tests for the chord resolver engine."""

from __future__ import annotations

import time

import pytest

from sqlit.core.chord_resolver import (
    ChordResolver,
    get_chord_resolver,
    reset_chord_resolver,
)
from sqlit.core.input_context import InputContext
from sqlit.core.keymap import (
    ActionKeyDef,
    ChordDef,
    DefaultKeymapProvider,
    KeymapProvider,
    LeaderCommandDef,
    reset_keymap,
    set_keymap,
)
from sqlit.core.vim import VimMode


class _StubProvider(KeymapProvider):
    def __init__(self, chords: list[ChordDef]) -> None:
        self._chords = chords

    def get_leader_commands(self) -> list[LeaderCommandDef]:
        return []

    def get_action_keys(self) -> list[ActionKeyDef]:
        return []

    def get_chords(self) -> list[ChordDef]:
        return list(self._chords)


def _ctx(*, focus: str = "query", vim_mode: VimMode = VimMode.INSERT,
         autocomplete: bool = False) -> InputContext:
    return InputContext(
        focus=focus,
        vim_mode=vim_mode,
        leader_pending=False,
        leader_menu="leader",
        tree_filter_active=False,
        tree_multi_select_active=False,
        tree_visual_mode_active=False,
        autocomplete_visible=autocomplete,
        results_filter_active=False,
        value_view_active=False,
        value_view_tree_mode=False,
        value_view_is_json=False,
        query_executing=False,
        modal_open=False,
        has_connection=False,
        current_connection_name=None,
        tree_node_kind=None,
        tree_node_connection_name=None,
        tree_node_connection_selected=False,
        last_result_is_error=False,
        has_results=False,
    )


@pytest.fixture(autouse=True)
def _reset_state():
    reset_keymap()
    reset_chord_resolver()
    yield
    reset_keymap()
    reset_chord_resolver()


def test_jk_sequence_fires_in_insert_mode():
    set_keymap(_StubProvider([
        ChordDef(("j", "k"), "exit_insert_mode", "query_insert", 300),
    ]))
    r = ChordResolver()
    assert r.feed("j", _ctx()) is None
    match = r.feed("k", _ctx())
    assert match is not None
    assert match.action == "exit_insert_mode"
    assert match.delete_chars == 1


def test_jk_does_not_fire_in_normal_mode():
    set_keymap(_StubProvider([
        ChordDef(("j", "k"), "exit_insert_mode", "query_insert", 300),
    ]))
    r = ChordResolver()
    assert r.feed("j", _ctx(vim_mode=VimMode.NORMAL)) is None
    assert r.feed("k", _ctx(vim_mode=VimMode.NORMAL)) is None


def test_jk_guard_blocks_when_autocomplete_visible():
    set_keymap(_StubProvider([
        ChordDef(("j", "k"), "exit_insert_mode", "query_insert", 300,
                 guard="not_autocomplete_visible"),
    ]))
    r = ChordResolver()
    assert r.feed("j", _ctx(autocomplete=True)) is None
    assert r.feed("k", _ctx(autocomplete=True)) is None


def test_timeout_drops_pending_prefix(monkeypatch):
    set_keymap(_StubProvider([
        ChordDef(("j", "k"), "exit_insert_mode", "query_insert", 50),
    ]))
    r = ChordResolver()

    t = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: t[0])
    assert r.feed("j", _ctx()) is None
    t[0] += 1.0  # simulate 1 full second passing — beyond timeout
    assert r.feed("k", _ctx()) is None


def test_non_prefix_key_resets_buffer():
    set_keymap(_StubProvider([
        ChordDef(("j", "k"), "exit_insert_mode", "query_insert", 300),
    ]))
    r = ChordResolver()
    assert r.feed("j", _ctx()) is None
    # 'x' is not a prefix of any chord — must drop pending 'j'
    assert r.feed("x", _ctx()) is None
    # A later 'k' alone must not fire
    assert r.feed("k", _ctx()) is None


def test_context_switch_drops_pending_prefix():
    set_keymap(_StubProvider([
        ChordDef(("j", "k"), "exit_insert_mode", "query_insert", 300),
    ]))
    r = ChordResolver()
    assert r.feed("j", _ctx()) is None
    # Switch to NORMAL mode — the INSERT-mode chord must no longer fire
    assert r.feed("k", _ctx(vim_mode=VimMode.NORMAL)) is None


def test_three_key_chord():
    set_keymap(_StubProvider([
        ChordDef(("a", "b", "c"), "three_key_action", "query_insert", 300),
    ]))
    r = ChordResolver()
    assert r.feed("a", _ctx()) is None
    assert r.feed("b", _ctx()) is None
    match = r.feed("c", _ctx())
    assert match is not None
    assert match.delete_chars == 2


def test_default_keymap_registers_jk_chord():
    set_keymap(DefaultKeymapProvider())
    from sqlit.core.keymap import get_keymap
    chords = get_keymap().get_chords()
    assert any(c.sequence == ("j", "k") for c in chords)


def test_get_chord_resolver_is_singleton():
    a = get_chord_resolver()
    b = get_chord_resolver()
    assert a is b
    reset_chord_resolver()
    c = get_chord_resolver()
    assert c is not a
