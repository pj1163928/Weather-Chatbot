# Security

Security is a graded requirement. This file covers the controls that exist now
and the rules all code must follow. The free gate (rate limits and pre-filter)
and the redacted security log are built. The classifier, the hardened system
prompt, the output scan and full error redaction are not built yet. They are
described in the [PRD](../prd/weather-chatbot.md#implementation-decisions)
and assigned to phases in the [plan](../plans/weather-chatbot.md).

## Secrets: what exists

- **Storage:** keys live only in `.env` at the project root (`config.ENV_PATH`). `.gitignore` excludes `.env` and `.env.*` but not `.env.example`. [.env.example](../.env.example) holds the placeholder lines exactly as the PRD gives them.
- **Loading:** `load_env()` calls `load_dotenv(..., override=True)`, so values in `.env` win over shell variables with the same name.
- **Checking:** `check_keys(env)` returns the names of required keys that fail. A key fails if it is missing, blank, only whitespace, matches a `KNOWN_PLACEHOLDERS` value (case-insensitive) or is wrapped in `<angle brackets>`. Passing proves only that a key is configured. It does not prove the provider accepts the key.
- **Required keys:** `REQUIRED_KEYS` is `("XAI_API_KEY", "OPENWEATHER_API_KEY")`.
- **Startup:** if any key fails, the app shows `setup_message()` and stops before a model is created. The message names the keys but never shows their values.
- **The OpenWeather key** is read only by `openweather_key()`, and only `weather.py` calls it, to put it in the `appid` request parameter. It never appears in tool results, so the model never sees it. `test_the_api_key_never_reaches_the_model` checks this.
- **Leak test:** `tests/test_no_secrets_in_source.py` checks that no real `.env` key value appears in any project file.
- **Redaction's copy:** `secret_values()` gives the configured key values (blank and placeholder values left out) to `redact()` in `security.py`, and nothing else calls it.

## The free gate: what exists

`check_free_gate(text, limiter)` runs on every message before any Grok call, in this order. The first check that fails returns a `Block` (layer, reason, fixed refusal), and the message goes no further, so a blocked message costs nothing.

1. **Session cap** (`rate_limit`, reason `session_cap`): `MAX_MESSAGES_PER_SESSION = 20`. Messages 1–20 go through; message 21 and every one after it get `SESSION_CAP_MESSAGE`.
2. **Cooldown** (`rate_limit`, reason `cooldown`): `COOLDOWN_SECONDS = 3.0`, measured from the last message that got through. A message at 2.99 s gets `COOLDOWN_MESSAGE`; one at exactly 3.00 s goes through. A session's first message always does.
3. **Length cap** (`prefilter`, reason `too_long`): `MAX_INPUT_CHARS = 300`, counted after trimming spaces at the start and end; spaces in the middle count. The app sends the trimmed text on. Over the cap gets `TOO_LONG_MESSAGE`.
4. **Attack phrases** (`prefilter`, reason = the pattern's name): `ATTACK_PATTERNS` holds `ignore_instructions`, `system_prompt`, `developer_mode`, `env_file` and `api_key`. They are matched against `normalize_for_matching(text)`, which applies NFKC (full-width letters become plain), removes invisible format characters such as zero-width spaces, joins whitespace and lower-cases. Each pattern needs its whole phrase, so "storm system", "ignore the drizzle" or "Key West" pass. Every match gets the same `BLOCKED_REQUEST_MESSAGE`, which doesn't say which rule matched.

**What counts toward the limits.** `RateLimiter.check()` records a message (count +1, time now) only when it lets it through. A message the limiter blocks changes nothing, so it can't push the cooldown back. A message the pre-filter blocks has already passed the limiter, so it uses one of the 20 and restarts the cooldown.

**The counters can't be reset from the UI.** They live in their own session-state entry, `RATE_LIMIT_KEY`, holding a frozen `UsageCounters`, separate from the chat history in `messages`. Only `RateLimiter.check()` replaces it; no other module mentions the key (`test_only_the_security_module_refers_to_the_counters`). Clearing the history, rerunning or switching units leave it alone. The clock is injectable: `RateLimiter(state, clock)`, defaulting to `monotonic_now()`.

**Known limit (accepted in the PRD):** a full page refresh starts a new Streamlit session, so the counters start again. For a local app that is a speed bump, not a wall. Keyword lists can also be reworded around; the Phase 6 classifier is the next layer.

**Blocked messages stay out of Grok's memory.** The app marks a blocked message and its refusal `"blocked": True`, and `trim_history()` skips them, so a blocked attack never reaches the model as history. They stay on screen, the refusal shown in an `st.warning`.

## The security log: what exists

- **Where:** `LOG_PATH` is `logs/security.log` (gitignored, created on first write) through the `SECURITY_LOGGER_NAME` logger, which doesn't pass lines on to the terminal.
- **What:** `log_block(layer, reason, text)` writes one line per blocked event, for example `2026-11-06 14:03:22,123 | layer=prefilter | reason=ignore_instructions | snippet="Ignore previous instructions"`. Layers so far: `rate_limit`, `prefilter`, and `loop_limit` (reasons `tool_round_limit` and `repeated_tool_call`, from the agent loop).
- **Snippet:** `make_snippet()` redacts the whole message first, then keeps the first `SNIPPET_LENGTH` (100) characters, so a key that crosses the cut is still removed whole. It is then quoted as JSON with every non-ASCII character escaped, so a newline, `\r`, `U+2028` or `U+0085` in user text can't start a fake log line.
- **Redaction:** `redact()` replaces with `[REDACTED]`, in order:
  1. the loaded key values from `secret_values()`, in any letter case, longest first
  2. `KEY_LIKE_PATTERNS`: `xai-` plus 16 or more key characters, and any run of 32 or more hex digits

  No pattern uses word boundaries, so a key inside a longer string (`appid=<key>&units=metric`, or glued to other letters) is removed, and each pattern takes the whole run, so no piece is left. Tests check that no 8-character piece of either key survives. Phase 7 extends this to exception details.

## Tool and loop controls: what exists

- **City validation:** `is_valid_city()` runs before any network call, for both tools (they share `look_up_weather()`). After trimming, a city must be 1–60 characters (`MAX_CITY_LENGTH`), contain a letter, and use only letters, spaces, commas, hyphens and periods (`ALLOWED_CITY_PUNCTUATION`). A rejected city returns an `invalid_city` result and nothing is sent.
- **Tool-round cap:** `MAX_TOOL_ROUNDS = 3` rounds of tool calls per question, plus one turn to answer. A 4th request is refused without running, and the user sees `TOOL_LIMIT_MESSAGE`. At most 4 Grok calls per question.
- **Repeated-call block:** the same tool with exactly the same arguments runs at most once per question. A repeat is answered with a `repeated_call` error and is not sent to OpenWeather.
- **Reply cap:** `MAX_REPLY_TOKENS = 500` is passed to `ChatXAI` as `max_tokens`.
- **Timeouts:** `REQUEST_TIMEOUT_SECONDS = 10` for every OpenWeather request and for the `ChatXAI` client.
- **Units:** only the sidebar toggle chooses them. The loop always overwrites `units` with the app's value, so the model can't choose them (asking in chat to "use Celsius" changes nothing), and `units` is hidden from the model's tool schema. The system prompt tells the model to point unit requests to the toggle.
- **Only known tools run:** a tool name outside `TOOLS_BY_NAME`, or arguments that fail the tool's schema, become an error result.
- **Cards come from data:** weather cards and the forecast table are drawn from the raw tool result, not from the model's reply. The location and condition are shown with `st.text` (in the forecast's day tiles too; only the app's own day names and numbers go through `st.markdown`), and the day icons pass the same `ICON_PATTERN` check.
- **Plain condition text:** every condition description from OpenWeather passes `plain_condition()` before it goes into a tool result. It must start with a letter, be at most `MAX_CONDITION_LENGTH` (60) characters, and use only letters, spaces and `ALLOWED_CONDITION_PUNCTUATION` (`-`, `/`, `,`); anything else becomes `UNKNOWN_CONDITION` ("unknown"). No Markdown, link, emoji, icon or HTML syntax can be built from those characters. This matters because the forecast table is an `st.table`, which renders Markdown in its cells: the condition is the only OpenWeather text in it, and the table runs it through `plain_condition()` again. Every other cell is the app's own text. It also keeps odd text out of what the model reads.
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
