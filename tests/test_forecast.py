"""Tests for the 5-day forecast: grouping by local date and daily summaries.

No API key and no network. Most tests build small forecast responses by hand
(shaped like OpenWeather's 5-day / 3-hour JSON), so the expected values can
be worked out on paper.
"""

from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

import weather_chatbot.weather as weather
from weather_chatbot.weather import (
    FORECAST_DAYS,
    IncompleteForecastError,
    WeatherServiceError,
    get_weather_forecast,
    lookup_weather_forecast,
    parse_forecast,
    summarize_forecast,
)

# The Seattle sample's "fetch" time: 15:00 on Friday, Nov 6 in Seattle.
SEATTLE_NOW = datetime(2026, 11, 6, 23, 0, tzinfo=UTC)

# --- Helpers that build OpenWeather-shaped forecast data ----------------------


def utc(text: str) -> datetime:
    """A UTC time from "YYYY-MM-DD HH:MM"."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def entry(
    when: datetime,
    low: float = 50.0,
    high: float = 55.0,
    condition: str = "clear sky",
    pop: float = 0.0,
    humidity: int = 80,
    wind: float = 5.0,
    icon: str = "01d",
) -> dict:
    """One 3-hour forecast entry. ``when`` is in UTC, as OpenWeather sends it."""
    return {
        "dt": int(when.timestamp()),
        "main": {
            "temp": (low + high) / 2,
            "temp_min": low,
            "temp_max": high,
            "humidity": humidity,
        },
        "weather": [{"description": condition, "icon": icon}],
        "wind": {"speed": wind},
        "pop": pop,
        "dt_txt": when.strftime("%Y-%m-%d %H:%M:%S"),
    }


def every_3_hours(first: datetime, count: int) -> list[dict]:
    """``count`` plain entries, 3 hours apart, starting at ``first`` (UTC)."""
    return [entry(first + timedelta(hours=3 * i)) for i in range(count)]


def forecast(entries: list[dict], utc_offset_hours: float) -> dict:
    """A forecast response for a city ``utc_offset_hours`` from UTC."""
    return {
        "cod": "200",
        "cnt": len(entries),
        "list": entries,
        "city": {"name": "Test City", "timezone": int(utc_offset_hours * 3600)},
    }


# --- Behavior 1 (TDD): grouped by local date into exactly five days ------------


@pytest.mark.parametrize(
    ("utc_offset_hours", "first_entry", "now", "expected"),
    [
        # Seattle (UTC-8), negative offset. The first entry, 00:00 UTC Nov 7, is
        # still 16:00 on Nov 6 locally. Local dates: Nov 6 (3 entries, partial),
        # Nov 7-10 (8 each) and Nov 11 (5), a sixth date that is dropped.
        # Grouping by UTC date would wrongly give five full days, Nov 7-11.
        pytest.param(
            -8,
            utc("2026-11-07 00:00"),
            utc("2026-11-06 23:00"),
            [
                ("2026-11-06", True),
                ("2026-11-07", False),
                ("2026-11-08", False),
                ("2026-11-09", False),
                ("2026-11-10", False),
            ],
            id="six-dates-negative-offset-crossing-utc-midnight",
        ),
        # Tokyo (UTC+9), positive offset. The first entry, 15:00 UTC Nov 6, is
        # exactly local midnight on Nov 7, so the 40 entries fill five whole
        # local days. Grouping by UTC date would start with a partial Nov 6.
        pytest.param(
            9,
            utc("2026-11-06 15:00"),
            utc("2026-11-06 15:00"),
            [
                ("2026-11-07", False),
                ("2026-11-08", False),
                ("2026-11-09", False),
                ("2026-11-10", False),
                ("2026-11-11", False),
            ],
            id="five-dates-from-local-midnight-positive-offset",
        ),
        # São Paulo (UTC-3), negative offset, also starting at local midnight
        # (03:00 UTC). Entries at 00:00 UTC belong to the previous local day.
        pytest.param(
            -3,
            utc("2026-11-07 03:00"),
            utc("2026-11-07 03:00"),
            [
                ("2026-11-07", False),
                ("2026-11-08", False),
                ("2026-11-09", False),
                ("2026-11-10", False),
                ("2026-11-11", False),
            ],
            id="five-dates-from-local-midnight-negative-offset",
        ),
        # Tokyo again, but the first entry (21:00 Nov 6 local) is already in
        # the past: it's 00:30 on Nov 7 in Tokyo. Today is Nov 7, so Nov 6 is
        # dropped and the five days are Nov 7-11. Nov 11 has only 7 entries
        # (00:00-18:00 local), so it is a partial last day.
        pytest.param(
            9,
            utc("2026-11-06 12:00"),
            utc("2026-11-06 15:30"),
            [
                ("2026-11-07", False),
                ("2026-11-08", False),
                ("2026-11-09", False),
                ("2026-11-10", False),
                ("2026-11-11", True),
            ],
            id="date-before-today-dropped-and-partial-last-day",
        ),
    ],
)
def test_entries_are_grouped_by_local_date_into_exactly_five_days(
    utc_offset_hours, first_entry, now, expected
):
    data = forecast(every_3_hours(first_entry, 40), utc_offset_hours)

    days = summarize_forecast(data, now)

    assert [(day["date"], day["partial"]) for day in days] == expected


# --- Behavior 2 (TDD): each day's summary is correct ---------------------------


def test_each_day_is_summarized_from_its_own_entries():
    # Seattle (UTC-8). It is 15:00 on Friday, Nov 6 locally.
    now = utc("2026-11-06 23:00")
    today = [  # 16:00, 19:00 and 22:00 local on Nov 6: only 3 entries.
        entry(utc("2026-11-07 00:00"), 51.8, 54.1, "light rain", 0.20),
        entry(utc("2026-11-07 03:00"), 49.0, 50.5, "overcast clouds", 0.75),
        entry(utc("2026-11-07 06:00"), 47.3, 48.2, "light rain", 0.40),
    ]
    tomorrow = [  # 01:00 to 22:00 local on Nov 7: all 8 entries.
        entry(utc("2026-11-07 09:00"), 44.6, 45.1, "broken clouds", 0.10),
        entry(utc("2026-11-07 12:00"), 43.9, 44.8, "moderate rain", 0.62),
        entry(utc("2026-11-07 15:00"), 45.2, 46.0, "moderate rain", 0.30),
        entry(utc("2026-11-07 18:00"), 47.0, 49.9, "broken clouds", 0.60),
        entry(utc("2026-11-07 21:00"), 48.3, 52.7, "light rain", 0.20),
        # These three are after midnight UTC but still Nov 7 in Seattle.
        entry(utc("2026-11-08 00:00"), 47.5, 50.2, "moderate rain", 0.81),
        entry(utc("2026-11-08 03:00"), 46.1, 47.4, "broken clouds", 0.86),
        entry(utc("2026-11-08 06:00"), 45.0, 45.8, "clear sky", 0.00),
    ]
    later = every_3_hours(utc("2026-11-08 09:00"), 29)  # Nov 8 to part of Nov 11
    data = forecast(today + tomorrow + later, utc_offset_hours=-8)

    days = summarize_forecast(data, now)

    assert days[0] == {
        "date": "2026-11-06",
        "label": "Today",
        "high": 54.1,  # the largest temp_max of the day
        "low": 47.3,  # the smallest temp_min of the day
        "condition": "light rain",  # 2 of 3 entries
        "icon": "01d",
        "chance_of_rain": 75,  # the highest pop (0.75), as a whole percent
        "humidity": 80,
        "wind_speed": 5.0,
        "partial": True,  # only 3 of 8 entries
    }
    assert days[1] == {
        "date": "2026-11-07",
        "label": "Tomorrow",
        "high": 52.7,
        "low": 43.9,
        # "broken clouds" and "moderate rain" both appear 3 times. A tie goes
        # to the condition that appears first in the day.
        "condition": "broken clouds",
        "icon": "01d",
        # 0.86 comes from 03:00 UTC Nov 8, which is still Nov 7 locally.
        "chance_of_rain": 86,
        "humidity": 80,
        "wind_speed": 5.0,
        "partial": False,
    }
    # Later days are named by weekday.
    assert [day["label"] for day in days[2:]] == ["Sunday", "Monday", "Tuesday"]


def seattle_today(*entries: dict) -> dict:
    """The first day of a Seattle forecast whose "today" is the given entries.

    The entries should be on Nov 6 local time (after 23:00 UTC Nov 6 and
    before 08:00 UTC Nov 7). Plain entries fill the rest of the five days.
    """
    later = every_3_hours(utc("2026-11-07 09:00"), 32)
    data = forecast(list(entries) + later, utc_offset_hours=-8)
    return summarize_forecast(data, utc("2026-11-06 23:00"))[0]


def test_humidity_is_the_day_average_and_wind_the_day_maximum():
    today = seattle_today(
        entry(utc("2026-11-07 00:00"), humidity=70, wind=4.0),
        entry(utc("2026-11-07 03:00"), humidity=85, wind=12.6),
        entry(utc("2026-11-07 06:00"), humidity=90, wind=8.1),
    )

    assert today["humidity"] == 82  # (70 + 85 + 90) / 3 = 81.67, rounded
    assert today["wind_speed"] == 12.6  # the windiest hour


@pytest.mark.parametrize(
    ("entries", "expected_icon"),
    [
        pytest.param(
            [("light rain", "10n"), ("light rain", "10d"), ("clear sky", "01d")],
            "10d",
            id="night-icon-shown-as-daytime",
        ),
        pytest.param(
            [("clear sky", "01d"), ("light rain", "10d"), ("light rain", "10n")],
            "10d",
            id="icon-follows-the-most-common-condition",
        ),
        pytest.param(
            [("light rain", '10n"><script>'), ("light rain", "10n")],
            None,
            id="malformed-icon-code-dropped",
        ),
    ],
)
def test_the_day_icon_is_the_daytime_icon_of_the_most_common_condition(
    entries, expected_icon
):
    times = ["2026-11-07 00:00", "2026-11-07 03:00", "2026-11-07 06:00"]
    today = seattle_today(
        *(
            entry(utc(when), condition=condition, icon=icon)
            for when, (condition, icon) in zip(times, entries, strict=False)
        )
    )

    assert today["icon"] == expected_icon


# --- The five-day rule: never fewer, never invented ----------------------------


@pytest.mark.parametrize(
    "count",
    [
        pytest.param(32, id="exactly-four-dates"),
        pytest.param(1, id="one-entry"),
        pytest.param(0, id="empty-list"),
    ],
)
def test_a_short_response_raises_instead_of_inventing_days(count):
    # Tokyo, starting at local midnight: 8 entries per date.
    data = forecast(every_3_hours(utc("2026-11-06 15:00"), count), 9)

    with pytest.raises(IncompleteForecastError):
        summarize_forecast(data, utc("2026-11-06 15:00"))


def test_a_missing_chance_of_rain_counts_as_zero():
    entries = every_3_hours(utc("2026-11-06 15:00"), 40)
    for item in entries:
        del item["pop"]

    days = summarize_forecast(forecast(entries, 9), utc("2026-11-06 15:00"))

    assert [day["chance_of_rain"] for day in days] == [0] * FORECAST_DAYS


# --- The saved Seattle sample ---------------------------------------------------


def test_the_seattle_sample_becomes_five_local_days(sample_json):
    # 40 entries from 16:00 Nov 6 to 13:00 Nov 11, Seattle time (UTC-8): six
    # local dates. Today is partial (3 entries) and Nov 11 is dropped.
    days = summarize_forecast(sample_json("forecast_seattle.json"), SEATTLE_NOW)

    table = [
        (d["label"], d["date"], d["high"], d["low"], d["condition"],
         d["chance_of_rain"], d["partial"])
        for d in days
    ]  # fmt: skip
    assert table == [
        ("Today", "2026-11-06", 52.7, 46.9, "light rain", 64, True),
        ("Tomorrow", "2026-11-07", 51.8, 44.5, "moderate rain", 100, False),
        ("Sunday", "2026-11-08", 51.3, 43.5, "broken clouds", 24, False),
        ("Monday", "2026-11-09", 50.6, 40.9, "clear sky", 0, False),
        ("Tuesday", "2026-11-10", 50.0, 42.3, "few clouds", 41, False),
    ]
    # Icon (daytime version), average humidity and highest wind of each day.
    details = [(d["icon"], d["humidity"], d["wind_speed"]) for d in days]
    assert details == [
        ("10d", 88, 13.6),
        ("10d", 91, 14.9),
        ("04d", 81, 10.9),
        ("01d", 65, 7.4),
        ("02d", 84, 14.9),
    ]


def test_parse_forecast_adds_location_and_units(sample_json):
    data = sample_json("forecast_seattle.json")

    result = parse_forecast(data, "Seattle, Washington, US", "imperial", SEATTLE_NOW)

    assert result["kind"] == "forecast"
    assert result["location"] == "Seattle, Washington, US"
    assert result["units"] == "imperial"
    assert result["temperature_unit"] == "°F"
    assert result["wind_speed_unit"] == "mph"
    assert len(result["days"]) == FORECAST_DAYS


# --- The lookup path, with the sample-JSON fake --------------------------------


def test_lookup_geocodes_then_fetches_the_forecast_by_coordinates(fake_openweather):
    result = lookup_weather_forecast("Seattle")

    assert fake_openweather.geocoded == ["Seattle"]
    assert fake_openweather.forecast_requests == [
        {
            "lat": 47.6038321,
            "lon": -122.330062,
            "units": "imperial",
            "appid": fake_openweather.api_key,
        }
    ]
    assert result["location"] == "Seattle, Washington, US"
    # The fake fixes the clock at the sample's time, so Nov 6 is "Today".
    assert [day["label"] for day in result["days"]][:2] == ["Today", "Tomorrow"]


def test_unknown_city_gives_city_not_found_and_no_forecast_request(fake_openweather):
    result = lookup_weather_forecast("Xyzzyville")

    assert result["error"] == "city_not_found"
    assert fake_openweather.forecast_requests == []


@pytest.mark.parametrize(
    "city",
    [
        pytest.param("Seattle&appid=stolen", id="bad-characters"),
        pytest.param("a" * 61, id="61-characters"),
    ],
)
def test_invalid_city_is_rejected_before_any_network_call(fake_openweather, city):
    result = lookup_weather_forecast(city)

    assert result["error"] == "invalid_city"
    assert fake_openweather.requests == []


def test_a_short_api_response_gives_a_friendly_error(monkeypatch, sample_json):
    short = sample_json("forecast_seattle.json")
    short["list"] = short["list"][:20]  # only 3 local dates

    def fake_fetch(url, params):
        if url == weather.GEOCODING_URL:
            return sample_json("geocode_seattle.json")
        return short

    monkeypatch.setattr(weather, "fetch_json", fake_fetch)

    result = lookup_weather_forecast("Seattle", now=SEATTLE_NOW)

    assert result["kind"] == "error"
    assert result["error"] == "forecast_incomplete"
    assert "try again" in result["message"]
    assert "days" not in result


def test_a_service_failure_gives_a_safe_error_result(monkeypatch):
    def failing_fetch(url, params):
        raise WeatherServiceError("OpenWeather HTTP 500")

    monkeypatch.setattr(weather, "fetch_json", failing_fetch)

    result = lookup_weather_forecast("Seattle", now=SEATTLE_NOW)

    assert result["error"] == "service_unavailable"
    assert "500" not in result["message"]


def test_forecast_results_never_contain_the_api_key(fake_openweather):
    for city in ["Seattle", "Xyzzyville", "Seattle;"]:
        assert fake_openweather.api_key not in str(lookup_weather_forecast(city))


# --- The LangChain tool ---------------------------------------------------------


def test_get_weather_forecast_is_a_tool_with_only_city_visible_to_the_model():
    assert isinstance(get_weather_forecast, BaseTool)
    assert get_weather_forecast.name == "get_weather_forecast"

    schema = convert_to_openai_tool(get_weather_forecast)["function"]["parameters"]

    assert list(schema["properties"]) == ["city"]
    assert schema["required"] == ["city"]
    assert "units" not in str(schema)


def test_the_forecast_tool_passes_app_units_to_openweather(fake_openweather):
    result = get_weather_forecast.invoke({"city": "Seattle", "units": "metric"})

    assert fake_openweather.forecast_requests[0]["units"] == "metric"
    assert result["units"] == "metric"
    assert result["temperature_unit"] == "°C"
