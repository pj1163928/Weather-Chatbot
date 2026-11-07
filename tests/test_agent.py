"""Tests for the agent module, using fake models (no API key, no network).

The loop's security limits (round cap, repeated calls) are in
test_agent_loop.py.
"""

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_xai import ChatXAI

from weather_chatbot.agent import (
    EMPTY_REPLY_MESSAGE,
    MAX_REPLY_TOKENS,
    SYSTEM_PROMPT,
    create_model,
    run_agent,
)


class RecordingFakeModel:
    """Stands in for Grok: replies from a script, records requests and tools."""

    def __init__(self, *replies: AIMessage) -> None:
        self.replies = list(replies)
        self.calls: list[list] = []
        self.bound_tool_names: list[str] = []

    def bind_tools(self, tools):
        self.bound_tool_names = [tool.name for tool in tools]
        return self

    def invoke(self, input):
        self.calls.append(list(input))
        return self.replies.pop(0)


def ask_for(city_args: dict, name: str = "get_current_weather") -> AIMessage:
    """A model reply that requests one tool call."""
    call = {"name": name, "args": city_args, "id": "call_1", "type": "tool_call"}
    return AIMessage(content="", tool_calls=[call])


def test_run_agent_returns_the_model_reply_text():
    model = RecordingFakeModel(AIMessage(content="It's 72°F and sunny in Chicago."))

    result = run_agent(model, "What's the weather in Chicago?")

    assert result.reply == "It's 72°F and sunny in Chicago."
    assert result.tool_results == []


def test_get_current_weather_is_bound_with_bind_tools():
    model = RecordingFakeModel(AIMessage(content="ok"))

    run_agent(model, "What's the weather in Chicago?")

    assert model.bound_tool_names == ["get_current_weather"]


def test_every_request_starts_with_the_system_prompt():
    model = RecordingFakeModel(AIMessage(content="ok"), AIMessage(content="ok"))

    run_agent(model, "What's the weather in Chicago?")
    run_agent(model, "And in Boston?")

    assert len(model.calls) == 2
    for messages in model.calls:
        assert isinstance(messages[0], SystemMessage)
        assert messages[0].content == SYSTEM_PROMPT


def test_user_text_travels_only_in_a_user_message():
    model = RecordingFakeModel(AIMessage(content="ok"))
    question = "What's the weather in Chicago?"

    run_agent(model, question)

    system, user = model.calls[0]
    assert isinstance(user, HumanMessage)
    assert user.content == question
    assert question not in system.content


def test_system_prompt_sets_the_weather_role():
    assert SYSTEM_PROMPT.strip()
    assert "weather" in SYSTEM_PROMPT.lower()


def test_tool_result_goes_back_to_the_model_and_to_the_ui(fake_openweather):
    model = RecordingFakeModel(
        ask_for({"city": "Paris"}), AIMessage(content="Paris: 59°F, light rain.")
    )

    result = run_agent(model, "What's the weather in Paris?")

    assert result.reply == "Paris: 59°F, light rain."
    assert [r["location"] for r in result.tool_results] == ["Paris, Île-de-France, FR"]
    tool_message = model.calls[1][-1]
    assert isinstance(tool_message, ToolMessage)
    assert json.loads(tool_message.content)["temperature"] == 59.02


def test_the_api_key_never_reaches_the_model(fake_openweather):
    model = RecordingFakeModel(ask_for({"city": "Paris"}), AIMessage(content="ok"))

    run_agent(model, "What's the weather in Paris?")

    # The key went to OpenWeather, but nothing the model saw contains it.
    key = fake_openweather.api_key
    assert fake_openweather.weather_requests[0]["appid"] == key
    for messages in model.calls:
        for message in messages:
            assert key not in str(message.content)


def test_units_come_from_the_app_not_the_model(fake_openweather):
    # The model tries to choose units itself; the app's choice wins.
    model = RecordingFakeModel(
        ask_for({"city": "Paris", "units": "standard"}), AIMessage(content="ok")
    )

    result = run_agent(model, "What's the weather in Paris in Kelvin?", "metric")

    assert fake_openweather.weather_requests[0]["units"] == "metric"
    assert result.tool_results[0]["units"] == "metric"


def test_unknown_tool_and_bad_arguments_become_error_results(fake_openweather):
    model = RecordingFakeModel(
        ask_for({"city": "Paris"}, name="delete_everything"),
        ask_for({"town": "Paris"}),
        AIMessage(content="Sorry, I couldn't look that up."),
    )

    result = run_agent(model, "What's the weather in Paris?")

    assert [r["error"] for r in result.tool_results] == [
        "unknown_tool",
        "bad_arguments",
    ]
    assert fake_openweather.requests == []
    assert result.reply == "Sorry, I couldn't look that up."


def test_an_empty_model_reply_becomes_a_fixed_message():
    model = RecordingFakeModel(AIMessage(content="   "))

    assert run_agent(model, "What's the weather?").reply == EMPTY_REPLY_MESSAGE


def test_model_is_chatxai_grok_4_7_with_reply_cap_and_timeout(monkeypatch):
    # A fake key so the client can be built; nothing is sent over the network.
    monkeypatch.setenv("XAI_API_KEY", "xai-test-not-a-real-key")

    model = create_model()

    assert isinstance(model, ChatXAI)
    assert model.model_name == "grok-4.7"
    assert MAX_REPLY_TOKENS == 500
    assert model.max_tokens == MAX_REPLY_TOKENS
    assert model.request_timeout == 10
