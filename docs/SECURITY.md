# Security

Security is a graded requirement. This file covers the controls that exist now
and the rules all code must follow. The planned defense layers (pre-filter,
rate limits, classifier, output scan, redacted security log) are not built
yet. They are described in the [PRD](../prd/weather-chatbot.md#implementation-decisions)
and assigned to phases in the [plan](../plans/weather-chatbot.md).

## Secrets: what exists

- **Storage:** keys live only in `.env` at the project root (`config.ENV_PATH`). `.gitignore` excludes `.env` and `.env.*` but not `.env.example`. [.env.example](../.env.example) holds the placeholder lines exactly as the PRD gives them.
- **Loading:** `load_env()` calls `load_dotenv(..., override=True)`, so values in `.env` win over shell variables with the same name.
- **Checking:** `check_keys(env)` returns the names of required keys that fail. A key fails if it is missing, blank, only whitespace, matches a `KNOWN_PLACEHOLDERS` value (case-insensitive) or is wrapped in `<angle brackets>`. Passing proves only that a key is configured. It does not prove the provider accepts the key.
- **Required keys:** `REQUIRED_KEYS` is `("XAI_API_KEY", "OPENWEATHER_API_KEY")`.
- **Startup:** if any key fails, the app shows `setup_message()` and stops before a model is created. The message names the keys but never shows their values.
- **The OpenWeather key** is read only by `openweather_key()`, and only `weather.py` calls it, to put it in the `appid` request parameter. It never appears in tool results, so the model never sees it. `test_the_api_key_never_reaches_the_model` checks this.
- **Leak test:** `tests/test_no_secrets_in_source.py` checks that no real `.env` key value appears in any project file.

## Tool and loop controls: what exists

- **City validation:** `is_valid_city()` runs before any network call, for both tools (they share `look_up_weather()`). After trimming, a city must be 1–60 characters (`MAX_CITY_LENGTH`), contain a letter, and use only letters, spaces, commas, hyphens and periods (`ALLOWED_CITY_PUNCTUATION`). A rejected city returns an `invalid_city` result and nothing is sent.
- **Tool-round cap:** `MAX_TOOL_ROUNDS = 3` rounds of tool calls per question, plus one turn to answer. A 4th request is refused without running, and the user sees `TOOL_LIMIT_MESSAGE`. At most 4 Grok calls per question.
- **Repeated-call block:** the same tool with exactly the same arguments runs at most once per question. A repeat is answered with a `repeated_call` error and is not sent to OpenWeather.
- **Reply cap:** `MAX_REPLY_TOKENS = 500` is passed to `ChatXAI` as `max_tokens`.
- **Timeouts:** `REQUEST_TIMEOUT_SECONDS = 10` for every OpenWeather request and for the `ChatXAI` client.
- **Units:** only the sidebar toggle chooses them. The loop always overwrites `units` with the app's value, so the model can't choose them (asking in chat to "use Celsius" changes nothing), and `units` is hidden from the model's tool schema. The system prompt tells the model to point unit requests to the toggle.
- **Only known tools run:** a tool name outside `TOOLS_BY_NAME`, or arguments that fail the tool's schema, become an error result.
- **Cards come from data:** weather cards and the forecast table are drawn from the raw tool result, not from the model's reply. The location and condition are shown with `st.text` (in the forecast's day tiles too; only the app's own day names and numbers go through `st.markdown`), the day icons pass the same `ICON_PATTERN` check, and the forecast table uses `st.dataframe` (not `st.table`, which renders Markdown in cells), so OpenWeather text is never parsed as Markdown.
- **Conversation memory:** `MAX_HISTORY_EXCHANGES = 2`. `trim_history()` sends only the last 2 complete exchanges, as role and text. Weather cards, tool payloads and any system or tool entry never go back to the model, which keeps cost down and keeps old OpenWeather text out of the request. Old user text goes in `HumanMessage`s and old replies in `AIMessage`s, never in the system prompt.
- **Cache:** `CACHE_TTL_SECONDS = 600` and `MAX_CACHE_ENTRIES = 128`. A repeat lookup (same tool, city and units) within 10 minutes makes no OpenWeather call, which keeps the app inside the free tier. The city is validated before the cache is checked, only successful responses are stored, and the cache never holds the API key (`test_the_cache_never_holds_the_api_key`). The size cap stops the cache from growing without limit.
- **No invented forecast days:** a response covering fewer than five local dates becomes a `forecast_incomplete` error, never padded days. The icon code must match `ICON_PATTERN` (like `10d`) before it goes into the image URL.

## Rules for all code

- Never print, log, return or embed a key value. This includes prompts, user-facing messages, tool results, exception text and test failure messages. Report key names only.
- Log a failure by its exception type or a status code, not its message, because messages can carry request details. OpenWeather URLs carry the key, so `fetch_json()` turns every `requests` error into a `WeatherServiceError` with a safe message (for example "OpenWeather HTTP 401") and drops the original with `from None`. Show the user a fixed, friendly message instead of exception text. For an example, see the `except` block in [app.py](../app.py).
- User text goes only in a `HumanMessage`. Never format it into the system prompt. `build_messages()` enforces this, and `tests/test_agent.py` checks it.
- The system prompt must contain no secrets.
- Text from OpenWeather (place names, conditions) is data. Display it as plain text.
- Tests use obviously fake keys, such as `xai-test-not-a-real-key`, set with `monkeypatch`. Never commit a real key, even in a skipped test.
