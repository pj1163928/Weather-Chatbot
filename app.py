"""UI module: the Streamlit chat page.

Run with:  uv run streamlit run app.py
"""

import logging
from datetime import date
from typing import Any

import streamlit as st

from weather_chatbot.agent import create_model, run_agent
from weather_chatbot.config import check_keys, load_env, setup_message
from weather_chatbot.weather import DEFAULT_UNITS, SUPPORTED_UNITS, UNIT_LABELS

# Shown when the xAI call fails. Phase 7 replaces this with full error mapping
# and redacted logging.
UNAVAILABLE_MESSAGE = (
    "Sorry, the weather assistant is unavailable right now. Please try again "
    "shortly. If this keeps happening, check that `XAI_API_KEY` in `.env` is "
    "correct."
)

# The session-state key of the sidebar °F/°C toggle.
UNITS_KEY = "units"

# OpenWeather's icon images. The code is checked by the weather module first.
ICON_URL = "https://openweathermap.org/img/wn/{code}@2x.png"

# Tool results with these kinds are drawn as cards. Errors are not.
CARD_KINDS: tuple[str, ...] = ("current_weather", "forecast")

logger = logging.getLogger(__name__)


@st.cache_resource
def get_model():
    """Create the Grok model once and reuse it across reruns."""
    return create_model()


def units_toggle() -> str:
    """Draw the sidebar °F/°C toggle and return the chosen units.

    This is the only place units are chosen; the model can't change them.
    Returns ``"imperial"`` (°F, the default) or ``"metric"`` (°C).
    """
    with st.sidebar:
        choice = st.segmented_control(
            "Units",
            SUPPORTED_UNITS,
            default=DEFAULT_UNITS,
            required=True,
            format_func=lambda units: UNIT_LABELS[units][0],
            key=UNITS_KEY,
        )
        st.caption("Applies to new lookups. Earlier cards keep their units.")
    return choice if choice in SUPPORTED_UNITS else DEFAULT_UNITS


def weather_cards(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the tool results that can be drawn as cards (successful lookups)."""
    return [result for result in tool_results if result["kind"] in CARD_KINDS]


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


def forecast_rows(card: dict[str, Any]) -> list[dict[str, str]]:
    """Turn a forecast tool result into the table's rows, one per day.

    For example: {"Day": "Today, Nov 6 (partial)", "High / Low": "53°F / 47°F",
    "Condition": "Light rain", "Chance of rain": "64%"}.
    """
    temperature_unit, _ = UNIT_LABELS[card["units"]]
    rows = []
    for day in card["days"]:
        when = date.fromisoformat(day["date"])
        name = f"{day['label']}, {when:%b} {when.day}"
        if day["partial"]:
            name += " (partial)"
        rows.append(
            {
                "Day": name,
                "High / Low": (
                    f"{round(day['high'])}{temperature_unit} / "
                    f"{round(day['low'])}{temperature_unit}"
                ),
                "Condition": day["condition"].capitalize(),
                "Chance of rain": f"{day['chance_of_rain']}%",
            }
        )
    return rows


def render_forecast(card: dict[str, Any]) -> None:
    """Draw the 5-day forecast table from a raw tool result, never from model text.

    ``st.dataframe`` shows cells as plain text (unlike ``st.table``, which
    renders Markdown), so OpenWeather's text can't add formatting or links.
    """
    with st.container(border=True):
        st.text(f"5-day forecast: {card['location']}")
        st.dataframe(
            forecast_rows(card),
            hide_index=True,
            height="content",
            alt=f"5-day forecast for {card['location']}",
        )
        if any(day["partial"] for day in card["days"]):
            st.caption("A partial day covers only the hours the forecast includes.")


def render_card(card: dict[str, Any]) -> None:
    """Draw one weather card: current-weather tiles or the forecast table."""
    if card["kind"] == "forecast":
        render_forecast(card)
    else:
        render_current_weather(card)


st.set_page_config(page_title="Weather Chatbot", page_icon="🌦️")
st.title("🌦️ Weather Chatbot")
st.caption("Ask about the current weather or the 5-day forecast for a city.")

# Startup key check: stop before any model is created or API call is made.
problems = check_keys(load_env())
if problems:
    st.error(setup_message(problems))
    st.stop()

units = units_toggle()

# Each message is {"role", "content"}, plus "cards" (raw tool results) for
# assistant replies, so cards re-render with the history.
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        for card in message.get("cards", []):
            render_card(card)

if prompt := st.chat_input("Ask about the weather in a city…"):
    # The conversation so far, before this question. The agent trims it to
    # the last two exchanges, text only.
    earlier_messages = list(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        # No streaming: the reply appears only once it is complete.
        with st.spinner("Checking the weather…"):
            try:
                result = run_agent(get_model(), prompt, units, earlier_messages)
                reply, cards = result.reply, weather_cards(result.tool_results)
            except Exception as exc:  # noqa: BLE001 - user sees a safe message
                # Log only the error type: messages can carry request details.
                logger.warning("xAI call failed: %s", type(exc).__name__)
                reply, cards = UNAVAILABLE_MESSAGE, []
        st.markdown(reply)
        for card in cards:
            render_card(card)
    st.session_state.messages.append(
        {"role": "assistant", "content": reply, "cards": cards}
    )
