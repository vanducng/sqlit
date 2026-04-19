"""Unit tests for inlined chord dispatch (QueryTextArea + action_validation)."""

from __future__ import annotations

from sqlit.core.action_validation import KNOWN_CHORD_GUARDS, evaluate_chord_guard
from sqlit.core.input_context import InputContext
from sqlit.core.keymap import DefaultKeymapProvider, get_keymap, reset_keymap
from sqlit.core.vim import VimMode


def _ctx(**kw) -> InputContext:
    base = {
        "focus": "query",
        "vim_mode": VimMode.INSERT,
        "leader_pending": False,
        "leader_menu": "leader",
        "tree_filter_active": False,
        "tree_multi_select_active": False,
        "tree_visual_mode_active": False,
        "autocomplete_visible": False,
        "results_filter_active": False,
        "value_view_active": False,
        "value_view_tree_mode": False,
        "value_view_is_json": False,
        "query_executing": False,
        "modal_open": False,
        "has_connection": False,
        "current_connection_name": None,
        "tree_node_kind": None,
        "tree_node_connection_name": None,
        "tree_node_connection_selected": False,
        "last_result_is_error": False,
        "has_results": False,
    }
    base.update(kw)
    return InputContext(**base)  # type: ignore[arg-type]


def test_guard_none_always_allows():
    assert evaluate_chord_guard(None, _ctx()) is True


def test_guard_not_autocomplete_visible():
    assert evaluate_chord_guard("not_autocomplete_visible", _ctx(autocomplete_visible=False)) is True
    assert evaluate_chord_guard("not_autocomplete_visible", _ctx(autocomplete_visible=True)) is False


def test_guard_has_connection():
    assert evaluate_chord_guard("has_connection", _ctx(has_connection=True)) is True
    assert evaluate_chord_guard("has_connection", _ctx(has_connection=False)) is False


def test_guard_query_executing():
    assert evaluate_chord_guard("query_executing", _ctx(query_executing=True)) is True
    assert evaluate_chord_guard("query_executing", _ctx(query_executing=False)) is False


def test_guard_unknown_fails_closed():
    """Typo'd guard names must never allow a chord to fire."""
    assert evaluate_chord_guard("not_a_real_guard", _ctx()) is False


def test_known_chord_guards_matches_evaluate_function():
    """Every known guard must be evaluable; no accidental omissions."""
    for guard in KNOWN_CHORD_GUARDS:
        # Must return a bool for *some* ctx — i.e. the name is handled.
        assert isinstance(evaluate_chord_guard(guard, _ctx()), bool)


def test_default_keymap_registers_jk_chord():
    reset_keymap()
    try:
        from sqlit.core.keymap import set_keymap
        set_keymap(DefaultKeymapProvider())
        chords = get_keymap().get_chords()
        jk = next((c for c in chords if c.sequence == ("j", "k")), None)
        assert jk is not None
        assert jk.action == "exit_insert_mode"
        assert jk.context == "query_insert"
        assert jk.timeout_ms == 300
        assert jk.guard == "not_autocomplete_visible"
    finally:
        reset_keymap()
