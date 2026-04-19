"""Pure-unit tests for LayoutState (pane size persistence + math)."""

from __future__ import annotations

from sqlit.domains.shell.state.layout_state import (
    DEFAULT_QUERY_PCT,
    DEFAULT_SIDEBAR_WIDTH,
    QUERY_PCT_MAX,
    QUERY_PCT_MIN,
    SIDEBAR_MAX,
    SIDEBAR_MIN,
    STEP,
    LayoutState,
)


class TestDefaults:
    def test_defaults(self):
        s = LayoutState()
        assert s.sidebar_width == DEFAULT_SIDEBAR_WIDTH
        assert s.query_height_pct == DEFAULT_QUERY_PCT


class TestFromDict:
    def test_empty_dict(self):
        s = LayoutState.from_dict({})
        assert s.sidebar_width == DEFAULT_SIDEBAR_WIDTH
        assert s.query_height_pct == DEFAULT_QUERY_PCT

    def test_partial_dict(self):
        s = LayoutState.from_dict({"sidebar_width": 50})
        assert s.sidebar_width == 50
        assert s.query_height_pct == DEFAULT_QUERY_PCT

    def test_clamps_high(self):
        s = LayoutState.from_dict({"sidebar_width": 999, "query_height_pct": 999})
        assert s.sidebar_width == SIDEBAR_MAX
        assert s.query_height_pct == QUERY_PCT_MAX

    def test_clamps_low(self):
        s = LayoutState.from_dict({"sidebar_width": 1, "query_height_pct": 1})
        assert s.sidebar_width == SIDEBAR_MIN
        assert s.query_height_pct == QUERY_PCT_MIN

    def test_invalid_falls_back(self):
        s = LayoutState.from_dict({"sidebar_width": "bad"})
        assert s.sidebar_width == DEFAULT_SIDEBAR_WIDTH
        assert s.query_height_pct == DEFAULT_QUERY_PCT

    def test_none_value_falls_back(self):
        s = LayoutState.from_dict({"sidebar_width": None, "query_height_pct": None})
        assert s.sidebar_width == DEFAULT_SIDEBAR_WIDTH
        assert s.query_height_pct == DEFAULT_QUERY_PCT


class TestToDict:
    def test_round_trip(self):
        s = LayoutState(sidebar_width=42, query_height_pct=60)
        raw = s.to_dict()
        assert raw == {"sidebar_width": 42, "query_height_pct": 60}
        reloaded = LayoutState.from_dict(raw)
        assert reloaded.sidebar_width == 42
        assert reloaded.query_height_pct == 60


class TestAdjustSidebar:
    def test_grow_right(self):
        s = LayoutState()
        assert s.adjust("sidebar", "right") is True
        assert s.sidebar_width == DEFAULT_SIDEBAR_WIDTH + STEP

    def test_shrink_left(self):
        s = LayoutState()
        assert s.adjust("sidebar", "left") is True
        assert s.sidebar_width == DEFAULT_SIDEBAR_WIDTH - STEP

    def test_up_no_op(self):
        s = LayoutState()
        assert s.adjust("sidebar", "up") is False
        assert s.sidebar_width == DEFAULT_SIDEBAR_WIDTH

    def test_down_no_op(self):
        s = LayoutState()
        assert s.adjust("sidebar", "down") is False

    def test_clamp_at_max_returns_false(self):
        s = LayoutState(sidebar_width=SIDEBAR_MAX)
        assert s.adjust("sidebar", "right") is False
        assert s.sidebar_width == SIDEBAR_MAX

    def test_clamp_at_min_returns_false(self):
        s = LayoutState(sidebar_width=SIDEBAR_MIN)
        assert s.adjust("sidebar", "left") is False
        assert s.sidebar_width == SIDEBAR_MIN


class TestAdjustQuery:
    def test_grow_down(self):
        s = LayoutState()
        assert s.adjust("query", "down") is True
        assert s.query_height_pct == DEFAULT_QUERY_PCT + STEP

    def test_shrink_up(self):
        s = LayoutState()
        assert s.adjust("query", "up") is True
        assert s.query_height_pct == DEFAULT_QUERY_PCT - STEP

    def test_left_no_op(self):
        s = LayoutState()
        assert s.adjust("query", "left") is False

    def test_right_no_op(self):
        s = LayoutState()
        assert s.adjust("query", "right") is False


class TestAdjustResults:
    def test_up_grows_results_by_shrinking_query(self):
        s = LayoutState(query_height_pct=50)
        assert s.adjust("results", "up") is True
        assert s.query_height_pct == 50 - STEP

    def test_down_shrinks_results_by_growing_query(self):
        s = LayoutState(query_height_pct=50)
        assert s.adjust("results", "down") is True
        assert s.query_height_pct == 50 + STEP

    def test_left_no_op(self):
        s = LayoutState()
        assert s.adjust("results", "left") is False


class TestAdjustUnknownPane:
    def test_unknown_pane_no_op(self):
        s = LayoutState()
        assert s.adjust("nope", "right") is False
