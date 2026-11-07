"""Weather tools module: city validation, OpenWeather lookups and the tools.

Phase 2 builds the current-weather path. Phase 3 adds the forecast tool, and
Phase 4 adds caching.

Every tool returns a plain dict. A successful lookup has ``"kind":
"current_weather"``. A problem has ``"kind": "error"`` and a short message
the model can pass on. Tool results never contain the API key.
"""

import logging
import re
import unicodedata
from typing import Annotated, Any

import requests
from langchain_core.tools import InjectedToolArg, tool
from pydantic import BaseModel, Field

from weather_chatbot.config import openweather_key

logger = logging.getLogger(__name__)

# --- Security limits and settings -------------------------------------------

# The longest city argument the model may pass to a tool (security limit).
MAX_CITY_LENGTH: int = 60

# The only non-letter characters a city argument may contain.
ALLOWED_CITY_PUNCTUATION: frozenset[str] = frozenset(" ,-.")

# Every OpenWeather request gives up after this many seconds.
REQUEST_TIMEOUT_SECONDS: int = 10

# Units OpenWeather understands. The app picks one; the model never does.
SUPPORTED_UNITS: tuple[str, ...] = ("imperial", "metric")

# Phase 4 replaces this fixed choice with the sidebar °F/°C toggle.
DEFAULT_UNITS: str = "imperial"

# OpenWeather icon codes look like "10d" or "01n".
ICON_PATTERN: re.Pattern[str] = re.compile(r"\d{2}[dn]")

GEOCODING_URL: str = "https://api.openweathermap.org/geo/1.0/direct"
CURRENT_WEATHER_URL: str = "https://api.openweathermap.org/data/2.5/weather"

# --- Messages the model sees in error results ---------------------------------

INVALID_CITY_MESSAGE: str = (
    "That location name can't be looked up. City names may use only letters, "
    "spaces, commas, hyphens and periods, up to 60 characters. Ask the user to "
    "rephrase the city name."
)
CITY_NOT_FOUND_MESSAGE: str = (
    "City not found. Politely tell the user you couldn't find that place, and "
    "suggest checking the spelling or adding a state or country."
)
SERVICE_UNAVAILABLE_MESSAGE: str = (
    "The weather service is unavailable right now. Tell the user to try again shortly."
)


class WeatherServiceError(Exception):
    """OpenWeather couldn't be reached or refused a request.

    The message is always safe to log: a status code or an error type, never
    a URL (OpenWeather URLs carry the API key).
    """


def is_valid_city(city: str) -> bool:
    """Return True if ``city`` is safe to send to OpenWeather.

    After trimming surrounding spaces, the name must be 1 to
    ``MAX_CITY_LENGTH`` characters long, contain at least one letter, and use
    only letters (any language), spaces, commas, hyphens and periods.
    """
    # NFC joins "e" + accent mark into one letter, so "Zürich" counts as letters.
    name = unicodedata.normalize("NFC", city).strip()
    if not name or len(name) > MAX_CITY_LENGTH:
        return False
    if not any(char.isalpha() for char in name):
        return False
    return all(char.isalpha() or char in ALLOWED_CITY_PUNCTUATION for char in name)


def fetch_json(url: str, params: dict[str, Any]) -> Any:
    """GET ``url`` with ``params`` and return the decoded JSON.

    Times out after ``REQUEST_TIMEOUT_SECONDS``. Any failure becomes a
    ``WeatherServiceError`` with a safe message. ``from None`` drops the
    original exception, because its text includes the full URL and key.
    """
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        raise WeatherServiceError(f"OpenWeather HTTP {status}") from None
    except requests.RequestException as exc:
        raise WeatherServiceError(f"OpenWeather {type(exc).__name__}") from None


def geocoding_query(city: str) -> str:
    """Tidy a validated city for OpenWeather: "Springfield, IL" -> "Springfield,IL"."""
    parts = [part.strip() for part in city.split(",")]
    return ",".join(part for part in parts if part)


