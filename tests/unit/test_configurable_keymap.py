"""Tests for ConfigurableKeymapProvider — user-overridable pane-focus bindings."""

from __future__ import annotations

import pytest

from sqlit.core.configurable_keymap import ConfigurableKeymapProvider
from sqlit.core.keymap import REBINDABLE_ACTIONS, ActionKeyDef, DefaultKeymapProvider


def _primary(keys: list[ActionKeyDef], action: str) -> ActionKeyDef | None:
    for k in keys:
        if k.action == action and k.primary:
            return k
    return None


def _all_for_action(keys: list[ActionKeyDef], action: str) -> list[ActionKeyDef]:
    return [k for k in keys if k.action == action]


def test_rebindable_actions_contains_pane_focus() -> None:
    assert {"focus_explorer", "focus_query", "focus_results"}.issubset(REBINDABLE_ACTIONS)


def test_rebindable_actions_contains_resize_pane() -> None:
    assert {
        "resize_pane_left",
        "resize_pane_right",
        "resize_pane_up",
        "resize_pane_down",
    }.issubset(REBINDABLE_ACTIONS)


def test_override_only_rebindable_injects_entry() -> None:
    """resize_pane_* actions ship without a default key — overrides must inject a fresh entry."""
    provider = ConfigurableKeymapProvider({"resize_pane_right": "ctrl+right"})
    keys = provider.get_action_keys()
    entry = _primary(keys, "resize_pane_right")
    assert entry is not None
    assert entry.key == "ctrl+right"
    assert entry.context is None  # injected entries are global


def test_override_only_rebindable_no_default_entry() -> None:
    """Without an override, resize_pane_* actions produce no entry."""
    provider = ConfigurableKeymapProvider({})
    keys = provider.get_action_keys()
    assert _primary(keys, "resize_pane_right") is None
    assert _primary(keys, "resize_pane_left") is None


def test_injected_binding_warns_on_collision(capsys: pytest.CaptureFixture[str]) -> None:
    """Injecting an override-only action onto a key already bound elsewhere must warn."""
    # `q` is bound to focus_query (navigation context); injecting resize_pane_right
    # globally onto `q` would silently shadow it. Expect a stderr warning.
    provider = ConfigurableKeymapProvider({"resize_pane_right": "q"})
    keys = provider.get_action_keys()
    assert _primary(keys, "resize_pane_right") is not None
    err = capsys.readouterr().err
    assert "shadows" in err
    assert "resize_pane_right" in err


def test_injected_binding_no_warning_when_key_unused(capsys: pytest.CaptureFixture[str]) -> None:
    """A user-only key (e.g., ctrl+right) that isn't in any default binding must not warn."""
    provider = ConfigurableKeymapProvider({"resize_pane_right": "ctrl+right"})
    provider.get_action_keys()
    err = capsys.readouterr().err
    assert "shadows" not in err


def test_no_overrides_behaves_like_default() -> None:
    default_keys = DefaultKeymapProvider().get_action_keys()
    provider = ConfigurableKeymapProvider({})
    assert provider.get_action_keys() == default_keys


def test_missing_keymap_section_is_noop() -> None:
    default_keys = DefaultKeymapProvider().get_action_keys()
    assert ConfigurableKeymapProvider({}).get_action_keys() == default_keys


def test_valid_override_rebinds_primary_entry(capsys: pytest.CaptureFixture[str]) -> None:
    provider = ConfigurableKeymapProvider({"focus_explorer": "1"})
    keys = provider.get_action_keys()
    entry = _primary(keys, "focus_explorer")
    assert entry is not None
    assert entry.key == "1"
    assert entry.context == "navigation"
    # No leftover default `e` → focus_explorer binding
    assert not any(k.key == "e" and k.action == "focus_explorer" for k in keys)


