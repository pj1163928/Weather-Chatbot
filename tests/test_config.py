"""Tests for the startup key check.

These prove only that a key is configured and not a placeholder. They don't
(and can't) prove xAI or OpenWeather accepts the key; the live app confirms that.
"""

import pytest

from weather_chatbot.config import (
    check_keys,
    openweather_key,
    secret_values,
    setup_message,
)

# Obviously fake, but shaped like real configured values.
CONFIGURED = "xai-test0000000000000000000000000000000000000000"
CONFIGURED_OW = "0" * 32

# Placeholder-style values every key must refuse.
UNCONFIGURED = [
    pytest.param(None, id="none"),
    pytest.param("", id="empty"),
    pytest.param("   ", id="whitespace"),
    pytest.param("<GET-API-KEY-ON-CANVAS>", id="prd-xai-placeholder"),
    pytest.param("<YOUR_OPENWEATHER_API_KEY>", id="prd-openweather-placeholder"),
    pytest.param("your_xai_api_key_here", id="old-xai-placeholder"),
    pytest.param("your_openweather_api_key_here", id="old-openweather-placeholder"),
    pytest.param("<anything in angle brackets>", id="angle-bracket-placeholder"),
]


@pytest.mark.parametrize("value", UNCONFIGURED)
def test_check_keys_refuses_missing_or_placeholder_xai_key(value):
    env = {"XAI_API_KEY": value, "OPENWEATHER_API_KEY": CONFIGURED_OW}

    assert check_keys(env) == ["XAI_API_KEY"]


@pytest.mark.parametrize("value", UNCONFIGURED)
def test_check_keys_refuses_missing_or_placeholder_openweather_key(value):
    env = {"XAI_API_KEY": CONFIGURED, "OPENWEATHER_API_KEY": value}

    assert check_keys(env) == ["OPENWEATHER_API_KEY"]


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        pytest.param({}, ["XAI_API_KEY", "OPENWEATHER_API_KEY"], id="both-missing"),
        pytest.param(
            {"XAI_API_KEY": CONFIGURED},
            ["OPENWEATHER_API_KEY"],
            id="openweather-missing-is-refused-from-phase-2",
        ),
        pytest.param(
            {"XAI_API_KEY": CONFIGURED, "OPENWEATHER_API_KEY": CONFIGURED_OW},
            [],
            id="both-configured",
        ),
        pytest.param(
            {
                "XAI_API_KEY": f"  {CONFIGURED}  ",
                "OPENWEATHER_API_KEY": f"\t{CONFIGURED_OW}\n",
            },
            [],
            id="configured-with-padding",
        ),
    ],
)
def test_check_keys_requires_both_keys(env, expected):
    assert check_keys(env) == expected


def test_setup_message_names_every_failing_key_and_no_values():
    message = setup_message(["XAI_API_KEY", "OPENWEATHER_API_KEY"])

    assert "`XAI_API_KEY` and `OPENWEATHER_API_KEY` are missing" in message
    assert "is missing" in setup_message(["OPENWEATHER_API_KEY"])


def test_openweather_key_reads_the_environment(monkeypatch):
    monkeypatch.setenv("OPENWEATHER_API_KEY", f"  {CONFIGURED_OW}  ")

    assert openweather_key() == CONFIGURED_OW


def test_secret_values_gives_the_configured_keys_for_redaction(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", f" {CONFIGURED} ")
    monkeypatch.setenv("OPENWEATHER_API_KEY", CONFIGURED_OW)

    assert secret_values() == [CONFIGURED, CONFIGURED_OW]


@pytest.mark.parametrize("value", UNCONFIGURED)
def test_secret_values_leaves_out_blank_and_placeholder_keys(monkeypatch, value):
    # Redacting a blank value would break the text; placeholders aren't secret.
    if value is None:
        monkeypatch.delenv("XAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("XAI_API_KEY", value)
    monkeypatch.setenv("OPENWEATHER_API_KEY", CONFIGURED_OW)

    assert secret_values() == [CONFIGURED_OW]
