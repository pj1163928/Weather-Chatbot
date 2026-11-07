"""Tests for the tool-calling loop's security limits, using fake models.

No API key and no network: Grok is a scripted fake, and OpenWeather is the
sample-JSON fake from conftest.py.
"""

import json
from itertools import count

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import weather_chatbot.weather as weather
from tests.conftest import log_lines
from weather_chatbot.agent import MAX_TOOL_ROUNDS, TOOL_LIMIT_MESSAGE, run_agent

# Different real-looking cities, so no call ever repeats an earlier one.
CITIES = ["Paris", "London", "Tokyo", "Berlin", "Madrid", "Rome", "Oslo", "Lima"]


def tool_call(city: str, call_id: str) -> dict:
    """One get_current_weather request, shaped the way LangChain gives it."""
    return {
        "name": "get_current_weather",
        "args": {"city": city},
        "id": call_id,
        "type": "tool_call",
    }


class ToolHungryFakeModel:
    """Stands in for a runaway Grok: every reply asks for a new city's weather."""

    def __init__(self) -> None:
        self.calls: list[list] = []
        self._ids = count(1)

    def bind_tools(self, tools):
        return self

    def invoke(self, input):
        self.calls.append(list(input))
        city = CITIES[len(self.calls) - 1]
        call = tool_call(city, f"call_{next(self._ids)}")
        return AIMessage(content="", tool_calls=[call])


class ScriptedFakeModel:
    """Stands in for Grok: returns the given replies in order, records requests."""

    def __init__(self, replies: list[AIMessage]) -> None:
        self.replies = list(replies)
        self.calls: list[list] = []

    def bind_tools(self, tools):
        return self

    def invoke(self, input):
        self.calls.append(list(input))
        return self.replies.pop(0)


@pytest.fixture
def tool_ran_for(monkeypatch) -> list[str]:
    """Spy on the tool's work: every city it starts running for, in order.

    This sees a call even if it would fail before reaching OpenWeather.
    """
    cities: list[str] = []
    real_lookup = weather.lookup_current_weather

    def spy_lookup(city, units=weather.DEFAULT_UNITS):
        cities.append(city)
        return real_lookup(city, units)

    monkeypatch.setattr(weather, "lookup_current_weather", spy_lookup)
    return cities


def test_tool_loop_stops_after_three_rounds_with_a_safe_message(
    fake_openweather, tool_ran_for, security_log
):
    model = ToolHungryFakeModel()

    result = run_agent(model, "What's the weather in Paris?")

    assert MAX_TOOL_ROUNDS == 3
    # The loop ends with the fixed safe message, not a model reply.
    assert result.reply == TOOL_LIMIT_MESSAGE
    # Exactly 3 rounds of tools ran: one OpenWeather lookup per round.
    assert fake_openweather.geocoded == ["Paris", "London", "Tokyo"]
    # Grok was asked 4 times: 3 tool rounds, then the request for a 4th
    # round, which was refused instead of run.
    assert len(model.calls) == MAX_TOOL_ROUNDS + 1
    # The 4th response asked for Berlin. That call never ran, not even briefly:
    # the tool itself was never started for it.
    assert tool_ran_for == ["Paris", "London", "Tokyo"]
    assert "Berlin" not in fake_openweather.geocoded

    # The stop is written to the security log once, with the question.
    (line,) = log_lines(security_log)
    assert "| layer=loop_limit | reason=tool_round_limit |" in line
    assert line.endswith('snippet="What\'s the weather in Paris?"')


def test_repeated_identical_tool_call_is_blocked_but_a_new_city_runs(
    fake_openweather, tool_ran_for, security_log
):
    final_answer = "Paris is 59°F with light rain; London is 52°F and cloudy."
    model = ScriptedFakeModel(
        [
            AIMessage(content="", tool_calls=[tool_call("Paris", "call_1")]),
            AIMessage(content="", tool_calls=[tool_call("Paris", "call_2")]),
            AIMessage(content="", tool_calls=[tool_call("London", "call_3")]),
            AIMessage(content=final_answer),
        ]
    )

    result = run_agent(model, "What's the weather in Paris and London?")

    # The repeated Paris call was never sent to OpenWeather, and the tool
    # never even started for it. London, a different city, still ran.
    assert tool_ran_for == ["Paris", "London"]
    assert fake_openweather.geocoded == ["Paris", "London"]
    assert len(fake_openweather.weather_requests) == 2

    # London's lookup succeeded and its real data came back for the card.
    locations = [
        r["location"] for r in result.tool_results if r["kind"] == "current_weather"
    ]
    assert locations == ["Paris, Île-de-France, FR", "London, England, GB"]

    # Grok was told the repeat was blocked (every tool call gets an answer).
    third_request = model.calls[2]
    answer_to_repeat = third_request[-1]
    assert isinstance(answer_to_repeat, ToolMessage)
    assert answer_to_repeat.tool_call_id == "call_2"
    assert json.loads(answer_to_repeat.content)["error"] == "repeated_call"

    # The loop carried on and returned the model's final answer.
    assert result.reply == final_answer

    # The one blocked repeat is written to the security log once.
    (line,) = log_lines(security_log)
    assert "| layer=loop_limit | reason=repeated_tool_call |" in line
