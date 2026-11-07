"""The 10-minute weather cache, with a controllable clock (no test waits).

An entry is fresh while it is under ``CACHE_TTL_SECONDS`` (600) old and has
expired at exactly 600 seconds. Lookups are cached by tool, city and units,
and only successful responses are cached.
"""

from datetime import timedelta

import pytest

import weather_chatbot.weather as weather
from tests.conftest import SAMPLE_NOW, FakeClock
from weather_chatbot.weather import (
    CACHE_TTL_SECONDS,
    MAX_CACHE_ENTRIES,
    TimedCache,
    WeatherServiceError,
    lookup_current_weather,
    lookup_weather_forecast,
)


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    """Replace the weather cache with an empty one driven by a fake clock."""
    fake_clock = FakeClock()
    monkeypatch.setattr(weather, "WEATHER_CACHE", TimedCache(clock=fake_clock))
    return fake_clock


def test_the_limits_are_ten_minutes_and_128_entries():
    assert CACHE_TTL_SECONDS == 600
    assert MAX_CACHE_ENTRIES == 128
    cache = TimedCache()
    assert cache.ttl_seconds == 600
    assert cache.max_entries == 128


# --- The cache on its own ------------------------------------------------------


def test_an_entry_is_fresh_until_just_before_600_seconds():
    clock = FakeClock()
    cache = TimedCache(clock=clock)
    cache.put("paris", "sunny")

    clock.advance(599.99)

    assert cache.get("paris") == "sunny"


def test_an_entry_expires_at_exactly_600_seconds():
    clock = FakeClock()
    cache = TimedCache(clock=clock)
    cache.put("paris", "sunny")

    clock.advance(600)

    assert cache.get("paris") is None
    assert len(cache) == 0  # the expired entry is removed, not kept around


def test_a_missing_key_gives_none():
    assert TimedCache().get("nowhere") is None


def test_going_over_128_entries_drops_the_oldest():
    clock = FakeClock()
    cache = TimedCache(clock=clock)
    for number in range(MAX_CACHE_ENTRIES):
        cache.put(f"city-{number}", number)
        clock.advance(1)
    assert len(cache) == MAX_CACHE_ENTRIES

    cache.put("one-too-many", "new")

    assert len(cache) == MAX_CACHE_ENTRIES
    assert cache.get("city-0") is None  # the oldest was dropped
    assert cache.get("city-1") == 1  # the next oldest is still there
    assert cache.get("city-127") == 127
    assert cache.get("one-too-many") == "new"


def test_storing_a_key_again_makes_it_the_newest():
    clock = FakeClock()
    cache = TimedCache(clock=clock)
    for number in range(MAX_CACHE_ENTRIES):
        cache.put(f"city-{number}", number)
    cache.put("city-0", "again")  # now the newest, so city-1 is the oldest

    cache.put("one-too-many", "new")

    assert cache.get("city-0") == "again"
    assert cache.get("city-1") is None


def test_when_full_expired_entries_are_dropped_before_fresh_ones():
    clock = FakeClock()
    cache = TimedCache(clock=clock)
    for number in range(MAX_CACHE_ENTRIES - 1):
        cache.put(f"old-{number}", number)
    clock.advance(300)
    cache.put("recent", "kept")
    clock.advance(300)  # the "old" entries are now exactly 600 s old: expired

    cache.put("one-too-many", "new")

    assert len(cache) == 2  # every expired entry went, not just the oldest one
    assert cache.get("recent") == "kept"
    assert cache.get("one-too-many") == "new"


# --- Lookups through the cache, with the fake OpenWeather ----------------------


def test_a_repeat_lookup_within_10_minutes_makes_no_api_call(fake_openweather, clock):
    first = lookup_current_weather("Paris")
    assert len(fake_openweather.requests) == 2  # geocoding + current weather

    clock.advance(CACHE_TTL_SECONDS - 0.01)
    second = lookup_current_weather("Paris")

    assert len(fake_openweather.requests) == 2  # no new call: from the cache
    assert second == first


def test_a_lookup_after_10_minutes_calls_the_api_again(fake_openweather, clock):
    lookup_current_weather("Paris")

    clock.advance(CACHE_TTL_SECONDS)
    lookup_current_weather("Paris")

    assert fake_openweather.geocoded == ["Paris", "Paris"]
    assert len(fake_openweather.weather_requests) == 2


def test_the_same_city_written_differently_shares_one_entry(fake_openweather, clock):
    lookup_current_weather("Springfield, IL, US")
    lookup_current_weather("  springfield,il,us ")

    assert len(fake_openweather.requests) == 2


def test_each_units_setting_gets_its_own_entry(fake_openweather, clock):
    fahrenheit = lookup_current_weather("Paris", units="imperial")
    celsius = lookup_current_weather("Paris", units="metric")

    assert [p["units"] for p in fake_openweather.weather_requests] == [
        "imperial",
        "metric",
    ]
    assert fahrenheit["temperature_unit"] == "°F"
    assert celsius["temperature_unit"] == "°C"

    # Both are cached now: repeating either makes no new call.
    assert lookup_current_weather("Paris", units="imperial") == fahrenheit
    assert lookup_current_weather("Paris", units="metric") == celsius
    assert len(fake_openweather.weather_requests) == 2


