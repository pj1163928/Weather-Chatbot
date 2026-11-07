"""Tests for the agent module, using a fake model (no API key, no network)."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_xai import ChatXAI

from weather_chatbot.agent import SYSTEM_PROMPT, ask, create_model


class RecordingFakeModel:
    """Stands in for Grok: records every request and returns a fixed reply."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list] = []

    def invoke(self, input):
        self.calls.append(list(input))
        return AIMessage(content=self.reply)


def test_ask_returns_the_model_reply_text():
    model = RecordingFakeModel("It's 72°F and sunny in Chicago.")

    assert ask(model, "What's the weather in Chicago?") == (
        "It's 72°F and sunny in Chicago."
    )


def test_every_request_starts_with_the_system_prompt():
    model = RecordingFakeModel("ok")

    ask(model, "What's the weather in Chicago?")
    ask(model, "And in Boston?")

    assert len(model.calls) == 2
    for messages in model.calls:
        assert isinstance(messages[0], SystemMessage)
        assert messages[0].content == SYSTEM_PROMPT


def test_user_text_travels_only_in_a_user_message():
    model = RecordingFakeModel("ok")
    question = "What's the weather in Chicago?"

    ask(model, question)

    system, user = model.calls[0]
    assert isinstance(user, HumanMessage)
    assert user.content == question
    assert question not in system.content


def test_system_prompt_sets_the_weather_role():
    assert SYSTEM_PROMPT.strip()
    assert "weather" in SYSTEM_PROMPT.lower()


def test_model_is_chatxai_grok_4_7(monkeypatch):
    # A fake key so the client can be built; nothing is sent over the network.
    monkeypatch.setenv("XAI_API_KEY", "xai-test-not-a-real-key")

    model = create_model()

    assert isinstance(model, ChatXAI)
    assert model.model_name == "grok-4.7"
