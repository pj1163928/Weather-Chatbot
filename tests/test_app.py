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
        self.requests: list[list] = []  # the messages sent with each call

    def bind_tools(self, tools):
        return self

    def invoke(self, input):
        self.calls += 1
        self.requests.append(list(input))
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
    ["Today, Nov 6 (partial)", "53°F / 47°F", "Light rain", "64%", "88%", "14 mph"],
    ["Tomorrow, Nov 7", "52°F / 44°F", "Moderate rain", "100%", "91%", "15 mph"],
    ["Sunday, Nov 8", "51°F / 44°F", "Broken clouds", "24%", "81%", "11 mph"],
    ["Monday, Nov 9", "51°F / 41°F", "Clear sky", "0%", "65%", "7 mph"],
    ["Tuesday, Nov 10", "50°F / 42°F", "Few clouds", "41%", "84%", "15 mph"],
]

# The day tiles' icons: each day's most common condition, as a daytime icon.
SEATTLE_ICONS = [
    f"https://openweathermap.org/img/wn/{code}@2x.png"
    for code in ["10d", "10d", "04d", "01d", "02d"]
]


def forecast_table(message) -> list[list[str]]:
    """The rows of the one forecast table inside a chat message."""
    (table,) = message.dataframe
    assert list(table.value.columns) == [
        "Day",
        "High / Low",
        "Condition",
        "Chance of rain",
        "Humidity",
        "Wind",
    ]
    return table.value.values.tolist()


def forecast_tiles_look_right(message) -> None:
    """Check the forecast card's header and its five day tiles."""
    texts = [t.value for t in message.text]
    # The location, then each tile's condition, all as plain text.
    assert texts == [
        "Seattle, Washington, US",
        "Light rain",
        "Moderate rain",
        "Broken clouds",
        "Clear sky",
        "Few clouds",
    ]
    icons = [url for image in message.image for url in image.value]
    assert icons == SEATTLE_ICONS
    markdown = [m.value for m in message.markdown]
    for name, temperatures, rain, wind in [
        ("Today", "53°F / 47°F", "64%", "14 mph"),
        ("Tomorrow", "52°F / 44°F", "100%", "15 mph"),
        ("Tuesday", "50°F / 42°F", "41%", "15 mph"),
    ]:
        assert f"**{name}**" in markdown
        assert f"**{temperatures}**" in markdown
        assert f":material/water_drop: {rain}  \n:material/air: {wind}" in markdown
    captions = [c.value for c in message.caption]
    assert captions[:3] == ["5-day forecast", "Nov 6 · partial", "Nov 7"]


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
    forecast_tiles_look_right(first_reply)
    assert forecast_table(first_reply) == SEATTLE_TABLE
    assert len(first_reply.metric) == 0  # no current-weather tiles

    # A new message re-renders the page; the card must still be there.
    at.chat_input[0].set_value("Thanks!").run()

    assert not at.exception
    replies = assistant_messages(at)
    forecast_tiles_look_right(replies[0])
    assert forecast_table(replies[0]) == SEATTLE_TABLE
    assert len(replies[1].dataframe) == 0


def test_a_forecast_card_saved_before_humidity_and_wind_still_renders(
    use_env_file, monkeypatch
):
    # A card stored in an open session before this change has no humidity,
    # wind or icon. After a code reload it must still draw, with dashes.
    use_env_file(BOTH_KEYS)
    old_day = {
        "date": "2026-11-06",
        "label": "Today",
        "high": 53.0,
        "low": 47.0,
        "condition": "light rain",
        "chance_of_rain": 64,
        "partial": False,
    }
    old_card = {
        "kind": "forecast",
        "location": "Seattle, Washington, US",
        "units": "imperial",
        "days": [old_day] * 5,
    }
    at = AppTest.from_file(APP)
    at.session_state["messages"] = [
        {"role": "user", "content": "Forecast for Seattle?"},
        {"role": "assistant", "content": "Here it is.", "cards": [old_card]},
    ]
    at.run()

    assert not at.exception
    (row, *_) = forecast_table(assistant_messages(at)[0])
    assert row[-2:] == ["–", "–"]
    assert len(assistant_messages(at)[0].image) == 0