def test_all_three_pane_focus_overrides_together() -> None:
    provider = ConfigurableKeymapProvider(
        {"focus_explorer": "1", "focus_query": "2", "focus_results": "3"}
    )
    keys = provider.get_action_keys()
    assert _primary(keys, "focus_explorer").key == "1"  # type: ignore[union-attr]
    assert _primary(keys, "focus_query").key == "2"  # type: ignore[union-attr]
    assert _primary(keys, "focus_results").key == "3"  # type: ignore[union-attr]


def test_secondary_aliases_untouched() -> None:
    # Synthesize a secondary alias on top of the default, then override the
    # primary action — the secondary alias must survive.
    class _WithAlias(DefaultKeymapProvider):
        def _build_action_keys(self) -> list[ActionKeyDef]:
            base = super()._build_action_keys()
            base.append(
                ActionKeyDef("E", "focus_explorer", "navigation", primary=False)
            )
            return base

    class _ConfigurableAlias(ConfigurableKeymapProvider, _WithAlias):
        pass

    provider = _ConfigurableAlias({"focus_explorer": "1"})
    keys = provider.get_action_keys()
    for_action = _all_for_action(keys, "focus_explorer")
    primary = [k for k in for_action if k.primary]
    secondary = [k for k in for_action if not k.primary]
    assert len(primary) == 1 and primary[0].key == "1"
    assert any(k.key == "E" for k in secondary)


def test_whitelist_enforcement(capsys: pytest.CaptureFixture[str]) -> None:
    provider = ConfigurableKeymapProvider({"quit": "Q"})
    keys = provider.get_action_keys()
    # quit binding unchanged (still ctrl+q primary)
    entry = _primary(keys, "quit")
    assert entry is not None and entry.key == "ctrl+q"
    err = capsys.readouterr().err
    assert "quit" in err


def test_unknown_action_name(capsys: pytest.CaptureFixture[str]) -> None:
    provider = ConfigurableKeymapProvider({"focus_expleror": "1"})
    keys = provider.get_action_keys()
    entry = _primary(keys, "focus_explorer")
    assert entry is not None and entry.key == "e"
    err = capsys.readouterr().err
    assert "focus_expleror" in err


def test_malformed_override_entry(capsys: pytest.CaptureFixture[str]) -> None:
    provider = ConfigurableKeymapProvider(
        {"focus_explorer": "", "focus_query": 42, "focus_results": None}
    )
    keys = provider.get_action_keys()
    # All three stay at defaults
    assert _primary(keys, "focus_explorer").key == "e"  # type: ignore[union-attr]
    assert _primary(keys, "focus_query").key == "q"  # type: ignore[union-attr]
    assert _primary(keys, "focus_results").key == "r"  # type: ignore[union-attr]
    err = capsys.readouterr().err
    assert "focus_explorer" in err
    assert "focus_query" in err
    assert "focus_results" in err


def test_collision_with_other_binding(capsys: pytest.CaptureFixture[str]) -> None:
    # focus_explorer -> q displaces default focus_query primary binding (also q)
    provider = ConfigurableKeymapProvider({"focus_explorer": "q"})
    keys = provider.get_action_keys()
    fe = _primary(keys, "focus_explorer")
    assert fe is not None and fe.key == "q"
    # focus_query's default primary was displaced
    fq_primary = _primary(keys, "focus_query")
    assert fq_primary is None
    err = capsys.readouterr().err
    assert "focus_query" in err


def test_collision_resolves_when_both_rebind(capsys: pytest.CaptureFixture[str]) -> None:
    # Swap: both rebound → no collision warning for the swap targets
    provider = ConfigurableKeymapProvider(
        {"focus_explorer": "q", "focus_query": "e"}
    )
    keys = provider.get_action_keys()
    assert _primary(keys, "focus_explorer").key == "q"  # type: ignore[union-attr]
    assert _primary(keys, "focus_query").key == "e"  # type: ignore[union-attr]
    err = capsys.readouterr().err
    # No displaced-warning for focus_explorer or focus_query since both were
    # themselves rebound.
    assert "displaced" not in err.lower()
