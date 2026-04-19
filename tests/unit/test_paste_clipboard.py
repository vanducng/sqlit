"""Unit tests for paste helpers (vim p / P)."""

from __future__ import annotations

from sqlit.domains.query.editing.clipboard import (
    paste_text,
    paste_text_above,
    paste_text_below,
)


class TestPasteTextBelow:
    """Linewise `p` semantics: paste a new line below current row."""

    def test_single_line_clipboard(self) -> None:
        result = paste_text_below("a\nb\nc", row=1, clipboard="X")
        assert result.text == "a\nb\nX\nc"
        # Cursor on first non-blank of first pasted line
        assert (result.row, result.col) == (2, 0)

    def test_first_non_blank_indent(self) -> None:
        # Indented pasted line — cursor lands on the first non-space char.
        result = paste_text_below("a\nb", row=0, clipboard="    indented")
        assert result.text == "a\n    indented\nb"
        assert (result.row, result.col) == (1, 4)

    def test_multi_line_clipboard(self) -> None:
        result = paste_text_below("a\nb\nc", row=0, clipboard="X\nY")
        assert result.text == "a\nX\nY\nb\nc"
        assert (result.row, result.col) == (1, 0)

    def test_paste_at_last_line(self) -> None:
        result = paste_text_below("a\nb", row=1, clipboard="X")
        assert result.text == "a\nb\nX"
        assert (result.row, result.col) == (2, 0)

    def test_empty_text(self) -> None:
        result = paste_text_below("", row=0, clipboard="X")
        assert result.text == "\nX"
        assert (result.row, result.col) == (1, 0)

    def test_row_out_of_bounds_clamped(self) -> None:
        result = paste_text_below("a", row=99, clipboard="X")
        assert result.text == "a\nX"
        assert (result.row, result.col) == (1, 0)


class TestPasteTextAbove:
    """Linewise `P` semantics: paste a new line above current row."""

    def test_single_line_clipboard(self) -> None:
        result = paste_text_above("a\nb\nc", row=1, clipboard="X")
        assert result.text == "a\nX\nb\nc"
        assert (result.row, result.col) == (1, 0)

    def test_first_non_blank_indent(self) -> None:
        result = paste_text_above("a", row=0, clipboard="\t  hello")
        assert result.text == "\t  hello\na"
        # Two leading whitespace chars (\t and spaces) skipped
        assert (result.row, result.col) == (0, 3)

    def test_multi_line_clipboard(self) -> None:
        result = paste_text_above("a\nb", row=1, clipboard="X\nY")
        assert result.text == "a\nX\nY\nb"
        assert (result.row, result.col) == (1, 0)

    def test_paste_at_first_line(self) -> None:
        result = paste_text_above("a\nb", row=0, clipboard="X")
        assert result.text == "X\na\nb"
        assert (result.row, result.col) == (0, 0)

    def test_empty_text(self) -> None:
        result = paste_text_above("", row=0, clipboard="X")
        assert result.text == "X\n"
        assert (result.row, result.col) == (0, 0)


class TestPasteTextCharwise:
    """Charwise paste (existing behavior — sanity check unchanged)."""

    def test_single_line_inline(self) -> None:
        result = paste_text("hello world", row=0, col=5, clipboard=" beautiful")
        assert result.text == "hello beautiful world"
        assert (result.row, result.col) == (0, 15)

    def test_multi_line_clipboard_splits_target_line(self) -> None:
        result = paste_text("ab", row=0, col=1, clipboard="X\nY")
        assert result.text == "aX\nYb"
        assert (result.row, result.col) == (1, 1)
