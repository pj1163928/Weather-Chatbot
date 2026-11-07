"""UI module: the Streamlit chat page.

Run with:  uv run streamlit run app.py
"""

import logging
from datetime import date
from typing import Any

import streamlit as st

from weather_chatbot.agent import create_model, run_agent
from weather_chatbot.config import check_keys, load_env, setup_message
from weather_chatbot.security import RateLimiter, check_free_gate
from weather_chatbot.weather import (
    DEFAULT_UNITS,
    SUPPORTED_UNITS,
    UNIT_LABELS,
    plain_condition,
)

# Shown when the xAI call fails. Phase 7 replaces this with full error mapping
# and redacted logging.
UNAVAILABLE_MESSAGE = (
    "Sorry, the weather assistant is unavailable right now. Please try again "
    "shortly. If this keeps happening, check that `XAI_API_KEY` in `.env` is "
    "correct."
)

# The icon shown on a fixed refusal from the free gate.
BLOCKED_ICON = ":material/block:"

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


def short_date(day: dict[str, Any]) -> str:
    """A forecast day's date, like "Nov 6"."""
    when = date.fromisoformat(day["date"])
    return f"{when:%b} {when.day}"


def high_low(day: dict[str, Any], temperature_unit: str) -> str:
    """A forecast day's temperatures, like "53°F / 47°F"."""
    return (
        f"{round(day['high'])}{temperature_unit} / "
        f"{round(day['low'])}{temperature_unit}"
    )


def tile_name(day: dict[str, Any]) -> str:
    """A day tile's short name: "Today", or the weekday shortened ("Sat")."""
    if day["label"] == "Today":
        return "Today"
    return f"{date.fromisoformat(day['date']):%a}"


def humidity_text(day: dict[str, Any]) -> str:
    """A forecast day's average humidity, like "84%" ("–" if not known)."""
    humidity = day.get("humidity")
    return "–" if humidity is None else f"{humidity}%"


def wind_text(day: dict[str, Any], speed_unit: str) -> str:
    """A forecast day's highest wind speed, like "12 mph" ("–" if not known)."""
    wind_speed = day.get("wind_speed")
    return "–" if wind_speed is None else f"{round(wind_speed)} {speed_unit}"


def forecast_rows(card: dict[str, Any]) -> list[dict[str, str]]:
    """Turn a forecast tool result into the table's rows, one per day.

    For example: {"Day": "Today, Nov 6 (partial)", "High / Low": "53°F / 47°F",
    "Condition": "Light rain", "Chance of rain": "64%", "Humidity": "84%",
    "Wind": "12 mph"}.
    """
    temperature_unit, speed_unit = UNIT_LABELS[card["units"]]
    rows = []
    for day in card["days"]:
        name = f"{day['label']}, {short_date(day)}"
        if day["partial"]:
            name += " (partial)"
        rows.append(
            {
                "Day": name,
                "High / Low": high_low(day, temperature_unit),
                # The only OpenWeather text in the table, which renders Markdown.
                "Condition": plain_condition(day["condition"]).capitalize(),
                "Chance of rain": f"{day['chance_of_rain']}%",
                "Humidity": humidity_text(day),
                "Wind": wind_text(day, speed_unit),
            }
        )
    return rows


def render_forecast_day(day: dict[str, Any], units: str) -> None:
    """Draw one day's tile: name, date, icon, condition, high/low, rain and wind.

    Tiles are narrow, so the name is short ("Today", "Sat", "Wed") and the
    temperatures leave out the unit (the card's header says it). The day name,
    date and numbers are the app's own text. The condition comes from
    OpenWeather, so it is shown with ``st.text`` (plain text).
    """
    _, speed_unit = UNIT_LABELS[units]
    st.markdown(f"**{tile_name(day)}**", text_alignment="center")
    when = short_date(day) + (" · partial" if day["partial"] else "")
    st.caption(when, text_alignment="center")
    if day.get("icon"):
        with st.container(horizontal_alignment="center"):
            st.image(ICON_URL.format(code=day["icon"]), width=56, alt=day["condition"])
    st.text(day["condition"].capitalize(), text_alignment="center", width="stretch")
    st.markdown(
        f"**{round(day['high'])}° / {round(day['low'])}°**", text_alignment="center"
    )
    st.markdown(
        f":material/water_drop: {day['chance_of_rain']}%  \n"
        f":material/air: {wind_text(day, speed_unit)}",
        text_alignment="center",
    )


