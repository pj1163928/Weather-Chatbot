# Architecture

This file covers the modules and the request flow that exist now. The target
design (all five modules and the full request pipeline) is in the plan's
[Architectural decisions](../plans/weather-chatbot.md#architectural-decisions).

## Modules

| Module | File | Job | Public names |
|---|---|---|---|
| UI | [app.py](../app.py) | Streamlit chat page: the key check, chat history, the spinner and the weather cards | `UNAVAILABLE_MESSAGE`, `UNIT_LABELS`, `ICON_URL`, `CARD_KINDS`, `weather_cards()`, `render_current_weather()`, `forecast_rows()`, `render_forecast()`, `render_card()` |
| Agent | [weather_chatbot/agent.py](../weather_chatbot/agent.py) | Talks to Grok and runs the hand-written tool-calling loop | `MODEL_NAME`, `MAX_TOOL_ROUNDS`, `MAX_REPLY_TOKENS`, `TOOLS_BY_NAME`, `REPEATED_CALL_MESSAGE`, `EMPTY_REPLY_MESSAGE`, `TOOL_LIMIT_MESSAGE`, `SYSTEM_PROMPT`, `ChatModel`, `ToolCallingModel`, `AgentResult`, `create_model()`, `build_messages()`, `call_signature()`, `run_tool_call()`, `run_agent()` |
| Weather tools | [weather_chatbot/weather.py](../weather_chatbot/weather.py) | City validation, OpenWeather geocoding, current weather and the 5-day forecast, and the two tools | `MAX_CITY_LENGTH`, `ALLOWED_CITY_PUNCTUATION`, `REQUEST_TIMEOUT_SECONDS`, `SUPPORTED_UNITS`, `DEFAULT_UNITS`, `ICON_PATTERN`, `GEOCODING_URL`, `CURRENT_WEATHER_URL`, `FORECAST_URL`, `FORECAST_DAYS`, `ENTRIES_PER_FULL_DAY`, the four `*_MESSAGE` error texts, `WeatherServiceError`, `IncompleteForecastError`, `is_valid_city()`, `fetch_json()`, `geocoding_query()`, `format_location()`, `geocode()`, `parse_current_weather()`, `group_by_local_date()`, `summarize_forecast()`, `day_label()`, `summarize_day()`, `error_result()`, `parse_forecast()`, `utc_now()`, `look_up_weather()`, `lookup_current_weather()`, `lookup_weather_forecast()`, `CityInput`, `get_current_weather`, `get_weather_forecast`, `WEATHER_TOOLS` |
| Config | [weather_chatbot/config.py](../weather_chatbot/config.py) | Loads `.env` and checks the keys | `ENV_PATH`, `REQUIRED_KEYS`, `KNOWN_PLACEHOLDERS`, `check_keys()`, `load_env()`, `setup_message()`, `openweather_key()` |

The security module does not exist yet.

## Request flow

Streamlit runs `app.py` from the top on every interaction:

1. `check_keys(load_env())` runs first. Both `XAI_API_KEY` and `OPENWEATHER_API_KEY` are required. If either fails, the page shows `setup_message()` with `st.error` and calls `st.stop()`, before any model is created.
2. `get_model()` wraps `create_model()` in `@st.cache_resource`, so one `ChatXAI(model="grok-4.7", max_tokens=500, timeout=10)` is reused across reruns.
3. Chat history lives in `st.session_state.messages`. Each entry is `{"role", "content"}`, and assistant entries also carry `"cards"`, the raw tool results to draw. Only the newest message goes to the model, because conversation memory is not built yet.
4. `run_agent(model, text, DEFAULT_UNITS)` runs the loop:
   1. It binds `WEATHER_TOOLS` (`get_current_weather` and `get_weather_forecast`) with `bind_tools` and builds `[SystemMessage(SYSTEM_PROMPT), HumanMessage(text)]`.
   2. It asks the model for its next step. A reply with no tool calls ends the loop, and that reply is returned (or `EMPTY_REPLY_MESSAGE` if it's blank).
   3. Otherwise each tool call runs through `run_tool_call()`, which always puts the app's `units` into the arguments. A call whose `call_signature()` (tool name plus exact arguments) already ran gets a `repeated_call` error instead. Every call gets a `ToolMessage` answer.
   4. After `MAX_TOOL_ROUNDS` (3) rounds the model gets one more turn. If it asks for tools again, those calls are not run and the reply is `TOOL_LIMIT_MESSAGE`.
5. Both tools share `look_up_weather()`: `is_valid_city()` first (no network call if it fails), then `geocode()` (top match) and a request by latitude and longitude. All requests go through `fetch_json()`. Each tool returns a plain dict: `kind: "current_weather"`, `kind: "forecast"`, or `kind: "error"` with `invalid_city`, `city_not_found`, `service_unavailable` or `forecast_incomplete`.
   - `get_current_weather` → `lookup_current_weather()` → `parse_current_weather()`.
   - `get_weather_forecast` → `lookup_weather_forecast()` → `parse_forecast()` → `summarize_forecast(data, now)`, which turns the 40 three-hour entries into exactly `FORECAST_DAYS` (5) days:
     1. `group_by_local_date()` shifts each entry's UTC `dt` by the response's `city.timezone` offset and groups by local date.
     2. The first five local dates on or after the city's local today (from `now`, which is `utc_now()` unless a test passes one) are kept. Earlier and later dates are dropped.
     3. Fewer than five dates raises `IncompleteForecastError`, which the lookup turns into a `forecast_incomplete` error. Days are never invented.
     4. `summarize_day()` gives each day a `label` ("Today", "Tomorrow" or the weekday), its ISO `date`, `high` (largest `temp_max`), `low` (smallest `temp_min`), `condition` (most common; a tie goes to the first in the day), `chance_of_rain` (highest `pop` as a whole percent) and `partial` (fewer than `ENTRIES_PER_FULL_DAY`, 8, entries for that local date).
6. The spinner "Checking the weather…" runs during step 4. When the loop finishes, the reply appears, followed by one card per successful lookup (`weather_cards()` keeps the `CARD_KINDS`). `render_card()` draws each from the raw result, never from the model's text: `render_current_weather()` for metric tiles, or `render_forecast()` for a 5-row `st.dataframe` table (Day, High / Low, Condition, Chance of rain) built by `forecast_rows()`, with "(partial)" after a partial day. If the xAI call raises, the user sees `UNAVAILABLE_MESSAGE` and only the exception type is logged.

## Gotchas

- `agent.py` and `app.py` take the model through the `ToolCallingModel` protocol, meaning any object with `bind_tools(tools)` returning something with `invoke(messages)`. Tests rely on this to pass in fakes.
- `create_model()` writes the literal `"grok-4.7"` instead of using `MODEL_NAME`. The two must stay equal. `test_model_is_chatxai_grok_4_7_with_reply_cap_and_timeout` checks this.
- Both tools use the same input schema, `CityInput`. `units` is a field of it marked `InjectedToolArg`, so it is left out of the schema the model sees. The loop fills it in. Phase 4 replaces `DEFAULT_UNITS` with the sidebar toggle.
- OpenWeather's state code only works for US places, and a bare 2-letter code may be read as a country. The `city` field description asks the model for `"Springfield, IL, US"` style. `geocoding_query()` removes the spaces around commas.
- **Fixed offset:** the forecast uses one UTC offset (`city.timezone`) for the whole response. If daylight saving time starts or ends during the five days, entries after the change are an hour off, which can move an entry near midnight to the next or previous day.
- "Today" is the city's date, not the computer's. Late in the city's evening the forecast may have no entries left for today, so the five days start with "Tomorrow" and may all be full.
- The forecast table uses `st.dataframe`, not `st.table`, because `st.table` renders Markdown in its cells and the cells hold OpenWeather text.
- The location on the card comes from geocoding, not the weather response. The weather response often names a district instead (for example "Palais-Royal" for Paris).
- `load_env()` reads `ENV_PATH` when it is called, not at import time, so tests can point it at a temporary `.env`. See [TESTING.md](TESTING.md).
- No logging handler or log file is configured yet. `logs/` is already gitignored for the planned security log.
