"""Property 22: LLM time budget stays inside the function limit."""
from hypothesis import given, settings, strategies as st

from airwise.config import (
    LLM_MIN_BUDGET_S,
    LLM_TIMEOUT_S,
    REQUEST_DEADLINE_S,
    Deadline,
)


# Feature: airwise, Property 22: LLM time budget stays inside the function limit
# **Validates: Requirements 12.6, 12.8**
@settings(max_examples=200)
@given(
    elapsed=st.floats(min_value=0.0, max_value=60.0, allow_nan=False),
    total=st.floats(min_value=1.0, max_value=60.0, allow_nan=False),
)
def test_llm_budget_inside_limit(elapsed, total):
    now = [0.0]
    d = Deadline(total, clock=lambda: now[0])
    now[0] = elapsed
    remaining = d.remaining()
    timeout = d.llm_timeout()
    assert remaining >= 0.0
    assert 0.0 <= timeout <= LLM_TIMEOUT_S
    assert timeout <= max(0.0, remaining - 1.0)
    assert d.should_skip_llm() == (remaining < LLM_MIN_BUDGET_S)
    if not d.should_skip_llm():
        assert timeout >= 1.0 - 1e-9
        # LLM call finishes with at least 1s to spare before the deadline
        assert elapsed + timeout <= total - 1.0 + 1e-9 or timeout == 0.0


@settings(max_examples=100)
@given(elapsed=st.floats(min_value=0.0, max_value=REQUEST_DEADLINE_S, allow_nan=False))
def test_default_deadline_stays_below_function_limit(elapsed):
    now = [0.0]
    d = Deadline(clock=lambda: now[0])
    now[0] = elapsed
    assert elapsed + d.llm_timeout() <= REQUEST_DEADLINE_S < 30
