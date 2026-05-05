"""Tests for `yj` (copy current row as JSON) — formatter + action."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from textual.coordinate import Coordinate

from sqlit.domains.results.formatters import format_row_json
from sqlit.domains.results.ui.mixins.results import ResultsMixin

# ---------------------------------------------------------------------------
# format_row_json — pure unit tests
# ---------------------------------------------------------------------------


class TestFormatRowJson:
    def test_normal_row(self) -> None:
        text = format_row_json(["a", "b"], (1, "x"))
        assert json.loads(text) == {"a": 1, "b": "x"}

    def test_none_serializes_as_null(self) -> None:
        text = format_row_json(["a", "b"], (1, None))
        parsed = json.loads(text)
        assert parsed == {"a": 1, "b": None}

    def test_decimal_coerced_via_default_str(self) -> None:
        text = format_row_json(["price"], (Decimal("1.50"),))
        assert json.loads(text) == {"price": "1.50"}

    def test_datetime_coerced_via_default_str(self) -> None:
        text = format_row_json(["ts"], (datetime(2026, 5, 4, 12, 30, 0),))
        parsed = json.loads(text)
        assert parsed["ts"].startswith("2026-05-04")

    def test_bytes_coerced_via_default_str(self) -> None:
        text = format_row_json(["blob"], (b"\x00\x01",))
        parsed = json.loads(text)
        # default=str on bytes yields the repr-style "b'\\x00\\x01'"
        assert isinstance(parsed["blob"], str)
        assert "\\x00" in parsed["blob"] or "\x00" in parsed["blob"]


# ---------------------------------------------------------------------------
# action_ry_row_json — fake-host behavior tests
# ---------------------------------------------------------------------------


class _FakeTable:
    has_focus = False

    def __init__(
        self,
        rows: list[tuple],
        cursor: tuple[int, int] = (0, 0),
    ) -> None:
        self._rows = rows
        self.cursor_coordinate = Coordinate(*cursor)
        self.row_count = len(rows)

    @property
    def cursor_row(self) -> int:
        return self.cursor_coordinate.row

    def get_row_at(self, row: int) -> tuple:
        return tuple(self._rows[row])


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

    def _get_active_results_context(self):  # type: ignore[override]
        return self._table, list(self._columns), list(self._rows), self._stacked

    def _find_results_section(self, _widget):  # type: ignore[override]
        return self._section

    def notify(
        self, message: str, *, severity: str = "information", **_: object
    ) -> None:
        self.notifications.append((message, severity))

    def _copy_text(self, text: str) -> bool:  # type: ignore[override]
        self.copied.append(text)
        return True

    def _flash_table_yank(self, _table, scope: str) -> None:  # type: ignore[override]
        self.flashes.append(scope)

    def _clear_leader_pending(self) -> None:
        self._leader_cleared += 1


class TestActionRyRowJson:
    def test_normal_mode_copies_cursor_row(self) -> None:
        rows = [(1, "a"), (2, "b"), (3, "c")]
        table = _FakeTable(rows, cursor=(1, 0))
        host = _FakeHost(table, ["id", "name"], rows)
        host.action_ry_row_json()
        assert len(host.copied) == 1
        assert json.loads(host.copied[0]) == {"id": 2, "name": "b"}
        assert host.flashes == ["row"]
        assert host._leader_cleared == 1

    def test_transposed_data_col_copies_original_row(self) -> None:
        # cursor display (dr=0, dc=2) → orig_row_idx = dc-1 = 1
        rows = [(1, "a"), (2, "b"), (3, "c")]
        # Transposed display has rows = [("id",1,2,3), ("name","a","b","c")]
        table = _FakeTable(
            [("id", 1, 2, 3), ("name", "a", "b", "c")], cursor=(0, 2)
        )
        section = _FakeSection(["id", "name"], rows, transposed=True)
        host = _FakeHost(
            table, ["id", "name"], rows, stacked=True, section=section
        )
        host.action_ry_row_json()
        assert len(host.copied) == 1
        assert json.loads(host.copied[0]) == {"id": 2, "name": "b"}
        assert host.flashes == ["row"]

    def test_transposed_label_col_warns_and_skips(self) -> None:
        rows = [(1, "a"), (2, "b")]
        table = _FakeTable(
            [("id", 1, 2), ("name", "a", "b")], cursor=(0, 0)
        )
        section = _FakeSection(["id", "name"], rows, transposed=True)
        host = _FakeHost(
            table, ["id", "name"], rows, stacked=True, section=section
        )
        host.action_ry_row_json()
        assert host.copied == []
        assert host.flashes == []
        assert any(
            m == "No row at cursor" and sev == "warning"
            for m, sev in host.notifications
        )

    def test_transposed_dc_past_rows_silent_return(self) -> None:
        rows = [(1, "a"), (2, "b")]
        # Only 2 original rows → dc must be 1 or 2; dc=5 is out of range.
        table = _FakeTable(
            [("id", 1, 2), ("name", "a", "b")], cursor=(0, 5)
        )
        section = _FakeSection(["id", "name"], rows, transposed=True)
        host = _FakeHost(
            table, ["id", "name"], rows, stacked=True, section=section
        )
        host.action_ry_row_json()
        assert host.copied == []
        assert host.notifications == []
        assert host.flashes == []

    def test_no_results_warns(self) -> None:
        table = _FakeTable([])
        host = _FakeHost(table, ["a"], [])
        host.action_ry_row_json()
        assert host.copied == []
        assert any(
            m == "No results" and sev == "warning"
            for m, sev in host.notifications
        )

    def test_normal_mode_with_null_cell(self) -> None:
        rows = [(1, None)]
        table = _FakeTable(rows, cursor=(0, 0))
        host = _FakeHost(table, ["id", "name"], rows)
        host.action_ry_row_json()
        assert json.loads(host.copied[0]) == {"id": 1, "name": None}
