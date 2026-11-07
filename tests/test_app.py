"""Runs the Streamlit page headlessly with a temporary .env and fake services."""

import pytest
import streamlit as st
from langchain_core.messages import AIMessage
from streamlit.testing.v1 import AppTest

import weather_chatbot.agent as agent
import weather_chatbot.config as config

APP = str(config.ENV_PATH.parent / "app.py")
FAKE_XAI_KEY = "xai-test-not-a-real-key"
FAKE_OW_KEY = "openweather-test-not-a-real-key"
BOTH_KEYS = f"XAI_API_KEY={FAKE_XAI_KEY}\nOPENWEATHER_API_KEY={FAKE_OW_KEY}\n"


class ScriptedFakeModel:
    """Stands in for Grok: returns the given replies in order."""

    def __init__(self, *replies: AIMessage) -> None:
        self.replies = list(replies)
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, input):
        self.calls += 1
        return self.replies.pop(0)


class BrokenFakeModel:
    """Stands in for an xAI outage: every call fails with URL-like details."""

    def bind_tools(self, tools):
        return self

    def invoke(self, input):
        raise RuntimeError("500 from https://api.x.ai/v1/chat/completions")


def asks_for_weather_in(city: str, tool: str = "get_current_weather") -> AIMessage:
    """A model reply that calls ``tool`` (current weather by default) for ``city``."""
    call = {
        "name": tool,
        "args": {"city": city},
        "id": f"call_{tool}_{city}",
        "type": "tool_call",
    }
    return AIMessage(content="", tool_calls=[call])


@pytest.fixture
def use_env_file(tmp_path, monkeypatch):
    """Point the app at a temporary .env; restore the real environment after."""
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    st.cache_resource.clear()

    def write(text: str) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(text, encoding="utf-8")
        monkeypatch.setattr(config, "ENV_PATH", env_file)

    yield write
    st.cache_resource.clear()


@pytest.fixture
def no_model_allowed(monkeypatch):
    def fail():
        raise AssertionError("the model must not be created")

    monkeypatch.setattr(agent, "create_model", fail)


def assistant_messages(at: AppTest) -> list:
    return [m for m in at.chat_message if m.name == "assistant"]


def card_metrics(message) -> dict[str, str]:
    """The metric tiles inside one chat message, as {label: value}."""
    return {metric.label: metric.value for metric in message.metric}


@pytest.mark.parametrize(
    ("env_text", "failing_key"),
    [
        pytest.param(
            f"OPENWEATHER_API_KEY={FAKE_OW_KEY}\n", "XAI_API_KEY", id="xai-missing"
        ),
        pytest.param(
            f"XAI_API_KEY=<GET-API-KEY-ON-CANVAS>\nOPENWEATHER_API_KEY={FAKE_OW_KEY}\n",
            "XAI_API_KEY",
            id="xai-placeholder",
        ),
        pytest.param(
            f"XAI_API_KEY={FAKE_XAI_KEY}\n",
            "OPENWEATHER_API_KEY",
            id="openweather-missing",
        ),
        pytest.param(
            f"XAI_API_KEY={FAKE_XAI_KEY}\n"
            "OPENWEATHER_API_KEY=<YOUR_OPENWEATHER_API_KEY>\n",
            "OPENWEATHER_API_KEY",
            id="openweather-placeholder",
        ),
    ],
)
def test_unconfigured_key_shows_setup_message(
    use_env_file, no_model_allowed, env_text, failing_key
):
    use_env_file(env_text)

    at = AppTest.from_file(APP).run()

    assert not at.exception
    assert len(at.error) == 1
    assert "Setup needed" in at.error[0].value
    assert f"`{failing_key}` is missing" in at.error[0].value
    assert len(at.chat_input) == 0  # the page stopped before the chat box


def test_chats_when_both_keys_are_configured(use_env_file, monkeypatch):
    use_env_file(BOTH_KEYS)
    fake = ScriptedFakeModel(AIMessage(content="Which city would you like?"))
    monkeypatch.setattr(agent, "create_model", lambda: fake)

    at = AppTest.from_file(APP).run()
    assert not at.error
    at.chat_input[0].set_value("What's the weather?").run()

    assert not at.exception
    assert fake.calls == 1
    reply = assistant_messages(at)[-1]
    assert reply.markdown[0].value == "Which city would you like?"
    assert len(reply.metric) == 0  # no lookup, so no card