def test_each_tool_gets_its_own_entry_for_the_same_city(fake_openweather, clock):
    current = lookup_current_weather("Seattle")
    forecast = lookup_weather_forecast("Seattle")

    assert current["kind"] == "current_weather"
    assert forecast["kind"] == "forecast"
    assert len(fake_openweather.weather_requests) == 1
    assert len(fake_openweather.forecast_requests) == 1

    # Both are cached now, each under its own tool.
    assert lookup_current_weather("Seattle") == current
    assert lookup_weather_forecast("Seattle") == forecast
    assert len(fake_openweather.requests) == 4  # 2 geocodes + 1 of each tool


def test_a_cached_forecast_still_works_out_today_from_the_clock(
    fake_openweather, clock, monkeypatch
):
    before = lookup_weather_forecast("Seattle")
    assert before["days"][0]["label"] == "Today"
    assert before["days"][0]["date"] == "2026-11-06"

    # Nine hours later it is just past midnight in Seattle (UTC-8), and the
    # response is still cached (the cache's clock moved only one minute).
    monkeypatch.setattr(weather, "utc_now", lambda: SAMPLE_NOW + timedelta(hours=9))
    clock.advance(60)
    after = lookup_weather_forecast("Seattle")

    assert len(fake_openweather.forecast_requests) == 1  # served from the cache
    assert after["days"][0]["label"] == "Today"
    assert after["days"][0]["date"] == "2026-11-07"


# --- Failed lookups are never cached --------------------------------------------


def outage(url, params, real_fetch):
    raise WeatherServiceError("OpenWeather HTTP 503")


def malformed_response(url, params, real_fetch):
    return {"unexpected": "shape"}


def short_forecast(url, params, real_fetch):
    data = real_fetch(url, params)
    return {**data, "list": data["list"][:8]}  # covers too few local dates


@pytest.mark.parametrize(
    ("lookup", "city", "failing_url", "first_failure", "expected_error"),
    [
        pytest.param(
            lookup_current_weather,
            "Paris",
            weather.CURRENT_WEATHER_URL,
            outage,
            "service_unavailable",
            id="current-weather-outage",
        ),
        pytest.param(
            lookup_current_weather,
            "Paris",
            weather.CURRENT_WEATHER_URL,
            malformed_response,
            "service_unavailable",
            id="current-weather-malformed-response",
        ),
        pytest.param(
            lookup_weather_forecast,
            "Seattle",
            weather.FORECAST_URL,
            outage,
            "service_unavailable",
            id="forecast-outage",
        ),
        pytest.param(
            lookup_weather_forecast,
            "Seattle",
            weather.FORECAST_URL,
            short_forecast,
            "forecast_incomplete",
            id="forecast-incomplete",
        ),
    ],
)
def test_a_failed_lookup_is_not_cached(
    fake_openweather,
    clock,
    monkeypatch,
    lookup,
    city,
    failing_url,
    first_failure,
    expected_error,
):
    real_fetch = weather.fetch_json  # the sample-JSON fake
    failures_left = [1]

    def fail_once(url, params):
        if url == failing_url and failures_left:
            failures_left.pop()
            real_fetch(url, params)  # still recorded as a request
            return first_failure(url, params, real_fetch)
        return real_fetch(url, params)

    monkeypatch.setattr(weather, "fetch_json", fail_once)

    failed = lookup(city)
    assert failed["kind"] == "error"
    assert failed["error"] == expected_error

    # The next question goes back to OpenWeather and succeeds...
    retried = lookup(city)
    assert retried["kind"] != "error"
    assert fake_openweather.geocoded == [city, city]

    # ...and only that success is cached.
    assert lookup(city) == retried
    assert fake_openweather.geocoded == [city, city]


def test_city_not_found_is_not_cached(fake_openweather, clock):
    lookup_current_weather("Xyzzyville")
    lookup_current_weather("Xyzzyville")

    assert fake_openweather.geocoded == ["Xyzzyville", "Xyzzyville"]
    assert len(weather.WEATHER_CACHE) == 0


def test_an_invalid_city_never_reaches_the_cache_or_the_network(
    fake_openweather, clock
):
    result = lookup_current_weather("Paris; DROP TABLE")

    assert result["error"] == "invalid_city"
    assert fake_openweather.requests == []
    assert len(weather.WEATHER_CACHE) == 0


def test_the_cache_never_holds_the_api_key(fake_openweather, clock):
    lookup_current_weather("Paris")
    lookup_weather_forecast("Seattle")

    stored = str(weather.WEATHER_CACHE._entries)
    assert fake_openweather.api_key not in stored