def test_a_failing_xai_call_shows_a_friendly_message(use_env_file, monkeypatch):
    use_env_file(BOTH_KEYS)
    monkeypatch.setattr(agent, "create_model", BrokenFakeModel)
    at = AppTest.from_file(APP).run()

    at.chat_input[0].set_value("What's the weather in Paris?").run()

    assert not at.exception
    reply = assistant_messages(at)[-1].markdown[0].value
    assert reply.startswith("Sorry, the weather assistant is unavailable")
    assert "api.x.ai" not in reply


# --- Units toggle and conversation memory ----------------------------------------


def units_toggle(at: AppTest):
    """The sidebar °F/°C toggle."""
    (toggle,) = at.sidebar.segmented_control
    return toggle


def test_the_units_toggle_is_in_the_sidebar_and_starts_on_fahrenheit(
    use_env_file, no_model_allowed
):
    use_env_file(BOTH_KEYS)

    at = AppTest.from_file(APP).run()

    toggle = units_toggle(at)
    assert toggle.label == "Units"
    assert toggle.options == ["°F", "°C"]
    assert toggle.value == "imperial"


def test_switching_to_celsius_changes_new_lookups_and_keeps_old_cards(
    use_env_file, fake_openweather, monkeypatch
):
    use_env_file(BOTH_KEYS)
    fake = ScriptedFakeModel(
        asks_for_weather_in("Paris"),
        AIMessage(content="It's 59°F in Paris."),
        asks_for_weather_in("London"),
        AIMessage(content="It's 52°C in London."),
    )
    monkeypatch.setattr(agent, "create_model", lambda: fake)
    at = AppTest.from_file(APP).run()

    at.chat_input[0].set_value("Weather in Paris?").run()
    units_toggle(at).set_value("metric").run()
    at.chat_input[0].set_value("Weather in London?").run()

    assert not at.exception
    assert [p["units"] for p in fake_openweather.weather_requests] == [
        "imperial",
        "metric",
    ]
    paris, london = assistant_messages(at)
    # The sample readings don't change with units; only the labels do.
    assert card_metrics(paris)["Temperature"] == "59°F"
    assert card_metrics(paris)["Wind"] == "9 mph"
    assert card_metrics(london)["Temperature"] == "52°C"
    assert card_metrics(london)["Wind"] == "7 m/s"


def test_a_follow_up_sends_the_earlier_exchange_as_text_only(
    use_env_file, fake_openweather, monkeypatch
):
    use_env_file(BOTH_KEYS)
    fake = ScriptedFakeModel(
        asks_for_weather_in("Seattle"),
        AIMessage(content="It's 52°F in Seattle."),
        asks_for_weather_in("Seattle", tool="get_weather_forecast"),
        AIMessage(content="Tomorrow in Seattle: rain likely."),
    )
    monkeypatch.setattr(agent, "create_model", lambda: fake)
    at = AppTest.from_file(APP).run()

    at.chat_input[0].set_value("What's the weather in Seattle?").run()
    at.chat_input[0].set_value("What about tomorrow?").run()

    assert not at.exception
    follow_up_request = fake.requests[2]  # the first call for the 2nd question
    assert [m.content for m in follow_up_request[1:]] == [
        "What's the weather in Seattle?",
        "It's 52°F in Seattle.",
        "What about tomorrow?",
    ]
    # The earlier card's data stayed out of the request.
    assert "Washington" not in " ".join(str(m.content) for m in follow_up_request)
    assert fake_openweather.geocoded == ["Seattle", "Seattle"]
    assert len(assistant_messages(at)[1].dataframe) == 1