def render_forecast(card: dict[str, Any]) -> None:
    """Draw the 5-day forecast from a raw tool result, never from model text.

    A header with the location, a row of five day tiles like a weather app,
    then a table with every detail.

    The table is a static ``st.table``, not an ``st.dataframe``: a dataframe is
    an interactive grid that catches the mouse wheel, so a chat full of them
    stutters while scrolling. ``st.table`` renders Markdown in its cells, so
    every cell is the app's own text except the condition, which passes
    ``plain_condition`` (plain words only) first.
    """
    temperature_unit, _ = UNIT_LABELS[card["units"]]
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.markdown(":material/location_on:")
            st.text(card["location"])
        st.caption(f"5-day forecast · temperatures in {temperature_unit}")
        days = card["days"]
        for column, day in zip(st.columns(len(days), border=True), days, strict=True):
            with column:
                render_forecast_day(day, card["units"])
        st.table(
            forecast_rows(card),
            hide_index=True,
            border="horizontal",
            alt=f"5-day forecast for {card['location']}",
        )
        if any(day["partial"] for day in card["days"]):
            st.caption("A partial day covers only the hours the forecast includes.")


def render_reply(message: dict[str, Any]) -> None:
    """Draw a reply's text: a fixed refusal as a warning, anything else as Markdown.

    A refusal from the free gate is the app's own text, never the model's.
    """
    if message.get("blocked"):
        st.warning(message["content"], icon=BLOCKED_ICON)
    else:
        st.markdown(message["content"])


def render_card(card: dict[str, Any]) -> None:
    """Draw one weather card: current-weather tiles or the 5-day forecast."""
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
# assistant replies, so cards re-render with the history. A message the free
# gate blocked, and its refusal, also have "blocked": True, which keeps them
# out of the model's memory. The rate-limit counters live in their own
# session-state entry, which only the RateLimiter changes, so clearing this
# list doesn't reset them.
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            render_reply(message)
        else:
            st.markdown(message["content"])
        for card in message.get("cards", []):
            render_card(card)

if prompt := st.chat_input("Ask about the weather in a city…"):
    # The pre-filter counts the message without spaces at either end, so the
    # trimmed text is what goes on to Grok.
    text = prompt.strip()
    # The conversation so far, before this question. The agent trims it to
    # the last two exchanges, text only.
    earlier_messages = list(st.session_state.messages)
    question = {"role": "user", "content": text}
    st.session_state.messages.append(question)
    with st.chat_message("user"):
        st.markdown(text)

    # The free gate (rate limits, then the pre-filter) runs before any Grok
    # call. A blocked message gets a fixed refusal and costs nothing.
    block = check_free_gate(text, RateLimiter(st.session_state))

    with st.chat_message("assistant"):
        if block is not None:
            question["blocked"] = True
            answer = {
                "role": "assistant",
                "content": block.message,
                "cards": [],
                "blocked": True,
            }
            render_reply(answer)
        else:
            # No streaming: the reply appears only once it is complete.
            with st.spinner("Checking the weather…"):
                try:
                    result = run_agent(get_model(), text, units, earlier_messages)
                    reply, cards = result.reply, weather_cards(result.tool_results)
                except Exception as exc:  # noqa: BLE001 - user sees a safe message
                    # Log only the error type: messages can carry request details.
                    logger.warning("xAI call failed: %s", type(exc).__name__)
                    reply, cards = UNAVAILABLE_MESSAGE, []
            answer = {"role": "assistant", "content": reply, "cards": cards}
            render_reply(answer)
            for card in cards:
                render_card(card)
    st.session_state.messages.append(answer)
