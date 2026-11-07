"""The rate limiter: 20 messages per session and a 3-second cooldown.

Time comes from a ``FakeClock``, so no test sleeps.
"""

import dataclasses
from pathlib import Path

import pytest

import weather_chatbot.security as security
from tests.conftest import FakeClock
from weather_chatbot.security import (
    COOLDOWN_MESSAGE,
    COOLDOWN_SECONDS,
    LAYER_RATE_LIMIT,
    MAX_MESSAGES_PER_SESSION,
    RATE_LIMIT_KEY,
    SESSION_CAP_MESSAGE,
    RateLimiter,
    UsageCounters,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_messages_1_to_20_are_allowed_and_message_21_is_blocked():
    assert MAX_MESSAGES_PER_SESSION == 20
    clock = FakeClock()
    limiter = RateLimiter({}, clock=clock)

    decisions = []
    for _ in range(22):
        decisions.append(limiter.check())
        clock.advance(COOLDOWN_SECONDS)  # always wait out the cooldown

    assert decisions[:20] == [None] * 20, "messages 1-20 must all be allowed"
    for number, blocked in ((21, decisions[20]), (22, decisions[21])):
        assert blocked is not None, f"message {number} must be blocked"
        assert blocked.layer == LAYER_RATE_LIMIT
        assert blocked.reason == "session_cap"
        assert blocked.message == SESSION_CAP_MESSAGE


def test_the_cooldown_blocks_at_2_99_seconds_and_allows_at_exactly_3_00():
    assert COOLDOWN_SECONDS == 3.0
    clock = FakeClock()
    limiter = RateLimiter({}, clock=clock)

    assert limiter.check() is None, "the first message of a session is allowed"

    clock.advance(2.99)
    blocked = limiter.check()
    assert blocked is not None, "a message 2.99 s after the last one is blocked"
    assert blocked.layer == LAYER_RATE_LIMIT
    assert blocked.reason == "cooldown"
    assert blocked.message == COOLDOWN_MESSAGE

    # The blocked attempt didn't restart the wait: 3.00 s after the last
    # allowed message is allowed, and that message restarts it.
    clock.advance(0.01)
    assert limiter.check() is None, "a message at exactly 3.00 s is allowed"
    assert limiter.check() is not None, "0 s after an allowed message is blocked"


# --- Ordinary tests -------------------------------------------------------------


def test_the_counters_live_in_their_own_entry_next_to_the_chat_history():
    clock = FakeClock()
    state = {"messages": [{"role": "user", "content": "hi"}]}
    RateLimiter(state, clock=clock).check()

    assert state[RATE_LIMIT_KEY] == UsageCounters(
        messages_allowed=1, last_message_at=clock.now
    )
    # Clearing the history doesn't touch them.
    state["messages"] = []
    assert state[RATE_LIMIT_KEY].messages_allowed == 1


def test_a_new_limiter_over_the_same_state_carries_on_counting():
    # The app builds a new RateLimiter on every rerun; the count must survive.
    clock, state = FakeClock(), {}
    for _ in range(MAX_MESSAGES_PER_SESSION):
        assert RateLimiter(state, clock=clock).check() is None
        clock.advance(COOLDOWN_SECONDS)

    assert RateLimiter(state, clock=clock).check().reason == "session_cap"


def test_a_blocked_attempt_changes_nothing():
    clock, state = FakeClock(), {}
    limiter = RateLimiter(state, clock=clock)
    limiter.check()
    before = state[RATE_LIMIT_KEY]

    clock.advance(1.0)
    assert limiter.check().reason == "cooldown"
    assert state[RATE_LIMIT_KEY] is before

    state[RATE_LIMIT_KEY] = UsageCounters(MAX_MESSAGES_PER_SESSION, None)
    capped = state[RATE_LIMIT_KEY]
    assert limiter.check().reason == "session_cap"
    assert state[RATE_LIMIT_KEY] is capped


def test_the_session_cap_is_checked_before_the_cooldown():
    clock = FakeClock()
    state = {RATE_LIMIT_KEY: UsageCounters(MAX_MESSAGES_PER_SESSION, clock.now)}

    # Both limits fail; the cap is the one reported.
    assert RateLimiter(state, clock=clock).check().reason == "session_cap"


def test_the_counters_cant_be_changed_in_place():
    counters = UsageCounters(messages_allowed=20, last_message_at=5.0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        counters.messages_allowed = 0


def test_only_the_security_module_refers_to_the_counters():
    # Nothing else in the app may read or write the counters' entry directly.
    sources = [
        PROJECT_ROOT / "app.py",
        *(PROJECT_ROOT / "weather_chatbot").glob("*.py"),
    ]
    offenders = [
        path.name
        for path in sources
        if path.name != "security.py"
        and (
            "RATE_LIMIT_KEY" in (text := path.read_text(encoding="utf-8"))
            or RATE_LIMIT_KEY in text
            or "UsageCounters" in text
        )
    ]
    assert offenders == []


def test_the_default_clock_can_be_replaced(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(security, "monotonic_now", clock)
    limiter = RateLimiter({})

    assert limiter.check() is None
    assert limiter.counters.last_message_at == clock.now
