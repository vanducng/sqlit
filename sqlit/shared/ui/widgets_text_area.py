"""Text-area related widgets for sqlit."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from rich.segment import Segment
from rich.style import Style
from textual.color import Color
from textual.events import Key
from textual.strip import Strip
from textual.widgets import TextArea

if TYPE_CHECKING:
    from sqlit.shared.ui.protocols import AutocompleteProtocol


class QueryTextArea(TextArea):
    """TextArea that intercepts clipboard keys and defers Enter to app."""

    _last_text: str = ""
    _terminal_cursor_active: bool = False
    _relative_line_numbers: bool = False
    _last_cursor_row: int = -1
    _stmt_range_text: str = ""
    _stmt_range_cursor: tuple[int, int] = (-1, -1)
    _active_statement_line_range: tuple[int, int] | None = None

    # Normalize OS-variant shortcuts to canonical forms
    # Maps: super → ctrl for common operations, strips shift where irrelevant
    _KEY_NORMALIZATION: dict[str, str] = {
        # Paste variants
        "super+v": "ctrl+v",
        "ctrl+shift+v": "ctrl+v",
        "super+shift+v": "ctrl+v",
        # Copy variants
        "super+c": "ctrl+c",
        "ctrl+shift+c": "ctrl+c",
        "super+shift+c": "ctrl+c",
        # Cut variants
        "super+x": "ctrl+x",
        "ctrl+shift+x": "ctrl+x",
        "super+shift+x": "ctrl+x",
        # Select all variants
        "super+a": "ctrl+a",
        # Undo variants
        "super+z": "ctrl+z",
        # Redo variants
        "super+y": "ctrl+y",
        "super+shift+z": "ctrl+y",  # macOS-style redo
        "ctrl+shift+z": "ctrl+y",   # Alternative redo
        # Backspace/delete - shift shouldn't change behavior
        "shift+backspace": "backspace",
        "shift+delete": "delete",
    }

    def _normalize_key(self, key: str) -> str:
        """Normalize OS-variant shortcuts to canonical form."""
        return self._KEY_NORMALIZATION.get(key, key)

    def _is_insert_mode(self) -> bool:
        """Check if app is in vim INSERT mode."""
        from sqlit.core.vim import VimMode
        vim_mode = getattr(self.app, "vim_mode", None)
        return vim_mode == VimMode.INSERT

    def _should_use_terminal_cursor(self) -> bool:
        """Use a terminal bar cursor only in INSERT mode with focus."""
        return self.has_focus and self._is_insert_mode()

    def _get_insert_cursor_color(self) -> str:
        from sqlit.domains.shell.app.themes import DEFAULT_MODE_COLORS, MODE_NORMAL_COLOR_VAR

        theme = self.app.current_theme
        variables = getattr(theme, "variables", {}) or {}
        theme_key = "dark" if theme.dark else "light"
        default = DEFAULT_MODE_COLORS[theme_key][MODE_NORMAL_COLOR_VAR]
        return str(variables.get(MODE_NORMAL_COLOR_VAR, default))

    def _format_osc_color(self, value: str) -> str | None:
        value = value.strip()
        if not value:
            return None
        try:
            color = Color.parse(value)
        except Exception:
            return None
        hex_value = color.hex
        if hex_value.startswith("ansi_"):
            return None
        return hex_value

    def _sync_terminal_cursor(self) -> None:
        """Show/hide a terminal bar cursor based on insert mode and focus."""
        use_terminal = self._should_use_terminal_cursor()
        if use_terminal == self._terminal_cursor_active:
            return

        self._terminal_cursor_active = use_terminal
        self._line_cache.clear()
        self.refresh()

        driver = getattr(self.app, "_driver", None)
        if driver is None:
            return

        if use_terminal:
            # Show cursor and request steady bar shape (DECSCUSR 6).
            driver.write("\x1b[?25h\x1b[6 q")
            osc_color = self._format_osc_color(self._get_insert_cursor_color())
            if osc_color:
                driver.write(f"\x1b]12;{osc_color}\x1b\\")
        else:
            # Hide cursor and reset to steady block (DECSCUSR 2).
            driver.write("\x1b[?25l\x1b[2 q")
            driver.write("\x1b]112\x1b\\")
        driver.flush()

    def sync_terminal_cursor(self) -> None:
        """Public hook to refresh cursor rendering."""
        self._sync_terminal_cursor()

    @property
    def _draw_cursor(self) -> bool:  # type: ignore[override]
        if self._should_use_terminal_cursor():
            return False
        return super()._draw_cursor

    def _watch_has_focus(self, focus: bool) -> None:
        super()._watch_has_focus(focus)
        self._sync_terminal_cursor()
        # Drop any stale statement highlight when the editor loses focus so it
        # does not linger in the background while the user is in the explorer
        # or results pane.
        if not focus and self._active_statement_line_range is not None:
            self._active_statement_line_range = None
            self._stmt_range_cursor = (-1, -1)
            self._line_cache.clear()
            self.refresh()

    async def _on_key(self, event: Key) -> None:
        """Intercept clipboard, undo/redo, and Enter keys."""
        normalized_key = self._normalize_key(event.key)

        # Clipboard shortcuts only work in INSERT mode (vim consistency)
        if normalized_key in ("ctrl+a", "ctrl+c", "ctrl+v"):
            if not self._is_insert_mode():
                # Block these in normal mode - use vim commands instead
                event.prevent_default()
                event.stop()
                return

            # Handle CTRL+A (select all) - override Emacs beginning-of-line
            if normalized_key == "ctrl+a":
                if hasattr(self.app, "action_select_all"):
                    self.app.action_select_all()
                event.prevent_default()
                event.stop()
                return

            # Handle CTRL+C (copy) - override default behavior
            if normalized_key == "ctrl+c":
                if hasattr(self.app, "action_copy_selection"):
                    self.app.action_copy_selection()
                event.prevent_default()
                event.stop()
                return

            # Handle CTRL+V (paste) - override default behavior
            if normalized_key == "ctrl+v":
                # Push undo state before paste
                self._push_undo_if_changed()
                if hasattr(self.app, "action_paste"):
                    self.app.action_paste()
                event.prevent_default()
                event.stop()
                return

        # Undo/redo work in both modes
        # Handle CTRL+Z (undo)
        if normalized_key == "ctrl+z":
            if hasattr(self.app, "action_undo"):
                self.app.action_undo()
            event.prevent_default()
            event.stop()
            return

        # Handle CTRL+Y (redo)
        if normalized_key == "ctrl+y":
            if hasattr(self.app, "action_redo"):
                self.app.action_redo()
            event.prevent_default()
            event.stop()
            return

        # Note: Shift+Arrow selection is handled natively by TextArea
        # (shift+left/right/up/down, shift+home/end)

        # Handle Enter key when autocomplete is visible
        if event.key == "enter":
            app = cast("AutocompleteProtocol", self.app)
            if getattr(app, "_autocomplete_visible", False):
                # Hide autocomplete and suppress re-triggering from the newline
                if hasattr(app, "_hide_autocomplete"):
                    app._hide_autocomplete()
                app._suppress_autocomplete_on_newline = True

        # For text-modifying keys, push undo state before the change
        if self._is_text_modifying_key(normalized_key):
            self._push_undo_if_changed()

        # For all other keys, use default TextArea behavior
        await super()._on_key(event)

    def _is_visual_mode(self) -> bool:
        """Check if app is in any vim visual mode."""
        from sqlit.core.vim import VimMode
        vim_mode = getattr(self.app, "vim_mode", None)
        return vim_mode in (VimMode.VISUAL, VimMode.VISUAL_LINE)

    def action_cursor_up(self, select: bool = False) -> None:
        """Override to delegate to app in visual modes."""
        if self._is_visual_mode():
            if hasattr(self.app, "action_cursor_up"):
                self.app.action_cursor_up()
            return
        super().action_cursor_up(select)

    def action_cursor_down(self, select: bool = False) -> None:
        """Override to delegate to app in visual modes."""
        if self._is_visual_mode():
            if hasattr(self.app, "action_cursor_down"):
                self.app.action_cursor_down()
            return
        super().action_cursor_down(select)

    def action_cursor_left(self, select: bool = False) -> None:
        """Override to delegate to app in visual modes."""
        if self._is_visual_mode():
            if hasattr(self.app, "action_cursor_left"):
                self.app.action_cursor_left()
            return
        super().action_cursor_left(select)

    def action_cursor_right(self, select: bool = False) -> None:
        """Override to delegate to app in visual modes."""
        if self._is_visual_mode():
            if hasattr(self.app, "action_cursor_right"):
                self.app.action_cursor_right()
            return
        super().action_cursor_right(select)

    def _is_text_modifying_key(self, key: str) -> bool:
        """Check if a key might modify text (expects normalized key)."""
        # Single characters, backspace, delete, enter are text-modifying
        if len(key) == 1:
            return True
        return key in ("backspace", "delete", "enter", "tab")

    def _push_undo_if_changed(self) -> None:
        """Push current state to undo history if text has changed."""
        current_text = self.text
        if current_text != self._last_text:
            if hasattr(self.app, "_push_undo_state"):
                self.app._push_undo_state()
            self._last_text = current_text

    @property
    def relative_line_numbers(self) -> bool:
        """Whether to show relative line numbers."""
        return self._relative_line_numbers

    @relative_line_numbers.setter
    def relative_line_numbers(self, value: bool) -> None:
        """Set relative line numbers mode."""
        if self._relative_line_numbers != value:
            self._relative_line_numbers = value
            self._line_cache.clear()
            self.refresh()

    def _watch_selection(self, previous_selection: object, selection: object) -> None:
        """Clear line cache when cursor row changes (for relative line numbers)."""
        super()._watch_selection(previous_selection, selection)  # type: ignore[arg-type]
        if self._relative_line_numbers and self.show_line_numbers:
            # Get current cursor row
            cursor_row = self.selection.end[0]
            if cursor_row != self._last_cursor_row:
                self._last_cursor_row = cursor_row
                self._line_cache.clear()
                self.refresh()
        # Re-resolve which statement lines should be tinted.
        old_range = self._active_statement_line_range
        new_range = self._resolve_active_statement_line_range()
        if new_range != old_range:
            self._line_cache.clear()
            self.refresh()

    def _resolve_active_statement_line_range(self) -> tuple[int, int] | None:
        """Compute (first_row, last_row) to tint, cached by (text, cursor)."""
        from sqlit.domains.query.app.multi_statement import active_statement_line_range

        text = self.text
        cursor = self.selection.end

        if text != self._stmt_range_text:
            self._stmt_range_text = text
            self._stmt_range_cursor = (-1, -1)

        if cursor != self._stmt_range_cursor:
            self._stmt_range_cursor = cursor
            self._active_statement_line_range = active_statement_line_range(
                text, cursor[0], cursor[1]
            )
        return self._active_statement_line_range

    def _active_statement_tint_style(self) -> Style | None:
        """Subtle background tint for the current statement."""
        theme = getattr(self.app, "current_theme", None)
        is_dark = bool(getattr(theme, "dark", True))
        # Low-contrast overlay that reads on both themes.
        hex_bg = "#2a2d3a" if is_dark else "#e6e8ec"
        try:
            return Style(bgcolor=hex_bg)
        except Exception:
            return None

    def render_line(self, y: int) -> Strip:
        """Render a line, with relative line numbers + statement highlight."""
        # Get the base rendered line
        strip = super().render_line(y)

        scroll_y = self.scroll_offset[1]
        absolute_y = scroll_y + y
        cursor_row = self.selection.end[0]
        gutter_width = self.gutter_width
        wrapped_document = self.wrapped_document

        line_index: int | None = None
        section_offset: int | None = None
        if absolute_y < wrapped_document.height:
            try:
                line_info = wrapped_document._offset_to_line_info[absolute_y]
            except (IndexError, AttributeError):
                line_info = None
            if line_info is not None:
                line_index, section_offset = line_info

        # Relative line numbers: replace gutter segment.
        if (
            self._relative_line_numbers
            and self.show_line_numbers
            and gutter_width > 0
            and line_index is not None
            and section_offset == 0
        ):
            if line_index == cursor_row:
                line_num = line_index + self.line_number_start
            else:
                line_num = abs(line_index - cursor_row)
            gutter_width_no_margin = gutter_width - 2
            new_gutter_text = f"{line_num:>{gutter_width_no_margin}}  "
            segments = list(strip._segments)
            if segments:
                old_seg = segments[0]
                if len(old_seg.text) == gutter_width:
                    segments[0] = Segment(new_gutter_text, old_seg.style)
                    strip = Strip(segments, strip.cell_length)

        # Current-statement highlight tint on non-gutter content.
        # Guard against text changes that happen without a cursor move — drop
        # any stale range so we re-resolve on the next selection watch.
        if (
            self._active_statement_line_range is not None
            and self._stmt_range_text is not self.text
            and self._stmt_range_text != self.text
        ):
            self._active_statement_line_range = None
            self._stmt_range_cursor = (-1, -1)
        active = self._active_statement_line_range
        if (
            active is not None
            and line_index is not None
            and active[0] <= line_index <= active[1]
        ):
            tint = self._active_statement_tint_style()
            if tint is not None:
                segments = list(strip._segments)
                start_idx = 0
                if gutter_width > 0 and segments:
                    first = segments[0]
                    if len(first.text) == gutter_width:
                        start_idx = 1
                for i in range(start_idx, len(segments)):
                    seg = segments[i]
                    existing = seg.style or Style()
                    # Place tint under existing style so explicit selection /
                    # syntax colors still win on top.
                    segments[i] = Segment(seg.text, tint + existing)
                strip = Strip(segments, strip.cell_length)

        return strip
