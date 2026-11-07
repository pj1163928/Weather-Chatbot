"""UI module: the Streamlit chat page.

Run with:  uv run streamlit run app.py
"""

import logging
from typing import Any

import streamlit as st

from weather_chatbot.agent import create_model, run_agent
from weather_chatbot.config import check_keys, load_env, setup_message
from weather_chatbot.weather import DEFAULT_UNITS

# Shown when the xAI call fails. Phase 7 replaces this with full error mapping
# and redacted logging.
UNAVAILABLE_MESSAGE = (
    "Sorry, the weather assistant is unavailable right now. Please try again "
    "shortly. If this keeps happening, check that `XAI_API_KEY` in `.env` is "
    "correct."
)

# Labels for each units setting: (temperature, wind speed).
UNIT_LABELS: dict[str, tuple[str, str]] = {
    "imperial": ("°F", "mph"),
    "metric": ("°C", "m/s"),
}

# OpenWeather's icon images. The code is checked by the weather module first.
ICON_URL = "https://openweathermap.org/img/wn/{code}@2x.png"

logger = logging.getLogger(__name__)


@st.cache_resource
def get_model():
    """Create the Grok model once and reuse it across reruns."""
    return create_model()


def weather_cards(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the tool results that can be drawn as cards (successful lookups)."""
    return [result for result in tool_results if result["kind"] == "current_weather"]


def render_current_weather(card: dict[str, Any]) -> None:
    """Draw a current-weather card from a raw tool result, never from model text.

    Location and condition come from OpenWeather, so they are shown with
    ``st.text``, which displays them as plain text (no Markdown or links).
    """
    temperature_unit, speed_unit = UNIT_LABELS[card["units"]]
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            if card["icon"]:
                st.image(
                    ICON_URL.format(code=card["icon"]), width=64, alt=card["condition"]
                )
            with st.container(gap=None):
                st.text(card["location"])
                st.text(card["condition"].capitalize())
        with st.container(horizontal=True):
            st.metric(
                "Temperature",
                f"{round(card['temperature'])}{temperature_unit}",
                border=True,
            )
            st.metric(
                "Feels like",
                f"{round(card['feels_like'])}{temperature_unit}",
                border=True,
            )
            st.metric("Humidity", f"{card['humidity']}%", border=True)
            st.metric("Wind", f"{round(card['wind_speed'])} {speed_unit}", border=True)


st.set_page_config(page_title="Weather Chatbot", page_icon="🌦️")
st.title("🌦️ Weather Chatbot")
st.caption("Ask about the current weather for a city.")

# Startup key check: stop before any model is created or API call is made.
problems = check_keys(load_env())
if problems:
    st.error(setup_message(problems))
    st.stop()

# Each message is {"role", "content"}, plus "cards" (raw tool results) for
# assistant replies, so cards re-render with the history.
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        for card in message.get("cards", []):
            render_current_weather(card)

if prompt := st.chat_input("Ask about the weather in a city…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        # No streaming: the reply appears only once it is complete.
        with st.spinner("Checking the weather…"):
            try:
                # Phase 4 replaces DEFAULT_UNITS with the sidebar toggle.
                result = run_agent(get_model(), prompt, DEFAULT_UNITS)
                reply, cards = result.reply, weather_cards(result.tool_results)
            except Exception as exc:  # noqa: BLE001 - user sees a safe message
                # Log only the error type: messages can carry request details.
                logger.warning("xAI call failed: %s", type(exc).__name__)
                reply, cards = UNAVAILABLE_MESSAGE, []
        st.markdown(reply)
        for card in cards:
            render_current_weather(card)
    st.session_state.messages.append(
        {"role": "assistant", "content": reply, "cards": cards}
    )
