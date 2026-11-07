"""Agent module: talks to Grok through LangChain and runs the tool-calling loop.

The loop is hand-written (not a prebuilt agent, not AgentExecutor), so its
security limits are visible constants below.
"""

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langchain_xai import ChatXAI
from pydantic import ValidationError

from weather_chatbot.weather import (
    DEFAULT_UNITS,
    REQUEST_TIMEOUT_SECONDS,
    WEATHER_TOOLS,
    error_result,
)

logger = logging.getLogger(__name__)

# The only model this app uses, for every Grok call.
MODEL_NAME: str = "grok-4.7"

# --- Security limits --------------------------------------------------------

# Rounds of tool calls allowed per question. After the last round the model
# gets one more turn to answer; asking for more tools then ends the loop.
MAX_TOOL_ROUNDS: int = 3

# Longest reply Grok may write, in tokens. Stops essay- or code-length output.
MAX_REPLY_TOKENS: int = 500

# The tools the model may call, looked up by the name it asks for.
TOOLS_BY_NAME: dict[str, BaseTool] = {tool.name: tool for tool in WEATHER_TOOLS}

# Sent back to the model when it repeats a tool call it already made.
REPEATED_CALL_MESSAGE: str = (
    "This exact lookup was already made for this question. Use the earlier "
    "result instead of asking again."
)

# Shown if the model finishes without writing any text.
EMPTY_REPLY_MESSAGE: str = (
    "Sorry, I don't have an answer for that. Please try asking another way."
)

# Shown instead of a reply when the model keeps asking for tools.
TOOL_LIMIT_MESSAGE: str = (
    "Sorry, I couldn't finish looking that up. Please ask about one city at a "
    "time and try again."
)

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

    def invoke(self, input: list[BaseMessage]) -> AIMessage: ...


class ToolCallingModel(Protocol):
    """A chat model that can be given tools, like ``ChatXAI``."""

    def bind_tools(self, tools: Sequence[BaseTool]) -> ChatModel: ...


@dataclass
class AgentResult:
    """What one question produces: the reply text and the raw tool results.

    The UI draws weather cards from ``tool_results``, never from ``reply``.
    """

    reply: str
    tool_results: list[dict[str, Any]] = field(default_factory=list)


def create_model() -> ChatXAI:
    """Create the Grok chat model. Reads ``XAI_API_KEY`` from the environment."""
    return ChatXAI(
        model="grok-4.7",
        max_tokens=MAX_REPLY_TOKENS,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def build_messages(user_text: str) -> list[BaseMessage]:
    """Build the request: the system prompt first, then the user's message.

    User text only ever travels in a user message, never in the system prompt.
    """
    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_text)]


def call_signature(call: dict[str, Any]) -> str:
    """Describe a tool call as text, so identical calls compare equal.

    Two calls are identical when the tool name and arguments match exactly.
    """
    return json.dumps([call["name"], call["args"]], sort_keys=True)


def run_tool_call(call: dict[str, Any], units: str) -> dict[str, Any]:
    """Run one tool call the model asked for and return the tool's result.

    The app's ``units`` always replace anything the model sent, so the model
    can't choose units. Unknown tools and malformed arguments become error
    results instead of exceptions.
    """
    tool = TOOLS_BY_NAME.get(call["name"])
    if tool is None:
        return error_result("unknown_tool", "That tool doesn't exist.")
    try:
        return tool.invoke({**call["args"], "units": units})
    except ValidationError:
        return error_result("bad_arguments", "The tool arguments were invalid.")


def run_agent(
    model: ToolCallingModel, user_text: str, units: str = DEFAULT_UNITS
) -> AgentResult:
    """Answer one question, letting the model call the weather tools.

    Each pass of the loop asks the model for its next step. If it asks for
    tools, they run (one "tool round") and their results go back to it. After
    ``MAX_TOOL_ROUNDS`` rounds the model gets one more turn to answer. If it
    asks for tools again, those calls are not run and the loop stops with
    ``TOOL_LIMIT_MESSAGE``.
    """
    bound_model = model.bind_tools(WEATHER_TOOLS)
    messages = build_messages(user_text)
    tool_results: list[dict[str, Any]] = []
    calls_already_run: set[str] = set()

    for rounds_done in range(MAX_TOOL_ROUNDS + 1):
        response = bound_model.invoke(messages)
        if not response.tool_calls:
            reply = response.text.strip() or EMPTY_REPLY_MESSAGE
            return AgentResult(reply=reply, tool_results=tool_results)
        if rounds_done == MAX_TOOL_ROUNDS:
            break  # A 4th round was requested: stop without running it.

        messages.append(response)
        for call in response.tool_calls:
            signature = call_signature(call)
            if signature in calls_already_run:
                # Same tool, same arguments: don't run it again. The model
                # still gets an answer, because every tool call needs one.
                # Phase 5 writes this to the security log (layer: loop limit).
                logger.warning("Blocked a repeated tool call: %s", call["name"])
                result = error_result("repeated_call", REPEATED_CALL_MESSAGE)
            else:
                calls_already_run.add(signature)
                result = run_tool_call(call, units)
                tool_results.append(result)
            messages.append(
                ToolMessage(
                    content=json.dumps(result, ensure_ascii=False),
                    tool_call_id=call["id"],
                )
            )

    # Phase 5 writes this to the security log (layer: loop limit).
    logger.warning("Tool loop stopped after %d rounds", MAX_TOOL_ROUNDS)
    return AgentResult(reply=TOOL_LIMIT_MESSAGE, tool_results=tool_results)
