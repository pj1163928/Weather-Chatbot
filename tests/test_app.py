"""Runs the Streamlit page headlessly with a temporary .env and a fake model."""

import pytest
import streamlit as st
from langchain_core.messages import AIMessage
from streamlit.testing.v1 import AppTest

import weather_chatbot.agent as agent
import weather_chatbot.config as config

APP = str(config.ENV_PATH.parent / "app.py")
FAKE_XAI_KEY = "xai-test-not-a-real-key"


class FakeModel:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, input):
        self.calls += 1
        return AIMessage(content="It's sunny and 72°F in Chicago.")


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


@pytest.mark.parametrize(
    "env_text",
    [
        pytest.param("", id="missing"),
        pytest.param("XAI_API_KEY=<GET-API-KEY-ON-CANVAS>\n", id="placeholder"),
    ],
)
def test_unconfigured_xai_key_shows_setup_message(
    use_env_file, no_model_allowed, env_text
):
    use_env_file(env_text)

    at = AppTest.from_file(APP).run()

    assert not at.exception
    assert len(at.error) == 1
    assert "Setup needed" in at.error[0].value
    assert "XAI_API_KEY" in at.error[0].value
    assert len(at.chat_input) == 0  # the page stopped before the chat box


def test_chats_while_openweather_key_is_placeholder(use_env_file, monkeypatch):
    use_env_file(
        f"XAI_API_KEY={FAKE_XAI_KEY}\nOPENWEATHER_API_KEY=<YOUR_OPENWEATHER_API_KEY>\n"
    )
    fake = FakeModel()
    monkeypatch.setattr(agent, "create_model", lambda: fake)

    at = AppTest.from_file(APP).run()
    assert not at.error
    at.chat_input[0].set_value("What's the weather in Chicago?").run()

    assert not at.exception
    assert fake.calls == 1
    replies = [m for m in at.chat_message if m.name == "assistant"]
    assert replies[-1].markdown[0].value == "It's sunny and 72°F in Chicago."