def format_location(match: dict[str, Any]) -> str:
    """Join a geocoding match's name, state and country, skipping blanks."""
    parts = [match.get("name"), match.get("state"), match.get("country")]
    return ", ".join(str(part) for part in parts if part)


def geocode(city: str) -> dict[str, Any] | None:
    """Return OpenWeather's top geocoding match for ``city``, or None if none."""
    matches = fetch_json(
        GEOCODING_URL,
        {"q": geocoding_query(city), "limit": 1, "appid": openweather_key()},
    )
    if not isinstance(matches, list) or not matches:
        return None
    return matches[0]


def parse_current_weather(
    data: dict[str, Any], location: str, units: str
) -> dict[str, Any]:
    """Turn OpenWeather's current-weather JSON into the dict the UI and model use."""
    condition = data["weather"][0]
    icon = str(condition.get("icon", ""))
    return {
        "kind": "current_weather",
        "location": location,
        "temperature": data["main"]["temp"],
        "feels_like": data["main"]["feels_like"],
        "humidity": data["main"]["humidity"],
        "wind_speed": data["wind"]["speed"],
        "condition": condition["description"],
        # Only a well-formed code is kept, because the UI builds a URL from it.
        "icon": icon if ICON_PATTERN.fullmatch(icon) else None,
        "units": units,
    }


def error_result(error: str, message: str) -> dict[str, Any]:
    """Build the result a tool returns when it can't give weather data."""
    return {"kind": "error", "error": error, "message": message}


def lookup_current_weather(city: str, units: str = DEFAULT_UNITS) -> dict[str, Any]:
    """Validate ``city``, geocode it and return its current weather.

    Problems come back as error results, never as exceptions, so the model
    can explain them politely.
    """
    if units not in SUPPORTED_UNITS:
        raise ValueError(f"Unsupported units: {units!r}")
    # Checked before any network call, so injected arguments never leave the app.
    if not is_valid_city(city):
        return error_result("invalid_city", INVALID_CITY_MESSAGE)
    try:
        match = geocode(city)
        if match is None:
            return error_result("city_not_found", CITY_NOT_FOUND_MESSAGE)
        data = fetch_json(
            CURRENT_WEATHER_URL,
            {
                "lat": match["lat"],
                "lon": match["lon"],
                "units": units,
                "appid": openweather_key(),
            },
        )
        return parse_current_weather(data, format_location(match), units)
    except WeatherServiceError as exc:
        # Phase 7 replaces this with full error mapping and redacted logging.
        logger.warning("Current-weather lookup failed: %s", exc)
        return error_result("service_unavailable", SERVICE_UNAVAILABLE_MESSAGE)
    except (KeyError, IndexError, TypeError):
        logger.warning("Current-weather lookup failed: unexpected response shape")
        return error_result("service_unavailable", SERVICE_UNAVAILABLE_MESSAGE)


class CurrentWeatherInput(BaseModel):
    """Input for ``get_current_weather``. The model only sees ``city``."""

    city: str = Field(
        description=(
            "The place to look up: a city name, optionally followed by a state "
            "code (US only) and a 2-letter ISO country code, separated by "
            "commas. Examples: 'Paris', 'Paris, FR', 'Springfield, IL, US'."
        )
    )
    # InjectedToolArg hides this field from the model. The app fills it in.
    units: Annotated[str, InjectedToolArg] = DEFAULT_UNITS


@tool(args_schema=CurrentWeatherInput)
def get_current_weather(city: str, units: str = DEFAULT_UNITS) -> dict[str, Any]:
    """Get the current weather for one city from OpenWeather.

    Returns temperature, feels-like temperature, humidity, wind speed, a
    condition description and the resolved location name.
    """
    return lookup_current_weather(city, units)


# Every tool the agent binds to the model. Phase 3 adds get_weather_forecast.
WEATHER_TOOLS = [get_current_weather]
