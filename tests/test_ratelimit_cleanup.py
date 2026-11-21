"""Tests for FixedWindowLimiter._cleanup: only expired entries go, decisions never change."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from airwise import ratelimit
from airwise.ratelimit import CLEANUP_THRESHOLD, FixedWindowLimiter

WINDOW = 60.0


def _limiter(limit: int = 1) -> tuple[FixedWindowLimiter, list[float]]:
    """A limiter driven by a mutable fake clock (no sleeps, no time patching)."""
    now = [0.0]
    return FixedWindowLimiter(limit, WINDOW, clock=lambda: now[0]), now


def test_cleanup_threshold_constant_is_unchanged():
    # The tests below that use the real constant depend on this value.
    assert CLEANUP_THRESHOLD == 10_000


def test_cleanup_drops_expired_keys_and_keeps_live_ones_untouched(monkeypatch):
    monkeypatch.setattr("airwise.ratelimit.CLEANUP_THRESHOLD", 5)
    lim, now = _limiter(limit=1)
    now[0] = 0.0
    for i in range(3):
        assert lim.check(f"old{i}").allowed
    now[0] = 50.0
    for i in range(3):
        assert lim.check(f"live{i}").allowed
    assert len(lim._state) == 6

    now[0] = 70.0  # old* are 70 s old (expired), live* are 20 s old
    assert lim.check("new").allowed

    assert not any(k.startswith("old") for k in lim._state), "expired keys must be removed"
    for i in range(3):
        assert lim._state[f"live{i}"] == (50.0, 1), "live keys keep window start and count"
    assert lim._state["new"] == (70.0, 1)
    assert len(lim._state) == 4

    # A live key that was at its limit is still rejected: cleanup did not reset it.
    rejected = lim.check("live0")
    assert not rejected.allowed
    assert rejected.retry_after == 40  # 50 + 60 - 70
    # An expired key that was cleaned up starts a fresh window.
    assert lim.check("old0").allowed


def test_cleanup_runs_only_when_size_is_over_the_threshold(monkeypatch):
    monkeypatch.setattr("airwise.ratelimit.CLEANUP_THRESHOLD", 5)
    lim, now = _limiter()
    for i in range(5):
        lim.check(f"k{i}")
    assert len(lim._state) == 5

    now[0] = 100.0  # all five entries are expired
    lim.check("a")  # size is 5 == threshold when checked: no cleanup
    assert len(lim._state) == 6, "exactly at the threshold nothing is removed"

    lim.check("b")  # size is 6 > 5 when checked: cleanup drops the five expired keys
    assert sorted(lim._state) == ["a", "b"]


def test_cleanup_threshold_with_the_real_constant():
    lim, now = _limiter()
    for i in range(CLEANUP_THRESHOLD):
        assert lim.check(f"ip{i}").allowed
    assert len(lim._state) == CLEANUP_THRESHOLD

    now[0] = WINDOW + 1  # everything expired
    assert lim.check("probe-1").allowed
    assert len(lim._state) == CLEANUP_THRESHOLD + 1, "at the threshold: no cleanup yet"

    assert lim.check("probe-2").allowed
    assert sorted(lim._state) == ["probe-1", "probe-2"], "one over the threshold: cleanup ran"


@pytest.mark.parametrize(
    ("age", "expired"),
    [(WINDOW - 0.5, False), (WINDOW - 1 / 1024, False), (WINDOW, True), (WINDOW + 0.5, True)],
)
def test_expiry_boundary_matches_check_rule(monkeypatch, age, expired):
    monkeypatch.setattr("airwise.ratelimit.CLEANUP_THRESHOLD", 2)
    lim, now = _limiter(limit=1)
    for key in ("k", "filler1", "filler2"):
        lim.check(key)  # all three start at t=0; the third check leaves size 3 > 2

    now[0] = age
    decision = lim.check("k")  # cleanup runs first (size 3 > 2), then k is evaluated

    # Cleanup and check() use the same rule: age >= window means a fresh window.
    assert decision.allowed is expired, f"age {age}: expected expired={expired}"
    if expired:
        assert lim._state["k"] == (age, 1)
        assert "filler1" not in lim._state and "filler2" not in lim._state
    else:
        assert lim._state["k"] == (0.0, 1), "live entry keeps its original window start"
        assert "filler1" in lim._state and "filler2" in lim._state


def test_live_fillers_survive_cleanup_just_before_expiry(monkeypatch):
    monkeypatch.setattr("airwise.ratelimit.CLEANUP_THRESHOLD", 2)
    lim, now = _limiter()
    for key in ("a", "b", "c"):
        lim.check(key)
    now[0] = WINDOW - 1 / 1024
    lim.check("d")  # size 3 > 2: cleanup runs but nothing is expired
    assert sorted(lim._state) == ["a", "b", "c", "d"]


def test_burst_of_unique_keys_is_released_once_the_window_has_passed(monkeypatch):
    monkeypatch.setattr("airwise.ratelimit.CLEANUP_THRESHOLD", 5)
    lim, now = _limiter()
    for i in range(100):
        assert lim.check(f"ip{i}").allowed
    assert len(lim._state) == 100, "nothing is expired during the burst, so all are kept"

    now[0] = WINDOW + 1
    assert lim.check("later").allowed
    assert list(lim._state) == ["later"]


def test_memory_stays_bounded_under_a_steady_flood_of_unique_keys(monkeypatch):
    threshold = 20
    monkeypatch.setattr("airwise.ratelimit.CLEANUP_THRESHOLD", threshold)
    lim, now = _limiter()
    largest = 0
    for i in range(500):
        now[0] = i * 10.0  # one new client every 10 s: at most 6 are live at any time
        assert lim.check(f"ip{i}").allowed
        largest = max(largest, len(lim._state))
    assert largest <= threshold + 1, f"state grew to {largest} entries"
    assert len(lim._state) <= threshold + 1


# --------------------------------------------- cleanup never changes a decision

_steps = st.lists(
    st.tuples(
        st.one_of(
            st.sampled_from([0.0, 1.0, 30.0, 59.0, 60.0, 61.0]),
            st.floats(min_value=0, max_value=130, allow_nan=False),
        ),
        st.integers(min_value=0, max_value=9),  # 10 keys against a threshold of 3
    ),
    max_size=120,
)


@settings(max_examples=150, deadline=None)
@given(steps=_steps, limit=st.integers(min_value=1, max_value=3))
def test_cleanup_never_changes_a_decision_or_a_live_entry(steps, limit):
    now = [0.0]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ratelimit, "CLEANUP_THRESHOLD", 3)  # cleanup runs very often
        lim = FixedWindowLimiter(limit, WINDOW, clock=lambda: now[0])
        model: dict[str, list[float]] = {}  # reference model: no cleanup at all
        for dt, key_id in steps:
            now[0] += dt
            key = f"k{key_id}"
            decision = lim.check(key)

            entry = model.get(key)
            if entry is None or now[0] - entry[0] >= WINDOW:
                model[key] = [now[0], 1]
                expected = True
            elif entry[1] < limit:
                entry[1] += 1
                expected = True
            else:
                expected = False

            assert decision.allowed == expected
            for k, (start, count) in model.items():
                if now[0] - start < WINDOW:  # live in the model: must be intact in the limiter
                    assert lim._state[k] == (start, count)
