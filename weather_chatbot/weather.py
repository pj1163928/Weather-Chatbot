"""Weather tools module: city validation, OpenWeather lookups and the tools.

Two tools share one path (validate the city, geocode it, fetch by
coordinates): ``get_current_weather`` and ``get_weather_forecast``.
Successful OpenWeather responses are cached for 10 minutes by tool, city and
units.

Every tool returns a plain dict. A successful lookup has ``"kind":
"current_weather"`` or ``"kind": "forecast"``. A problem has ``"kind":
"error"`` and a short message the model can pass on. Tool results never
contain the API key.
"""

import logging
import re
import threading
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Hashable
from datetime import UTC, date, datetime, timedelta, timezone
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

# Used when no units are given. The UI always passes the sidebar toggle's choice.
DEFAULT_UNITS: str = "imperial"

# Labels for each units setting: (temperature, wind speed). Tool results carry
# them, so the model's reply and the cards use the same units.
UNIT_LABELS: dict[str, tuple[str, str]] = {
    "imperial": ("°F", "mph"),
    "metric": ("°C", "m/s"),
}

# OpenWeather icon codes look like "10d" or "01n".
ICON_PATTERN: re.Pattern[str] = re.compile(r"\d{2}[dn]")

GEOCODING_URL: str = "https://api.openweathermap.org/geo/1.0/direct"
CURRENT_WEATHER_URL: str = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL: str = "https://api.openweathermap.org/data/2.5/forecast"

# The forecast always shows exactly this many local days, never more or fewer.
FORECAST_DAYS: int = 5

# OpenWeather's forecast has one entry every 3 hours, so a whole day has 8.
# A local date with fewer entries than this in the response is "partial".
ENTRIES_PER_FULL_DAY: int = 8

# A cached OpenWeather response is reused for this many seconds (10 minutes),
# so repeat questions are instant and stay within the free tier.
CACHE_TTL_SECONDS: float = 600

# The most responses the cache holds. Past this, the oldest is dropped.
MAX_CACHE_ENTRIES: int = 128

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
FORECAST_INCOMPLETE_MESSAGE: str = (
    "The forecast service didn't return a full five days right now. Tell the "
    "user the forecast is unavailable and to try again shortly."
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
        "temperature_unit": UNIT_LABELS[units][0],
        "wind_speed_unit": UNIT_LABELS[units][1],
    }


class IncompleteForecastError(ValueError):
    """The forecast response covers fewer than ``FORECAST_DAYS`` local dates."""


def group_by_local_date(
    entries: list[dict[str, Any]], city_time_zone: timezone
) -> dict[date, list[dict[str, Any]]]:
    """Sort 3-hour entries into lists by their date in the city's time zone.

    OpenWeather gives each entry's time (``dt``) in UTC. Converting it to the
    city's time zone first means an entry like 03:00 UTC lands on the right
    local day (for Seattle, that's 19:00 the day before).
    """
    days: dict[date, list[dict[str, Any]]] = {}
    for item in entries:
        local_date = datetime.fromtimestamp(item["dt"], city_time_zone).date()
        days.setdefault(local_date, []).append(item)
    return days


