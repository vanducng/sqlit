"""Open the current query buffer in an external editor ($VISUAL/$EDITOR/vi)."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlit.shared.ui.protocols import QueryMixinHost


class QueryExternalEditorMixin:
    """Handler for `edit_in_external_editor` (bound to `Ctrl+G`)."""

    def action_edit_in_external_editor(self: QueryMixinHost) -> None:
        if getattr(self, "_query_worker", None) is not None:
            self.notify("Cannot edit externally while a query is running", severity="warning")
            return

        if getattr(self, "_autocomplete_visible", False):
            self._hide_autocomplete()

        editor_spec = (os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi").strip()
        if not editor_spec:
            self.notify("No editor configured ($VISUAL/$EDITOR empty)", severity="error")
            return
        try:
            editor_argv = shlex.split(editor_spec)
        except ValueError as exc:
            self.notify(f"Invalid $VISUAL/$EDITOR: {exc}", severity="error")
            return
        if not editor_argv:
            self.notify("No editor configured", severity="error")
            return

        original = self.query_input.text
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".sql", delete=False, encoding="utf-8"
        )
        tmp_path = Path(tmp.name)
        try:
            tmp.write(original)
            tmp.flush()
            tmp.close()

            with self.app.suspend():
                proc = subprocess.run(
                    [*editor_argv, str(tmp_path)],
                    check=False,
                )

            if proc.returncode != 0:
                self.notify(
                    f"Editor exited with status {proc.returncode}; buffer preserved",
                    severity="warning",
                )
                return

            new_text = tmp_path.read_text(encoding="utf-8")
            if new_text == original:
                self.notify("No changes from external editor")
                return

            # Single undo step: snapshot current, then replace.
            self._push_undo_state()
            self.query_input.text = new_text
            # Return to NORMAL mode regardless of entry mode.
            exit_insert = getattr(self, "action_exit_insert_mode", None)
            if callable(exit_insert):
                exit_insert()
            self.notify("Buffer updated from external editor")
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
