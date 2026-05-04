"""Tests for results transpose pure helpers and action handlers."""

from __future__ import annotations

import pytest
from textual.coordinate import Coordinate

from sqlit.domains.results.ui.mixins.results import (
    MAX_TRANSPOSE_ROWS,
    ResultsMixin,
    _compute_transposed_layout,
    _transpose_coord,
)


class TestTransposeCoord:
    def test_label_col_returns_none(self) -> None:
        assert _transpose_coord(0, 0) is None
        assert _transpose_coord(5, 0) is None

    @pytest.mark.parametrize(
        "dr,dc,expected",
        [
            (0, 1, (0, 0)),  # first original row, first original col
            (0, 2, (1, 0)),
            (0, 3, (2, 0)),
            (1, 1, (0, 1)),
            (2, 1, (0, 2)),
            (2, 3, (2, 2)),
        ],
    )
    def test_maps_data_cells(
        self, dr: int, dc: int, expected: tuple[int, int]
    ) -> None:
        assert _transpose_coord(dr, dc) == expected


class TestComputeTransposedLayout:
    def test_shape(self) -> None:
        columns = ["a", "b", "c"]
        rows: list[tuple] = [(1, 2, 3), (4, 5, 6)]
        t_columns, t_rows = _compute_transposed_layout(columns, rows)
        assert t_columns == ["column", "1", "2"]
        assert t_rows == [("a", 1, 4), ("b", 2, 5), ("c", 3, 6)]

    def test_empty_rows(self) -> None:
        t_columns, t_rows = _compute_transposed_layout(["a", "b"], [])
        assert t_columns == ["column"]
        assert t_rows == []

    def test_empty_columns(self) -> None:
        t_columns, t_rows = _compute_transposed_layout([], [(1, 2), (3, 4)])
        assert t_columns == ["column", "1", "2"]
        assert t_rows == []

    def test_single_row(self) -> None:
        t_columns, t_rows = _compute_transposed_layout(["a", "b"], [(1, 2)])
        assert t_columns == ["column", "1"]
        assert t_rows == [("a", 1), ("b", 2)]


def test_max_transpose_rows_constant_is_10() -> None:
    assert MAX_TRANSPOSE_ROWS == 10


# ---------------------------------------------------------------------------
# Action-level tests (Phase 3)
# ---------------------------------------------------------------------------


class _FakeTable:
    has_focus = False

    def __init__(
        self,
        rows: list[tuple],
        cursor: tuple[int, int] = (0, 0),
        cells: dict[tuple[int, int], object] | None = None,
    ) -> None:
        self._rows = rows
        self._cells = cells or {}
        self.cursor_coordinate = Coordinate(*cursor)
        self.row_count = len(rows)

    @property
    def cursor_row(self) -> int:
        return self.cursor_coordinate.row

    def get_row_at(self, row: int) -> tuple:
        return tuple(self._rows[row])

    def get_cell_at(self, coord: Coordinate) -> object:
        return self._cells.get((coord.row, coord.column))


class _FakeSection:
    def __init__(
        self,
        columns: list[str],
        rows: list[tuple],
        transposed: bool = False,
    ) -> None:
        self.result_columns = columns
        self.result_rows = rows
        self.transposed = transposed
        self.result_table_info: dict | None = None


class _FakeHost(ResultsMixin):
    """Minimal stand-in for ResultsMixinHost in unit tests."""

    def __init__(
        self,
        table: _FakeTable,
        columns: list[str],
        rows: list[tuple],
        *,
        stacked: bool = False,
        section: _FakeSection | None = None,
        transposed_single: bool = False,
    ) -> None:
        self._table = table
        self._columns = columns
        self._rows = rows
        self._stacked = stacked
        self._section = section
        self._transposed_single = transposed_single
        self._last_result_columns = list(columns)
        self._last_result_rows = list(rows)
        self.notifications: list[tuple[str, str]] = []
        self.copied: list[str] = []
        self.flashes: list[str] = []
        self._leader_cleared = 0
        self.query_input_text = ""

    # --- protocol stubs -----------------------------------------------------
    def _get_active_results_context(self):  # type: ignore[override]
        return self._table, list(self._columns), list(self._rows), self._stacked

    def _find_results_section(self, _widget):  # type: ignore[override]
        return self._section

    def notify(self, message: str, *, severity: str = "information", **_: object) -> None:
        self.notifications.append((message, severity))

    def _copy_text(self, text: str) -> bool:  # type: ignore[override]
        self.copied.append(text)
        return True

    def _flash_table_yank(self, _table, scope: str) -> None:  # type: ignore[override]
        self.flashes.append(scope)

    def _clear_leader_pending(self) -> None:
        self._leader_cleared += 1