def summarize_forecast(data: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Group OpenWeather's 3-hour forecast into exactly five local days.

    The rule:

    - Entries are grouped by the city's local date. The city's offset from UTC
      comes from the response (``city.timezone``, in seconds).
    - The five days are the first five local dates on or after the city's
      local "today" (worked out from ``now``). Earlier and later dates are
      dropped.
    - A day is ``partial`` when the response has fewer than
      ``ENTRIES_PER_FULL_DAY`` (8) entries for that local date. Each day is
      counted on its own, so a full day stays full whatever time the
      forecast starts.
    - If fewer than five dates are left, ``IncompleteForecastError`` is
      raised. Missing days are never invented.

    The offset is fixed for the whole response, so if daylight saving time
    starts or ends during the five days, later entries are off by an hour.
    """
    city_time_zone = timezone(timedelta(seconds=data["city"]["timezone"]))
    today = now.astimezone(city_time_zone).date()
    days = group_by_local_date(data["list"], city_time_zone)
    dates = sorted(day for day in days if day >= today)[:FORECAST_DAYS]
    if len(dates) < FORECAST_DAYS:
        raise IncompleteForecastError(f"Forecast covers only {len(dates)} days")
    return [summarize_day(day, days[day], today) for day in dates]


def day_label(day: date, today: date) -> str:
    """Name a forecast day: "Today", "Tomorrow" or the weekday ("Sunday")."""
    if day == today:
        return "Today"
    if day == today + timedelta(days=1):
        return "Tomorrow"
    return day.strftime("%A")


def summarize_day(
    day: date, entries: list[dict[str, Any]], today: date
) -> dict[str, Any]:
    """Summarize one local day's 3-hour entries.

    - ``high`` is the largest ``temp_max`` and ``low`` the smallest ``temp_min``.
    - ``condition`` is the most common description. A tie goes to the one that
      appears first in the day.
    - ``chance_of_rain`` is the highest ``pop`` (0 to 1) as a whole percent. A
      missing ``pop`` counts as 0.
    - ``partial`` is True when the day has fewer than ``ENTRIES_PER_FULL_DAY``
      entries.
    """
    # Counter.most_common lists equal counts in the order first seen, which
    # gives the "first in the day wins a tie" rule.
    conditions = Counter(item["weather"][0]["description"] for item in entries)
    return {
        "date": day.isoformat(),
        "label": day_label(day, today),
        "high": max(item["main"]["temp_max"] for item in entries),
        "low": min(item["main"]["temp_min"] for item in entries),
        "condition": conditions.most_common(1)[0][0],
        "chance_of_rain": round(max(item.get("pop", 0) for item in entries) * 100),
        "partial": len(entries) < ENTRIES_PER_FULL_DAY,
    }


def error_result(error: str, message: str) -> dict[str, Any]:
    """Build the result a tool returns when it can't give weather data."""
    return {"kind": "error", "error": error, "message": message}


def parse_forecast(
    data: dict[str, Any], location: str, units: str, now: datetime
) -> dict[str, Any]:
    """Turn OpenWeather's 5-day / 3-hour JSON into the dict the UI and model use.

    Raises ``IncompleteForecastError`` if fewer than five local days come back.
    """
    return {
        "kind": "forecast",
        "location": location,
        "units": units,
        "temperature_unit": UNIT_LABELS[units][0],
        "days": summarize_forecast(data, now),
    }


def utc_now() -> datetime:
    """The current time in UTC. Tests pass their own ``now`` instead."""
    return datetime.now(UTC)


class TimedCache:
    """A small cache whose entries expire ``ttl_seconds`` after being stored.

    An entry is fresh while its age is under ``ttl_seconds``; at exactly
    ``ttl_seconds`` it has expired. When storing would go over
    ``max_entries``, expired entries are dropped first, then the oldest.

    ``clock`` returns the current time in seconds. It defaults to
    ``time.monotonic``; tests pass a fake clock so they can jump ahead
    without waiting.
    """

    def __init__(
        self,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        max_entries: int = MAX_CACHE_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.clock = clock
        # key -> (time stored, value). Dicts keep insertion order, oldest first.
        self._entries: dict[Hashable, tuple[float, Any]] = {}
        # Streamlit serves each browser tab from its own thread.
        self._lock = threading.Lock()

    def __len__(self) -> int:
        """How many entries are stored, including any not yet cleaned out."""
        return len(self._entries)

    def _is_fresh(self, stored_at: float, now: float) -> bool:
        return now - stored_at < self.ttl_seconds

    def get(self, key: Hashable) -> Any | None:
        """Return the value stored under ``key``, or None if missing or expired."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if not self._is_fresh(stored_at, self.clock()):
                del self._entries[key]
                return None
            return value

    def put(self, key: Hashable, value: Any) -> None:
        """Store ``value`` under ``key``, keeping at most ``max_entries``."""
        with self._lock:
            now = self.clock()
            self._entries.pop(key, None)  # re-stored entries count as newest
            self._entries[key] = (now, value)
            if len(self._entries) > self.max_entries:
                self._entries = {
                    k: entry
                    for k, entry in self._entries.items()
                    if self._is_fresh(entry[0], now)
                }
            while len(self._entries) > self.max_entries:
                del self._entries[next(iter(self._entries))]  # the oldest


# The cache every lookup shares. It lives as long as the app process, so it
# lasts across Streamlit reruns. Tests replace it with a fresh one.
WEATHER_CACHE = TimedCache()


def cache_key(url: str, city: str, units: str) -> tuple[str, str, str]:
    """The cache key for one lookup: which tool (its URL), the city and units.

    The city is tidied the way it is sent to geocoding and compared without
    case, so "Paris" and "paris " share an entry. Different units, or the
    other tool, always get a separate entry.
    """
    name = geocoding_query(unicodedata.normalize("NFC", city)).casefold()
    return (url, name, units)


def look_up_weather(
    city: str,
    units: str,
    url: str,
    parse: Callable[[Any, str], dict[str, Any]],
    lookup_name: str,
) -> dict[str, Any]:
    """The path both tools share: validate, check the cache, geocode, fetch, parse.

    ``parse(data, location)`` turns OpenWeather's JSON into the tool's result.
    ``lookup_name`` names the lookup in log lines (never the URL, which would
    carry the key). Problems come back as error results, never as exceptions,
    so the model can explain them politely.

    The cache holds the resolved location and OpenWeather's raw JSON, not the
    parsed result, so a cached forecast still works out "Today" from the
    current time. Only a response that parsed successfully is cached; errors
    never are, so the next question tries OpenWeather again.
    """
    if units not in SUPPORTED_UNITS:
        raise ValueError(f"Unsupported units: {units!r}")
    # Checked before any network call, so injected arguments never leave the app.
    if not is_valid_city(city):
        return error_result("invalid_city", INVALID_CITY_MESSAGE)
    key = cache_key(url, city, units)
    cached = WEATHER_CACHE.get(key)
    try:
        if cached is not None:
            location, data = cached
        else:
            match = geocode(city)
            if match is None:
                return error_result("city_not_found", CITY_NOT_FOUND_MESSAGE)
            location = format_location(match)
            data = fetch_json(
                url,
                {
                    "lat": match["lat"],
                    "lon": match["lon"],
                    "units": units,
                    "appid": openweather_key(),
                },
            )
        result = parse(data, location)
        if cached is None:
            WEATHER_CACHE.put(key, (location, data))
        return result
    except WeatherServiceError as exc:
        # Phase 7 replaces this with full error mapping and redacted logging.
        logger.warning("%s lookup failed: %s", lookup_name, exc)
        return error_result("service_unavailable", SERVICE_UNAVAILABLE_MESSAGE)
    except (KeyError, IndexError, TypeError):
        logger.warning("%s lookup failed: unexpected response shape", lookup_name)
        return error_result("service_unavailable", SERVICE_UNAVAILABLE_MESSAGE)


def lookup_current_weather(city: str, units: str = DEFAULT_UNITS) -> dict[str, Any]:
    """Validate ``city``, geocode it and return its current weather."""
    return look_up_weather(
        city,
        units,
        CURRENT_WEATHER_URL,
        lambda data, location: parse_current_weather(data, location, units),
        "Current-weather",
    )


def lookup_weather_forecast(
    city: str, units: str = DEFAULT_UNITS, now: datetime | None = None
) -> dict[str, Any]:
    """Validate ``city``, geocode it and return its five-day forecast.

    ``now`` decides which local day is "today". It defaults to the real time;
    tests pass a fixed time. A response with fewer than five local days gives
    a ``forecast_incomplete`` error result instead of invented days.
    """
    current_time = now or utc_now()
    try:
        return look_up_weather(
            city,
            units,
            FORECAST_URL,
            lambda data, location: parse_forecast(data, location, units, current_time),
            "Forecast",
        )
    except IncompleteForecastError as exc:
        logger.warning("Forecast lookup failed: %s", exc)
        return error_result("forecast_incomplete", FORECAST_INCOMPLETE_MESSAGE)


class CityInput(BaseModel):
    """Input for both weather tools. The model only sees ``city``."""

    city: str = Field(
        description=(
            "The place to look up: a city name, optionally followed by a state "
            "code (US only) and a 2-letter ISO country code, separated by "
            "commas. Examples: 'Paris', 'Paris, FR', 'Springfield, IL, US'."
        )
    )
    # InjectedToolArg hides this field from the model. The app fills it in.
    units: Annotated[str, InjectedToolArg] = DEFAULT_UNITS


@tool(args_schema=CityInput)
def get_current_weather(city: str, units: str = DEFAULT_UNITS) -> dict[str, Any]:
    """Get the current weather for one city from OpenWeather.

    Returns temperature, feels-like temperature, humidity, wind speed, a
    condition description and the resolved location name.
    """
    return lookup_current_weather(city, units)


@tool(args_schema=CityInput)
def get_weather_forecast(city: str, units: str = DEFAULT_UNITS) -> dict[str, Any]:
    """Get the 5-day forecast for one city from OpenWeather.

    Use it for later today, tomorrow or any of the next five days, and for
    practical advice such as whether to bring an umbrella. Returns the
    resolved location and five days, each with a label ("Today", "Tomorrow"
    or a weekday), its date, the high and low temperature, the most common
    condition, the highest chance of rain in percent, and whether the day is
    partial (only some hours of it are in the forecast).
    """
    return lookup_weather_forecast(city, units)


# Every tool the agent binds to the model.
WEATHER_TOOLS = [get_current_weather, get_weather_forecast]
