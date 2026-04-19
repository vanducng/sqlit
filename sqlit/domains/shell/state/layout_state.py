"""Pane layout state — sidebar width and query/results split percentage.

Pure data + math; no Textual imports. The shell app owns one instance and
reads/writes it on mount/unmount; the resize actions mutate via :meth:`adjust`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

SIDEBAR_MIN, SIDEBAR_MAX = 15, 80
QUERY_PCT_MIN, QUERY_PCT_MAX = 20, 80
DEFAULT_SIDEBAR_WIDTH = 35
DEFAULT_QUERY_PCT = 50
STEP = 2


@dataclass
class LayoutState:
    sidebar_width: int = DEFAULT_SIDEBAR_WIDTH
    query_height_pct: int = DEFAULT_QUERY_PCT

    def clamp(self) -> None:
        self.sidebar_width = max(SIDEBAR_MIN, min(SIDEBAR_MAX, self.sidebar_width))
        self.query_height_pct = max(QUERY_PCT_MIN, min(QUERY_PCT_MAX, self.query_height_pct))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LayoutState:
        try:
            sidebar = raw.get("sidebar_width", DEFAULT_SIDEBAR_WIDTH)
            query = raw.get("query_height_pct", DEFAULT_QUERY_PCT)
            if sidebar is None:
                sidebar = DEFAULT_SIDEBAR_WIDTH
            if query is None:
                query = DEFAULT_QUERY_PCT
            state = cls(sidebar_width=int(sidebar), query_height_pct=int(query))
        except (TypeError, ValueError):
            state = cls()
        state.clamp()
        return state

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    def adjust(self, pane: str, direction: str) -> bool:
        """Mutate state per pane/direction. Returns True iff value changed."""
        before = (self.sidebar_width, self.query_height_pct)
        if pane == "sidebar":
            if direction == "right":
                self.sidebar_width += STEP
            elif direction == "left":
                self.sidebar_width -= STEP
            else:
                return False
        elif pane == "query":
            if direction == "down":
                self.query_height_pct += STEP
            elif direction == "up":
                self.query_height_pct -= STEP
            else:
                return False
        elif pane == "results":
            # Results pane has no width/height of its own — it shares vertical
            # space with the query pane, so resize is expressed indirectly via
            # query_height_pct. Up shrinks query (results grows up); down grows
            # query (results shrinks down). This indirection is intentional.
            if direction == "up":
                self.query_height_pct -= STEP
            elif direction == "down":
                self.query_height_pct += STEP
            else:
                return False
        else:
            return False
        self.clamp()
        return (self.sidebar_width, self.query_height_pct) != before
