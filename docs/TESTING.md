# Testing

Run the suite with `uv run pytest`. The pytest settings in `pyproject.toml`
set `testpaths = ["tests"]` and `pythonpath = ["."]`. The suite needs no API
keys and makes no network calls.

## Test files

| File | Covers |
|---|---|
| [tests/conftest.py](../tests/conftest.py) | Shared fixtures: `fake_openweather` (which also fixes the clock at `SAMPLE_NOW`) and `sample_json` (see Patterns) |
| [tests/fixtures/openweather/](../tests/fixtures/openweather/) | Saved sample OpenWeather responses: geocoding for Paris, London, Springfield IL and Seattle, an empty geocoding result, current weather for Paris and London, and a made-up Seattle 5-day forecast (UTC−8, first entry 16:00 local on Nov 6, so it spans six local dates) |
| [tests/test_config.py](../tests/test_config.py) | `check_keys()` for both keys (missing, blank, whitespace, placeholders, configured), `setup_message()` wording and `openweather_key()`. The XAI case was the Phase 1 TDD behavior. |
| [tests/test_weather.py](../tests/test_weather.py) | City validation (the Phase 2 TDD behavior, with the 60/61 boundary), current-weather parsing from sample JSON, the geocode-then-coordinates lookup, "Springfield, IL, US", city not found, rejection before any network call, the model-visible tool schema, and `fetch_json()`'s timeout and safe errors |
| [tests/test_forecast.py](../tests/test_forecast.py) | The forecast (Phase 3 TDD behaviors): grouping by local date into exactly five days, with positive and negative offsets crossing UTC midnight, a start at local midnight, a sixth date dropped, a date before today dropped and partial first and last days; each day's high, low, most common condition (and tie rule), chance of rain, label and partial flag. Also: short responses raise or give `forecast_incomplete`, a missing `pop` counts as 0, the Seattle sample's five days, the lookup path, rejection before any network call, the model-visible schema and app units |
| [tests/test_agent_loop.py](../tests/test_agent_loop.py) | The loop's limits (Phase 2 TDD behaviors): it stops after 3 tool rounds without running the 4th request, and blocks a repeated identical call while a new city still runs |
| [tests/test_agent.py](../tests/test_agent.py) | `run_agent()` returns the reply and tool results, binds both tools, lets one question use both tools in one round, sends the system prompt first, keeps user text in the user message, never shows the key to the model, takes units from the app, handles unknown tools and bad arguments, and `create_model()` builds `ChatXAI` with `grok-4.7`, `max_tokens=500` and a 10-second timeout |
| [tests/test_app.py](../tests/test_app.py) | The Streamlit page run headlessly with `AppTest`: the setup message for each missing or placeholder key, a plain chat, the weather card and the forecast table in the reply and still there after another message, and the friendly message when xAI fails |
| [tests/test_no_secrets_in_source.py](../tests/test_no_secrets_in_source.py) | No real `.env` key value appears in any project file. Skipped when there is no `.env` or no real keys. |

## Patterns

- **Fake the model.** Any object with `bind_tools(tools)` that returns something with `invoke(messages)` will work (see `ToolCallingModel` in `agent.py`). Script its replies as `AIMessage`s. A reply with `tool_calls=[{"name", "args", "id", "type": "tool_call"}]` asks for a tool. Record each call to check the messages that were built, as `RecordingFakeModel` in `test_agent.py` does.
- **Fake OpenWeather.** The `fake_openweather` fixture replaces `weather.fetch_json` with `FakeOpenWeather`. It answers from the sample files and records every request. Use `.requests`, `.geocoded` (the place names sent) and `.weather_requests` to check what went out, and `.api_key` for the fake key it sets. Use `.forecast_requests` for forecast requests. Unknown places geocode to the empty sample. To add a city, add its sample file and an entry in `SAMPLE_PLACES`, plus `SAMPLE_CURRENT_WEATHER` or `SAMPLE_FORECASTS` if it needs weather. The fixture also replaces `weather.utc_now` with `SAMPLE_NOW` (15:00 on Nov 6 in Seattle), so the forecast sample's first day is always "Today".
- **Build forecasts by hand.** `test_forecast.py`'s `entry()`, `every_3_hours()` and `forecast()` helpers build OpenWeather-shaped responses for any UTC offset, so expected days can be worked out on paper. Pass `now` to `summarize_forecast()` or `lookup_weather_forecast()` instead of using the real clock.
- **Spy on the tool.** `test_agent_loop.py`'s `tool_ran_for` fixture wraps `weather.lookup_current_weather`, so a test sees every city the tool started for, even one rejected before the network.
- **The HTTP wrapper.** To test `fetch_json()` itself, monkeypatch `requests.get` with a fake that returns an object with `status_code`, `raise_for_status()` and `json()`, or raises a `requests` exception.
- **Fake keys.** Use obviously fake values set with `monkeypatch.setenv`. Constructing `ChatXAI` with a fake key makes no network call.
- **App tests.** In `test_app.py`:
  - The `use_env_file` fixture writes a temporary `.env`, monkeypatches `config.ENV_PATH` and clears `st.cache_resource` before and after each test.
  - To swap in a fake model, monkeypatch `agent.create_model`. This works because `AppTest` re-runs `app.py`, so its `from … import` lines pick up the patched attribute.
  - The `no_model_allowed` fixture fails the test if a model is created.
  - Inside a chat message, `.metric`, `.text`, `.image` and `.dataframe` list the card's elements. A dataframe's `.value` is a pandas DataFrame.
- **Parametrize with ids.** Use `pytest.param(..., id="...")` so each case's name explains the case.
- **Time.** By plan decision, anything time-dependent takes an injectable clock, and no test sleeps.
- **TDD.** At most 3 behaviors per phase, run through the `tdd` skill. The plan's [TDD recommendations](../plans/weather-chatbot.md#tdd-recommendations) list each phase's candidates.

## What tests can't prove

Tests cannot check live Grok or OpenWeather behavior: whether Grok calls the tool, how it words replies and refusals, what OpenWeather returns for a real city, or the spinner in a real browser. Those are checked by hand in a running app (`uv run streamlit run app.py`).
