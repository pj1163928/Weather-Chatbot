"""Shared test helpers: a fake OpenWeather that answers from saved sample JSON."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import weather_chatbot.weather as weather

FIXTURES = Path(__file__).parent / "fixtures" / "openweather"

# Obviously fake. Tests check it is sent to OpenWeather and never shown.
FAKE_OW_KEY = "openweather-test-not-a-real-key"

# Geocoding query (as the tool sends it, lower-cased) -> sample file.
SAMPLE_PLACES: dict[str, str] = {
    "paris": "geocode_paris.json",
    "london": "geocode_london.json",
    "springfield,il,us": "geocode_springfield_il.json",
    "seattle": "geocode_seattle.json",
    "seattle,wa,us": "geocode_seattle.json",
}

# Rounded latitude of each sample place -> its current-weather sample file.
SAMPLE_CURRENT_WEATHER: dict[int, str] = {
    48: "current_paris.json",
    51: "current_london.json",
    39: "current_paris.json",  # Springfield reuses the Paris sample readings.
    47: "current_london.json",  # Seattle reuses the London sample readings.
}

# Rounded latitude of each sample place -> its 5-day forecast sample file.
SAMPLE_FORECASTS: dict[int, str] = {
    47: "forecast_seattle.json",
}

# The moment the forecast samples were "fetched": 15:00 on Friday, Nov 6 in
# Seattle. The fake fixes the clock here, so "Today" is always Nov 6.
SAMPLE_NOW = datetime(2026, 11, 6, 23, 0, tzinfo=UTC)


def load_fixture(name: str) -> Any:
    """Load one saved OpenWeather sample response."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeOpenWeather:
    """Stands in for OpenWeather's API: records each request, answers from samples.

    Unknown places geocode to an empty list, as the real API does.
    """

    # The fake key the fixture puts in the environment.
    api_key = FAKE_OW_KEY

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def fetch_json(self, url: str, params: dict[str, Any]) -> Any:
        self.requests.append((url, dict(params)))
        if url == weather.GEOCODING_URL:
            sample = SAMPLE_PLACES.get(params["q"].casefold(), "geocode_empty.json")
            return load_fixture(sample)
        if url == weather.CURRENT_WEATHER_URL:
            return load_fixture(SAMPLE_CURRENT_WEATHER[int(params["lat"])])
        if url == weather.FORECAST_URL:
            return load_fixture(SAMPLE_FORECASTS[int(params["lat"])])
        raise AssertionError(f"unexpected OpenWeather URL: {url}")

    @property
    def geocoded(self) -> list[str]:
        """The place names sent to the geocoding API, in order."""
        return [p["q"] for url, p in self.requests if url == weather.GEOCODING_URL]

    @property
    def weather_requests(self) -> list[dict[str, Any]]:
        """The parameters of each current-weather request, in order."""
        return [p for url, p in self.requests if url == weather.CURRENT_WEATHER_URL]

    @property
    def forecast_requests(self) -> list[dict[str, Any]]:
        """The parameters of each forecast request, in order."""
        return [p for url, p in self.requests if url == weather.FORECAST_URL]


@pytest.fixture
def sample_json():
    """Give a test the ``load_fixture`` loader for the saved sample responses."""
    return load_fixture


@pytest.fixture
def fake_openweather(monkeypatch) -> FakeOpenWeather:
    """Replace every OpenWeather request with the sample-JSON fake.

    It also fixes the clock at ``SAMPLE_NOW``, so the forecast samples' first
    day is always "Today".
    """
    fake = FakeOpenWeather()
    monkeypatch.setattr(weather, "fetch_json", fake.fetch_json)
    monkeypatch.setattr(weather, "utc_now", lambda: SAMPLE_NOW)
    monkeypatch.setenv("OPENWEATHER_API_KEY", FAKE_OW_KEY)
    return fake
