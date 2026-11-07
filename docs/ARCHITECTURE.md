# Architecture

This file covers the modules and the request flow that exist now. The target
design (all five modules and the full request pipeline) is in the plan's
[Architectural decisions](../plans/weather-chatbot.md#architectural-decisions).

## Modules

| Module | File | Job | Public names |
|---|---|---|---|
| UI | [app.py](../app.py) | Streamlit chat page: the key check, chat history, the spinner and the weather cards | `UNAVAILABLE_MESSAGE`, `UNIT_LABELS`, `ICON_URL`, `weather_cards()`, `render_current_weather()` |
| Agent | [weather_chatbot/agent.py](../weather_chatbot/agent.py) | Talks to Grok and runs the hand-written tool-calling loop | `MODEL_NAME`, `MAX_TOOL_ROUNDS`, `MAX_REPLY_TOKENS`, `TOOLS_BY_NAME`, `REPEATED_CALL_MESSAGE`, `EMPTY_REPLY_MESSAGE`, `TOOL_LIMIT_MESSAGE`, `SYSTEM_PROMPT`, `ChatModel`, `ToolCallingModel`, `AgentResult`, `create_model()`, `build_messages()`, `call_signature()`, `run_tool_call()`, `run_agent()` |
| Weather tools | [weather_chatbot/weather.py](../weather_chatbot/weather.py) | City validation, OpenWeather geocoding and current weather, and the `get_current_weather` tool | `MAX_CITY_LENGTH`, `ALLOWED_CITY_PUNCTUATION`, `REQUEST_TIMEOUT_SECONDS`, `SUPPORTED_UNITS`, `DEFAULT_UNITS`, `ICON_PATTERN`, `GEOCODING_URL`, `CURRENT_WEATHER_URL`, the three `*_MESSAGE` error texts, `WeatherServiceError`, `is_valid_city()`, `fetch_json()`, `geocoding_query()`, `format_location()`, `geocode()`, `parse_current_weather()`, `error_result()`, `lookup_current_weather()`, `CurrentWeatherInput`, `get_current_weather`, `WEATHER_TOOLS` |
| Config | [weather_chatbot/config.py](../weather_chatbot/config.py) | Loads `.env` and checks the keys | `ENV_PATH`, `REQUIRED_KEYS`, `KNOWN_PLACEHOLDERS`, `check_keys()`, `load_env()`, `setup_message()`, `openweather_key()` |

The security module does not exist yet.

## Request flow

Streamlit runs `app.py` from the top on every interaction:

1. `check_keys(load_env())` runs first. Both `XAI_API_KEY` and `OPENWEATHER_API_KEY` are required. If either fails, the page shows `setup_message()` with `st.error` and calls `st.stop()`, before any model is created.
2. `get_model()` wraps `create_model()` in `@st.cache_resource`, so one `ChatXAI(model="grok-4.7", max_tokens=500, timeout=10)` is reused across reruns.
3. Chat history lives in `st.session_state.messages`. Each entry is `{"role", "content"}`, and assistant entries also carry `"cards"`, the raw tool results to draw. Only the newest message goes to the model, because conversation memory is not built yet.
4. `run_agent(model, text, DEFAULT_UNITS)` runs the loop:
   1. It binds `WEATHER_TOOLS` with `bind_tools` and builds `[SystemMessage(SYSTEM_PROMPT), HumanMessage(text)]`.
   2. It asks the model for its next step. A reply with no tool calls ends the loop, and that reply is returned (or `EMPTY_REPLY_MESSAGE` if it's blank).
   3. Otherwise each tool call runs through `run_tool_call()`, which always puts the app's `units` into the arguments. A call whose `call_signature()` (tool name plus exact arguments) already ran gets a `repeated_call` error instead. Every call gets a `ToolMessage` answer.
   4. After `MAX_TOOL_ROUNDS` (3) rounds the model gets one more turn. If it asks for tools again, those calls are not run and the reply is `TOOL_LIMIT_MESSAGE`.
5. `get_current_weather` → `lookup_current_weather()`: `is_valid_city()` first (no network call if it fails), then `geocode()` (top match) and a current-weather request by latitude and longitude. Both requests go through `fetch_json()`. Each tool returns a plain dict: `kind: "current_weather"` with the readings, or `kind: "error"` with `invalid_city`, `city_not_found` or `service_unavailable`.
6. The spinner "Checking the weather…" runs during step 4. When the loop finishes, the reply appears, followed by one card per successful lookup (`weather_cards()` filters the results). The card is drawn by `render_current_weather()` from the raw result, never from the model's text. If the xAI call raises, the user sees `UNAVAILABLE_MESSAGE` and only the exception type is logged.

## Gotchas

- `agent.py` and `app.py` take the model through the `ToolCallingModel` protocol, meaning any object with `bind_tools(tools)` returning something with `invoke(messages)`. Tests rely on this to pass in fakes.
- `create_model()` writes the literal `"grok-4.7"` instead of using `MODEL_NAME`. The two must stay equal. `test_model_is_chatxai_grok_4_7_with_reply_cap_and_timeout` checks this.
- `units` is a field of `CurrentWeatherInput` marked `InjectedToolArg`, so it is left out of the schema the model sees. The loop fills it in. Phase 4 replaces `DEFAULT_UNITS` with the sidebar toggle.
- OpenWeather's state code only works for US places, and a bare 2-letter code may be read as a country. The `city` field description asks the model for `"Springfield, IL, US"` style. `geocoding_query()` removes the spaces around commas.
- The location on the card comes from geocoding, not the weather response. The weather response often names a district instead (for example "Palais-Royal" for Paris).
- `load_env()` reads `ENV_PATH` when it is called, not at import time, so tests can point it at a temporary `.env`. See [TESTING.md](TESTING.md).
- No logging handler or log file is configured yet. `logs/` is already gitignored for the planned security log.
