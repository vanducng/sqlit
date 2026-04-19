"""Bindings + insert-mode action parity for run-statement-under-cursor.

Phase 1 of plans/260419-0459-run-statement-under-cursor.

Locks in the behaviour change: Enter (normal) and Ctrl+Enter (insert) must run
only the statement under the cursor, and `<space>ga` must exist as a run-all
alias.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlit.core.keymap import DefaultKeymapProvider
from sqlit.domains.query.state.autocomplete_active import AutocompleteActiveState
from sqlit.domains.query.state.query_insert import QueryInsertModeState
from sqlit.domains.query.ui.mixins.query_execution import QueryExecutionMixin


def _keymap() -> DefaultKeymapProvider:
    return DefaultKeymapProvider()


class TestEnterBindings:
    def test_enter_runs_single_statement_in_query_normal(self) -> None:
        km = _keymap()
        actions = [
            ak.action
            for ak in km.get_action_keys()
            if ak.key == "enter" and ak.context == "query_normal"
        ]
        assert actions == ["execute_single_statement"], actions

    def test_ctrl_enter_runs_single_statement_in_query_insert(self) -> None:
        km = _keymap()
        actions = [
            ak.action
            for ak in km.get_action_keys()
            if ak.key == "ctrl+enter" and ak.context == "query_insert"
        ]
        assert actions == ["execute_single_statement_insert"], actions

    def test_execute_query_not_bound_to_enter_in_query_normal(self) -> None:
        km = _keymap()
        enter_actions = {
            ak.action
            for ak in km.get_action_keys()
            if ak.key == "enter" and ak.context == "query_normal"
        }
        assert "execute_query" not in enter_actions

    def test_execute_query_still_reachable_via_leader_ga(self) -> None:
        km = _keymap()
        leader_pairs = [
            (cmd.key, cmd.action)
            for cmd in km.get_leader_commands()
            if cmd.menu == "g"
        ]
        assert ("a", "execute_query") in leader_pairs, leader_pairs

    def test_leader_gr_still_runs_all_for_backwards_compat(self) -> None:
        km = _keymap()
        leader_pairs = [
            (cmd.key, cmd.action)
            for cmd in km.get_leader_commands()
            if cmd.menu == "g"
        ]
        assert ("r", "execute_query") in leader_pairs, leader_pairs


class TestInsertModeState:
    def test_allows_execute_single_statement_insert(self) -> None:
        state = QueryInsertModeState()
        assert "execute_single_statement_insert" in state._actions

    def test_autocomplete_active_allows_execute_single_statement_insert(self) -> None:
        # Ctrl+Enter must still run the statement at cursor while the
        # autocomplete popup is visible, otherwise the binding silently breaks
        # the moment the user starts typing.
        state = AutocompleteActiveState()
        assert "execute_single_statement_insert" in state._actions


class _MockHost(QueryExecutionMixin):
    def __init__(self) -> None:
        self.current_connection = MagicMock()
        self.current_provider = MagicMock()
        self.query_input = MagicMock()
        self.query_input.cursor_location = (0, 12)
        self.query_input.text = "SELECT 1; SELECT 2; SELECT 3"
        self.notify = MagicMock()
        self.run_worker = MagicMock()
        self.query_executing = False
        self._query_worker = None
        self._query_spinner = None
        self.services = MagicMock()
        self.services.runtime.query_alert_mode = 0

    def _start_query_spinner(self) -> None:
        self.query_executing = True

    def _run_query_async(self, query: str, keep_insert_mode: bool) -> str:
        # Capture the flag so tests can assert on it.
        self._last_keep_insert_mode = keep_insert_mode
        self._last_query = query
        return "mock_coro"


class TestInsertActionParity:
    def test_action_execute_single_statement_insert_triggers_worker(self) -> None:
        host = _MockHost()
        host.action_execute_single_statement_insert()
        host.run_worker.assert_called_once()
        assert host.query_executing is True
        assert getattr(host, "_last_keep_insert_mode", None) is True
        assert host._last_query == "SELECT 2"

    def test_action_execute_single_statement_keeps_existing_normal_behaviour(self) -> None:
        host = _MockHost()
        host.action_execute_single_statement()
        host.run_worker.assert_called_once()
        assert getattr(host, "_last_keep_insert_mode", None) is False
        assert host._last_query == "SELECT 2"
