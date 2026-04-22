"""Tree yank (`ty`) leader-menu actions for the explorer."""

from __future__ import annotations

from sqlit.shared.ui.protocols import TreeMixinHost

from ...app.node_name_resolver import NodeNames, resolve_node_names

_TRUNCATE_AT = 80


class TreeYankMixin:
    """Mixin providing the `ty` leader menu (copy node name variants)."""

    def action_ty_leader_key(self: TreeMixinHost) -> None:
        """Open the tree yank (copy) leader menu."""
        self._start_leader_pending("ty")

    def _ty_current_node_names(self: TreeMixinHost) -> NodeNames | None:
        """Resolve the focused tree node into yank variants, or None."""
        node = self.object_tree.cursor_node
        if not node or not node.data:
            return None
        dialect = getattr(self.current_provider, "dialect", None) if self.current_provider else None
        return resolve_node_names(self._get_node_kind(node), node.data, dialect)

    def _ty_copy_and_notify(self: TreeMixinHost, text: str) -> None:
        """Copy `text` to clipboard and surface a short confirmation toast."""
        self._copy_text(text)
        msg = text if len(text) <= _TRUNCATE_AT else text[: _TRUNCATE_AT - 3] + "..."
        self.notify(f"Copied: {msg}")

    def action_ty_yank_qualified(self: TreeMixinHost) -> None:
        """Copy dialect-quoted FQN (ty menu)."""
        self._clear_leader_pending()
        names = self._ty_current_node_names()
        if names is None:
            self.notify("Nothing to copy", severity="warning")
            return
        self._ty_copy_and_notify(names.qualified)

    def action_ty_yank_name(self: TreeMixinHost) -> None:
        """Copy bare node name (ty menu)."""
        self._clear_leader_pending()
        names = self._ty_current_node_names()
        if names is None:
            self.notify("Nothing to copy", severity="warning")
            return
        self._ty_copy_and_notify(names.name)

    def action_ty_yank_dotted(self: TreeMixinHost) -> None:
        """Copy unquoted dotted FQN (ty menu)."""
        self._clear_leader_pending()
        names = self._ty_current_node_names()
        if names is None:
            self.notify("Nothing to copy", severity="warning")
            return
        self._ty_copy_and_notify(names.dotted)

    def action_ty_yank_select(self: TreeMixinHost) -> None:
        """Copy SELECT ... LIMIT 100 snippet (ty menu; table/view only)."""
        self._clear_leader_pending()
        names = self._ty_current_node_names()
        if names is None:
            self.notify("Nothing to copy", severity="warning")
            return
        if names.select_snippet is None:
            self.notify("No SELECT for this node", severity="warning")
            return
        self._ty_copy_and_notify(names.select_snippet)
