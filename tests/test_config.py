"""Tests for the startup key check.

These prove only that a key is configured and not a placeholder. They don't
(and can't) prove xAI accepts the key; the live chat confirms that.
"""

import pytest

from weather_chatbot.config import check_keys

# Obviously fake, but shaped like a real configured value.
CONFIGURED = "xai-test0000000000000000000000000000000000000000"


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        pytest.param({}, ["XAI_API_KEY"], id="missing"),
        pytest.param({"XAI_API_KEY": None}, ["XAI_API_KEY"], id="none"),
        pytest.param({"XAI_API_KEY": ""}, ["XAI_API_KEY"], id="empty"),
        pytest.param({"XAI_API_KEY": "   "}, ["XAI_API_KEY"], id="whitespace"),
        pytest.param(
            {"XAI_API_KEY": "<GET-API-KEY-ON-CANVAS>"},
            ["XAI_API_KEY"],
            id="prd-placeholder",
        ),
        pytest.param(
            {"XAI_API_KEY": "your_xai_api_key_here"},
            ["XAI_API_KEY"],
            id="old-example-placeholder",
        ),
        pytest.param(
            {"XAI_API_KEY": "<anything in angle brackets>"},
            ["XAI_API_KEY"],
            id="angle-bracket-placeholder",
        ),
        pytest.param({"XAI_API_KEY": CONFIGURED}, [], id="configured"),
        pytest.param(
            {"XAI_API_KEY": f"  {CONFIGURED}  "}, [], id="configured-with-padding"
        ),
        pytest.param(
            {"XAI_API_KEY": CONFIGURED, "OPENWEATHER_API_KEY": None},
            [],
            id="openweather-missing-is-ok-in-phase-1",
        ),
        pytest.param(
            {
                "XAI_API_KEY": CONFIGURED,
                "OPENWEATHER_API_KEY": "<YOUR_OPENWEATHER_API_KEY>",
            },
            [],
            id="openweather-placeholder-is-ok-in-phase-1",
        ),
    ],
)
def test_check_keys_refuses_missing_or_placeholder_xai_key(env, expected):
    assert check_keys(env) == expected
