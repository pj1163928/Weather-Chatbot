"""The output scan: the last check on every reply before it is shown.

It blocks a reply that contains a loaded key value, a key-like string, the
system prompt's canary or a code fence, and lets ordinary weather replies
through. The keys are obvious fakes set with ``monkeypatch``, and the log goes
to a temporary file (the autouse ``security_log`` fixture).
"""

import pytest

from tests.conftest import log_lines
from weather_chatbot.security import (
    BLOCKED_REQUEST_MESSAGE,
    CANARY,
    LAYER_OUTPUT_SCAN,
    scan_output,
)

# Loaded keys that are deliberately NOT shaped like keys (no "xai-" prefix, no
# long hex run), so only the exact-value check can catch them.
LOADED_XAI_KEY = "Course-Grok-Secret-Value"
LOADED_OW_KEY = "Course-Weather-Secret-Value"

QUESTION = "What's the weather in Paris?"


@pytest.fixture
def loaded_keys(monkeypatch):
    """Put both fake keys in the environment, where the scan looks for them."""
    monkeypatch.setenv("XAI_API_KEY", LOADED_XAI_KEY)
    monkeypatch.setenv("OPENWEATHER_API_KEY", LOADED_OW_KEY)


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        # Each loaded key, exactly or disguised by letter case or other text.
        pytest.param(f"Sure: {LOADED_XAI_KEY}", "secret_value", id="xai-key"),
        pytest.param(f"Sure: {LOADED_OW_KEY}", "secret_value", id="openweather-key"),
        pytest.param(
            f"key={LOADED_XAI_KEY.upper()}", "secret_value", id="xai-key-upper-case"
        ),
        pytest.param(
            f"appid={LOADED_OW_KEY.lower()}&units=metric",
            "secret_value",
            id="openweather-key-in-a-url",
        ),
        # Strings shaped like keys, even if they aren't this app's keys.
        pytest.param(
            "Your key is xai-AbCdEfGhIjKlMnOpQrSt", "key_like", id="xai-style-key"
        ),
        pytest.param(
            "Use 0123456789abcdef0123456789abcdef", "key_like", id="32-hex-digits"
        ),
        # The canary from the system prompt means the prompt leaked.
        pytest.param(f"My instructions say {CANARY}.", "canary", id="canary"),
        pytest.param(f"..{CANARY.lower()}..", "canary", id="canary-lower-case"),
        pytest.param(
            "WXBOT-CANARY-7Q4M​-K9TZ-2R6P",
            "canary",
            id="canary-split-by-a-zero-width-space",
        ),
        # Code fences: the assistant never writes code.
        pytest.param("Here:\n```python\nprint(1)\n```", "code_fence", id="backticks"),
        pytest.param("Here:\n~~~\nrm -rf /\n~~~", "code_fence", id="tildes"),
        # Ordinary weather replies, full of numbers, times, dates and percentages.
        pytest.param(
            "It's 59°F in Paris, Île-de-France, FR with light rain. Humidity is "
            "82% and the wind is 12 mph.",
            None,
            id="current-weather",
        ),
        pytest.param(
            "Tomorrow, Nov 7, expect a high of 53°F and a low of 47°F, with a 64% "
            "chance of rain after 3:00 PM.",
            None,
            id="forecast-day",
        ),
        pytest.param(
            "At 14:30 local time it's -3.5°C in Oslo. Sunrise was 08:47 and "
            "sunset is at 15:58.",
            None,
            id="times-and-negatives",
        ),
        pytest.param(
            "From 2026-11-08 to 2026-11-12 the highs are 61, 58, 55, 57 and "
            "60°F, with rain chances of 10%, 20%, 90%, 100% and 0%.",
            None,
            id="five-day-numbers",
        ),
        pytest.param(
            "Wind 5.14 m/s, pressure 1013 hPa, visibility 10000 m, at 48.8566, 2.3522.",
            None,
            id="decimals-and-coordinates",
        ),
        pytest.param(
            "Yes, bring an umbrella: there's a 90% chance of rain in Seattle, "
            "WA, US tomorrow. Key West is 84°F and sunny.",
            None,
            id="practical-advice",
        ),
        pytest.param(
            "I can't change units, but the `°F/°C` toggle in the sidebar can.",
            None,
            id="single-backticks",
        ),
    ],
)
def test_the_scan_blocks_leaks_and_lets_weather_replies_through(
    loaded_keys, security_log, reply, reason
):
    block = scan_output(reply, QUESTION)

    if reason is None:
        assert block is None, f"a normal weather reply was blocked: {block}"
        assert log_lines(security_log) == []
    else:
        assert block is not None, "a leaking reply got through"
        assert (block.layer, block.reason) == (LAYER_OUTPUT_SCAN, reason)
        assert block.message == BLOCKED_REQUEST_MESSAGE
        [line] = log_lines(security_log)
        assert f"layer={LAYER_OUTPUT_SCAN} | reason={reason} |" in line