def test_weather_card_shows_in_the_reply_and_stays_in_history(
    use_env_file, fake_openweather, monkeypatch
):
    use_env_file(BOTH_KEYS)
    fake = ScriptedFakeModel(
        asks_for_weather_in("Paris"),
        AIMessage(content="It's 59°F with light rain in Paris."),
        AIMessage(content="You're welcome!"),
    )
    monkeypatch.setattr(agent, "create_model", lambda: fake)
    at = AppTest.from_file(APP).run()

    at.chat_input[0].set_value("What's the weather in Paris?").run()

    assert not at.exception
    first_reply = assistant_messages(at)[0]
    assert first_reply.markdown[0].value == "It's 59°F with light rain in Paris."
    expected_tiles = {
        "Temperature": "59°F",
        "Feels like": "58°F",
        "Humidity": "82%",
        "Wind": "9 mph",
    }
    assert card_metrics(first_reply) == expected_tiles
    texts = [text.value for text in first_reply.text]
    assert texts == ["Paris, Île-de-France, FR", "Light rain"]
    # The condition icon, built from the checked OpenWeather icon code.
    icons = [url for image in first_reply.image for url in image.value]
    assert icons == ["https://openweathermap.org/img/wn/10d@2x.png"]

    # A new message re-renders the page; the first card must still be there.
    at.chat_input[0].set_value("Thanks!").run()

    assert not at.exception
    replies = assistant_messages(at)
    assert len(replies) == 2
    assert card_metrics(replies[0]) == expected_tiles
    assert len(replies[1].metric) == 0


# The Seattle forecast sample, as the table shows it (the clock is fixed at
# 15:00 on Friday, Nov 6 in Seattle by the fake OpenWeather).
SEATTLE_TABLE = [
    ["Today, Nov 6 (partial)", "53°F / 47°F", "Light rain", "64%"],
    ["Tomorrow, Nov 7", "52°F / 44°F", "Moderate rain", "100%"],
    ["Sunday, Nov 8", "51°F / 44°F", "Broken clouds", "24%"],
    ["Monday, Nov 9", "51°F / 41°F", "Clear sky", "0%"],
    ["Tuesday, Nov 10", "50°F / 42°F", "Few clouds", "41%"],
]


def forecast_table(message) -> list[list[str]]:
    """The rows of the one forecast table inside a chat message."""
    (table,) = message.dataframe
    assert list(table.value.columns) == [
        "Day",
        "High / Low",
        "Condition",
        "Chance of rain",
    ]
    return table.value.values.tolist()


def test_forecast_table_shows_in_the_reply_and_stays_in_history(
    use_env_file, fake_openweather, monkeypatch
):
    use_env_file(BOTH_KEYS)
    fake = ScriptedFakeModel(
        asks_for_weather_in("Seattle", tool="get_weather_forecast"),
        AIMessage(content="Yes, bring an umbrella: tomorrow has a 100% chance."),
        AIMessage(content="You're welcome!"),
    )
    monkeypatch.setattr(agent, "create_model", lambda: fake)
    at = AppTest.from_file(APP).run()

    at.chat_input[0].set_value("Umbrella in Seattle tomorrow?").run()

    assert not at.exception
    first_reply = assistant_messages(at)[0]
    assert first_reply.markdown[0].value.startswith("Yes, bring an umbrella")
    assert [t.value for t in first_reply.text] == [
        "5-day forecast: Seattle, Washington, US"
    ]
    assert forecast_table(first_reply) == SEATTLE_TABLE
    assert len(first_reply.metric) == 0  # no current-weather tiles

    # A new message re-renders the page; the table must still be there.
    at.chat_input[0].set_value("Thanks!").run()

    assert not at.exception
    replies = assistant_messages(at)
    assert forecast_table(replies[0]) == SEATTLE_TABLE
    assert len(replies[1].dataframe) == 0


def test_a_failing_xai_call_shows_a_friendly_message(use_env_file, monkeypatch):
    use_env_file(BOTH_KEYS)
    monkeypatch.setattr(agent, "create_model", BrokenFakeModel)
    at = AppTest.from_file(APP).run()

    at.chat_input[0].set_value("What's the weather in Paris?").run()

    assert not at.exception
    reply = assistant_messages(at)[-1].markdown[0].value
    assert reply.startswith("Sorry, the weather assistant is unavailable")
    assert "api.x.ai" not in reply