class TestResolveActiveCell:
    def test_non_transposed_returns_cursor_passthrough(self) -> None:
        table = _FakeTable([(1, 2)], cursor=(0, 1))
        host = _FakeHost(table, ["a", "b"], [(1, 2)])
        assert host._resolve_active_cell(table, None) == (0, 1)

    def test_transposed_label_col_returns_none(self) -> None:
        table = _FakeTable([("a", 1), ("b", 2)], cursor=(0, 0))
        section = _FakeSection(["a", "b"], [(1, 2)], transposed=True)
        host = _FakeHost(table, ["a", "b"], [(1, 2)], stacked=True, section=section)
        assert host._resolve_active_cell(table, section) is None

    def test_transposed_data_cell_maps(self) -> None:
        table = _FakeTable([("a", 1), ("b", 2)], cursor=(1, 1))
        section = _FakeSection(["a", "b"], [(1, 2)], transposed=True)
        host = _FakeHost(table, ["a", "b"], [(1, 2)], stacked=True, section=section)
        assert host._resolve_active_cell(table, section) == (0, 1)

    def test_transposed_single_mode_uses_flag(self) -> None:
        table = _FakeTable([("a", 1)], cursor=(0, 1))
        host = _FakeHost(table, ["a", "b"], [(1, 2)], transposed_single=True)
        assert host._resolve_active_cell(table, None) == (0, 0)


class TestRyRowTransposed:
    def test_data_cell_yields_column_vector_tsv(self) -> None:
        # Transposed display: rows = [("a",1,4), ("b",2,5), ("c",3,6)]
        # Cursor on (dr=1, dc=2) → orig_col = dr = 1 (col "b"), orig_row = dc-1 = 1
        table = _FakeTable(
            [("a", 1, 4), ("b", 2, 5), ("c", 3, 6)],
            cursor=(1, 2),
        )
        section = _FakeSection(
            ["a", "b", "c"], [(1, 2, 3), (4, 5, 6)], transposed=True
        )
        host = _FakeHost(
            table, ["a", "b", "c"], [(1, 2, 3), (4, 5, 6)],
            stacked=True, section=section,
        )
        host.action_ry_row()
        assert host.copied == ["b\t2\t5"]
        assert host.flashes == ["row"]

    def test_label_col_copies_column_names(self) -> None:
        table = _FakeTable(
            [("a", 1, 4), ("b", 2, 5), ("c", 3, 6)],
            cursor=(1, 0),
        )
        section = _FakeSection(
            ["a", "b", "c"], [(1, 2, 3), (4, 5, 6)], transposed=True
        )
        host = _FakeHost(
            table, ["a", "b", "c"], [(1, 2, 3), (4, 5, 6)],
            stacked=True, section=section,
        )
        host.action_ry_row()
        assert host.copied == ["column\ta\tb\tc"]
        assert host.flashes == ["row"]

    def test_non_transposed_unchanged(self) -> None:
        table = _FakeTable([(1, 2), (3, 4)], cursor=(1, 0))
        host = _FakeHost(table, ["a", "b"], [(1, 2), (3, 4)])
        host.action_ry_row()
        assert host.copied == ["3\t4"]


