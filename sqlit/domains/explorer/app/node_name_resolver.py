"""Pure resolver that maps an explorer tree node to yank-ready name variants.

Used by the tree `ty` leader menu. No Textual imports, no I/O — unit-testable
in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlit.domains.connections.providers.model import Dialect


@dataclass(frozen=True)
class NodeNames:
    """Four yank-ready representations of a tree node's name."""

    name: str                    # bare last segment: "users"
    dotted: str                  # unquoted dotted: "mydb.public.users"
    qualified: str               # dialect-quoted dotted: '"mydb"."public"."users"'
    select_snippet: str | None   # "SELECT ... LIMIT 100" — only for table/view


_SELECT_KINDS = {"table", "view"}
_EMPTY_KINDS = {"folder", "loading", "connection_folder"}


def _extract_parts(kind: str, data: Any) -> list[str] | None:
    """Extract non-empty identifier parts in FQN order for a node kind."""
    if kind in _EMPTY_KINDS or data is None:
        return None

    if kind in ("table", "view"):
        return [p for p in (getattr(data, "database", None), getattr(data, "schema", "") or None, data.name) if p]

    if kind == "column":
        return [
            p
            for p in (
                getattr(data, "database", None),
                getattr(data, "schema", "") or None,
                data.table,
                data.name,
            )
            if p
        ]

    if kind == "schema":
        return [p for p in (getattr(data, "database", None), data.schema) if p]

    if kind == "database":
        return [data.name]

    if kind in ("index", "trigger", "sequence", "procedure"):
        return [p for p in (getattr(data, "database", None), data.name) if p]

    if kind == "connection":
        return [data.config.name]

    return None


def _build_select(
    data: Any,
    dialect: Dialect,
) -> str | None:
    """Produce the SELECT ... LIMIT 100 snippet for a table/view node."""
    try:
        return dialect.build_select_query(
            data.name,
            100,
            getattr(data, "database", None),
            getattr(data, "schema", "") or None,
        )
    except Exception:
        return None


def resolve_node_names(
    kind: str,
    data: Any,
    dialect: Dialect | None,
) -> NodeNames | None:
    """Resolve a tree node to yank-ready name variants.

    Returns None for nodes that have no meaningful name to copy (folders,
    loading placeholders, connection folders).
    """
    parts = _extract_parts(kind, data)
    if not parts:
        return None

    name = parts[-1]
    dotted = ".".join(parts)
    if dialect is None:
        qualified = dotted
    else:
        qualified = ".".join(dialect.quote_identifier(p) for p in parts)

    select_snippet: str | None = None
    if kind in _SELECT_KINDS and dialect is not None:
        select_snippet = _build_select(data, dialect)

    return NodeNames(name=name, dotted=dotted, qualified=qualified, select_snippet=select_snippet)
