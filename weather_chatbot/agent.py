"""Agent module: talks to Grok through LangChain.

Phase 1 sends a single question with a minimal system prompt. Later phases add
the tools, the hand-written tool-calling loop and its security limits.
"""

from typing import Protocol

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_xai import ChatXAI

# The only model this app uses, for every Grok call.
MODEL_NAME: str = "grok-4.7"

# Minimal behavioral instructions sent with every request. Phase 6 replaces
# this with the full hardened prompt. It must never contain secrets.
SYSTEM_PROMPT: str = (
    "You are a friendly weather assistant. You only help with questions about "
    "the current weather and the weather forecast for a named city, plus short "
    "practical advice based on that weather (for example, whether to bring an "
    "umbrella). Politely decline anything else, such as code, homework, essays "
    "or general questions, and say you can only help with weather. "
    "Keep answers short and plain."
)


class ChatModel(Protocol):
    """Anything with LangChain's ``invoke(messages)`` interface."""

    def invoke(self, input: list[BaseMessage]) -> BaseMessage: ...


def create_model() -> ChatXAI:
    """Create the Grok chat model. Reads ``XAI_API_KEY`` from the environment."""
    return ChatXAI(model="grok-4.7")


def build_messages(user_text: str) -> list[BaseMessage]:
    """Build the request: the system prompt first, then the user's message.

    User text only ever travels in a user message, never in the system prompt.
    """
    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_text)]


def ask(model: ChatModel, user_text: str) -> str:
    """Send one question to the model and return its complete reply text."""
    response = model.invoke(build_messages(user_text))
    return response.text