class TestLabelColGuards:
    def test_edit_cell_label_col_flashes(self) -> None:
        table = _FakeTable(
            [("a", 1), ("b", 2)],
            cursor=(0, 0),
        )
        section = _FakeSection(["a", "b"], [(1, 2)], transposed=True)
        host = _FakeHost(
            table, ["a", "b"], [(1, 2)], stacked=True, section=section
        )
        host.action_edit_cell()
        assert host.notifications
        assert any("column label" in m.lower() for m, _ in host.notifications)

    def test_delete_row_label_col_flashes(self) -> None:
        table = _FakeTable(
            [("a", 1), ("b", 2)],
            cursor=(0, 0),
        )
        section = _FakeSection(["a", "b"], [(1, 2)], transposed=True)
        host = _FakeHost(
            table, ["a", "b"], [(1, 2)], stacked=True, section=section
        )
        host.action_delete_row()
        assert host.notifications
        assert any(
            "data column" in m.lower() or "column label" in m.lower()
            for m, _ in host.notifications
        )


# ---------------------------------------------------------------------------
# Registration / wiring checks (Phase 4)
# ---------------------------------------------------------------------------

class TestTransposeRegistration:
    def test_keymap_registers_t_for_transpose(self) -> None:
        from sqlit.core.keymap import DefaultKeymapProvider

        entries = [
            (e.key, e.action, e.context)
            for e in DefaultKeymapProvider().get_action_keys()
            if e.action == "toggle_results_transpose"
        ]
        assert ("t", "toggle_results_transpose", "results") in entries

    def test_results_focused_state_registers_transpose(self) -> None:
        from sqlit.domains.results.state.results_focused import ResultsFocusedState

        state = ResultsFocusedState()
        specs = state._actions
        assert "toggle_results_transpose" in specs
        spec = specs["toggle_results_transpose"]
        assert spec.display_label == "Transpose"
        assert spec.help_description is not None
        assert "10 rows" in spec.help_description

    def test_result_section_has_transposed_flag(self) -> None:
        from sqlit.shared.ui.widgets_stacked_results import ResultSection

        section = ResultSection("SELECT 1", 0)
        assert section.transposed is False


class TestTransposeFooterBinding:
    def _ctx(self, *, has_results: bool = True, is_error: bool = False):
        from sqlit.core.input_context import InputContext
        from sqlit.core.vim import VimMode

        return InputContext(
            focus="results",
            vim_mode=VimMode.NORMAL,
            leader_pending=False,
            leader_menu="",
            tree_filter_active=False,
            tree_multi_select_active=False,
            tree_visual_mode_active=False,
            autocomplete_visible=False,
            results_filter_active=False,
            value_view_active=False,
            value_view_tree_mode=False,
            value_view_is_json=False,
            query_executing=False,
            modal_open=False,
            has_connection=True,
            current_connection_name="c",
            tree_node_kind=None,
            tree_node_connection_name=None,
            tree_node_connection_selected=False,
            last_result_is_error=is_error,
            has_results=has_results,
        )

    def test_transpose_shown_in_footer_when_results_ok(self) -> None:
        from sqlit.domains.results.state.results_focused import ResultsFocusedState

        state = ResultsFocusedState()
        left, _right = state.get_display_bindings(self._ctx())
        actions = [b.action for b in left]
        assert "toggle_results_transpose" in actions
        binding = next(b for b in left if b.action == "toggle_results_transpose")
        assert binding.key == "t"
        assert binding.label == "Transpose"

    def test_transpose_hidden_on_error_result(self) -> None:
        from sqlit.domains.results.state.results_focused import ResultsFocusedState

        state = ResultsFocusedState()
        left, _right = state.get_display_bindings(self._ctx(is_error=True))
        actions = [b.action for b in left]
        assert "toggle_results_transpose" not in actions


class TestTransposeCap:
    def test_layout_caps_at_10_rows(self) -> None:
        # 20 rows -> display shows first 10 only
        columns = ["a", "b"]
        rows = [(i, i * 10) for i in range(20)]
        t_columns, t_rows = _compute_transposed_layout(
            columns, rows[:MAX_TRANSPOSE_ROWS]
        )
        # t_columns: "column" + 10 numeric labels
        assert len(t_columns) == 1 + MAX_TRANSPOSE_ROWS
        assert t_columns[-1] == "10"
        # t_rows: one per original column; each has 1 name + 10 values
        assert len(t_rows) == 2
        for r in t_rows:
            assert len(r) == 1 + MAX_TRANSPOSE_ROWS
