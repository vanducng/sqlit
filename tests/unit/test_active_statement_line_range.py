"""Unit tests for active_statement_line_range helper.

Phase 2 of plans/260419-0459-run-statement-under-cursor.

Drives the highlight logic: maps cursor (row, col) -> inclusive (first, last)
line range of the statement under the cursor, or None when there is nothing
meaningful to highlight (single-statement buffer, empty buffer, etc.).
"""

from __future__ import annotations

import pytest

from sqlit.domains.query.app.multi_statement import active_statement_line_range


class TestActiveStatementLineRange:
    def test_returns_none_for_single_statement(self) -> None:
        # No highlight when only one statement in buffer.
        assert active_statement_line_range("SELECT * FROM users", 0, 5) is None

    def test_returns_none_for_empty_buffer(self) -> None:
        assert active_statement_line_range("", 0, 0) is None
        assert active_statement_line_range("   \n  ", 0, 0) is None

    def test_returns_range_for_cursor_in_middle_statement(self) -> None:
        sql = "SELECT 1;\nSELECT 2;\nSELECT 3"
        # Cursor on line 1 (0-based): inside 'SELECT 2'.
        assert active_statement_line_range(sql, 1, 3) == (1, 1)

    def test_returns_range_for_cursor_in_first_statement(self) -> None:
        sql = "SELECT 1;\nSELECT 2;\nSELECT 3"
        assert active_statement_line_range(sql, 0, 2) == (0, 0)

    def test_returns_range_for_cursor_in_last_statement(self) -> None:
        sql = "SELECT 1;\nSELECT 2;\nSELECT 3"
        assert active_statement_line_range(sql, 2, 4) == (2, 2)

    def test_returns_range_for_multi_line_statement(self) -> None:
        sql = "SELECT *\nFROM users;\nSELECT 2"
        # Cursor somewhere on line 1 (second line of stmt 1).
        assert active_statement_line_range(sql, 1, 3) == (0, 1)

    def test_cursor_on_blank_line_between_statements_highlights_preceding(self) -> None:
        # Matches find_statement_at_cursor fallback semantics.
        sql = "SELECT 1;\n\nSELECT 2;"
        assert active_statement_line_range(sql, 1, 0) == (0, 0)

    def test_cursor_past_eof_highlights_last_statement(self) -> None:
        sql = "SELECT 1;\nSELECT 2"
        # Row past last line -> last statement.
        result = active_statement_line_range(sql, 5, 0)
        assert result == (1, 1)

    def test_blank_line_separated_statements_produce_ranges(self) -> None:
        sql = "SELECT 1\n\nSELECT 2"
        assert active_statement_line_range(sql, 0, 3) == (0, 0)
        assert active_statement_line_range(sql, 2, 3) == (2, 2)

    @pytest.mark.parametrize(
        "sql, row, col, expected",
        [
            # 3 statements on 3 lines
            ("A;\nB;\nC", 0, 0, (0, 0)),
            ("A;\nB;\nC", 1, 0, (1, 1)),
            ("A;\nB;\nC", 2, 0, (2, 2)),
        ],
    )
    def test_three_single_line_statements(
        self, sql: str, row: int, col: int, expected: tuple[int, int]
    ) -> None:
        assert active_statement_line_range(sql, row, col) == expected
