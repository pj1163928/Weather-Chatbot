# Plan: Secure AI Weather Chatbot

> Source PRD: `prd/weather-chatbot.md`

## Architectural decisions

These apply across all phases:

- **Runtime**: Runs locally only, started with Streamlit on the developer's machine. Python 3.13.
- **Model**: The model is always initialized with LangChain's `ChatXAI(model="grok-4.7")` from the `langchain-xai` package, and used for both the classifier and the main assistant. No other model class or model name is used.
- **Tool definitions**: `get_current_weather` and `get_weather_forecast` are defined with LangChain's `@tool` decorator and structured (typed) input schemas. Both are bound to the model with LangChain's tool-calling interface (`bind_tools`). Units are supplied by the app at call time and are **not** part of the schema the model sees.
- **Agent engine**: A hand-written tool-calling loop over the `bind_tools`-bound model. It isn't a prebuilt agent and doesn't use the deprecated AgentExecutor. Security limits are visible named constants: `MAX_TOOL_ROUNDS = 3`, reply `max_tokens` of about 500, 20 messages per session, a 3-second cooldown, a 300-character input cap and a 60-character city-argument cap.
- **Module boundaries** (one job each): UI, agent loop, weather tools, security, config.
- **Tools**: `get_current_weather` and `get_weather_forecast`. Each accepts a city/location name, optionally with state or country, resolves it through OpenWeather Geocoding (top match), and queries by latitude/longitude.
- **Data flow for display**: Tools return structured dicts. The agent returns the reply text plus the raw tool results. The UI renders weather cards from the raw results, never from model text.
- **Units**: Set only by the UI toggle (°F default) and passed to OpenWeather. The model never controls units.
- **Request pipeline order** (built up across phases): rate limit → pre-filter → classifier → agent loop → output scan → display. There's no streaming.
- **Secrets**: Keys live only in `.env` and are loaded with python-dotenv. `.gitignore` exists before `git init`. `.env.example` holds the placeholders. Keys are never in prompts, logs or code. Keys are required in step with the build: `XAI_API_KEY` from Phase 1, and `OPENWEATHER_API_KEY` from Phase 2, when the weather tools first need it.
- **Logging**: The standard `logging` module writes to `logs/security.log` (gitignored), one line per blocked event with timestamp, layer, reason and a 100-character message snippet. Everything written to the log is redacted first: both key values and key-like strings are removed from messages, snippets and exception details. Raw request URLs and headers are never logged, because OpenWeather requests carry the key in the URL.
- **Testing**: pytest needs no API keys. OpenWeather responses are faked from saved sample JSON. Anything time-dependent takes an injectable clock, so no test waits for real time.

---

## TDD recommendations

**What TDD means here:** for a few key behaviors, we write a test that fails *before* writing the code, then write only enough code to make it pass. The test becomes the definition of "correct," and you approve it before any code is written.

**Rules followed (from the project's TDD skill):**
- At most 3 behaviors per phase. Fewer, or none, is a perfectly valid answer.
- TDD only for logic a test can clearly describe: pure Python decisions such as "is this allowed?", "how is this grouped?" or "when does this stop?"
- No TDD for configuration, Streamlit layout and styling, prompt wording, or documentation. Those are checked by normal tests or by running the app.
- Everything else in a phase is still built and tested normally. TDD is extra rigor on the riskiest parts, not a replacement for the acceptance criteria.
- At the start of each phase, the selected behaviors are confirmed with you before any code is written.

**Summary:**

| Phase | TDD? | Behaviors | Why |
|---|---|---|---|
| 1. Secure skeleton | Light (1) | Key check rejects missing/placeholder keys | Small, pure decision that guards every later phase |
| 2. Current weather | **Yes (3)** | City validation; tool-round cap; repeated-call block | Security limits with exact boundaries, testable with a fake model |
| 3. 5-day forecast | **Yes (2)** | Local-date grouping into exactly 5 days; daily aggregates | Trickiest pure logic in the project; time-zone bugs are easy to miss by eye |
| 4. Units, follow-ups, caching | Light (1) | History trimming to last 2 exchanges | Clear input → output rule; toggle and cache are framework wiring |
| 5. Free gate | **Yes (3)** | Session cap; cooldown; pre-filter | Pure decisions with exact boundaries (20/21, 2.99/3.00 s, 300/301) |
| 6. Classifier + scope | **Yes (2)** | User text stays in its own escaped user message; unclear verdict fails closed | Security decisions in code; the model's own judgment is tested manually |
| 7. Output scan + errors | **Yes (3)** | Scanner block/allow decision; friendly error mapping; log redaction of keys in exception details | Last line of defense; false positives, misses and log leaks all matter |
| 8. Docs + verification | **No** | — | Documentation and verification runs have no new behavior to drive |

---

## Phase 1: Secure skeleton + "hello Grok"

**User stories**: 36, 43, 44, 45, 46, 47, 49 (partial)

### What to build

Set up the project so secrets are protected from the first minute. Create `.gitignore` first (covering `.env`, `logs/`, virtual environments and Python caches), then initialize git locally. Add `.env.example` with the two placeholder lines and pin the dependencies.

Config loading uses python-dotenv. In this phase **only `XAI_API_KEY` is required**: the app stops at startup with a clear, friendly message if it's missing or still set to its placeholder. `OPENWEATHER_API_KEY` may be absent or still a placeholder until Phase 2, so the first Grok chatbot runs before the weather integration exists.

Build a bare Streamlit chat page that sends the user's message to the model, initialized as `ChatXAI(model="grok-4.7")`, and shows the complete reply after a spinner (no streaming). Even this first version runs with a **minimal system prompt** that establishes the weather-assistant role and asks it to stay on weather topics. Phase 6 replaces this with the full hardened prompt and classifier.

**Pause point:** the developer creates `.env` and adds `XAI_API_KEY`. This is also the moment to sign up for OpenWeather, because new keys can take up to 2 hours to activate.

### Acceptance criteria

- [x] `.gitignore` is created before `git init`, and `git check-ignore -v .env` confirms `.env` is ignored.
- [x] `.env.example` exists with placeholder values and contains no real keys.
- [x] Starting the app with a missing or placeholder `XAI_API_KEY` shows a clear setup message instead of crashing or calling the API.
- [x] The app starts and chats normally while `OPENWEATHER_API_KEY` is still missing or a placeholder.
- [x] The model is initialized with `ChatXAI(model="grok-4.7")`.
- [x] With a working xAI key, a message typed in the chat returns a complete grok-4.7 reply after a spinner.
- [x] A minimal weather-assistant system prompt is sent with every request, and the chatbot never runs without behavioral instructions.
- [x] No key appears anywhere in source code.
- [x] pytest unit tests cover the config check (missing key, placeholder key, configured key). These tests prove only that a key is *configured and not a placeholder*. They don't, and can't, prove the provider accepts it; that's confirmed by the live chat above.

### TDD recommendation

**Use TDD for 1 behavior:**
1. **The key check refuses a missing or placeholder `XAI_API_KEY` and accepts a configured one.** It's a small yes/no decision with no outside dependencies, and every later phase relies on it to stop you from running (or hardcoding) without proper keys. The test checks configuration only, not whether xAI accepts the key.

**No TDD for:** `.gitignore`, `git init`, `.env.example` and dependency pinning (configuration, verified with `git check-ignore`), the Streamlit chat page (UI wiring, checked by running the app), and the minimal system prompt (wording, not testable logic).

---

## Phase 2: Current weather, end to end

**User stories**: 1, 2, 7, 8, 10, 12, 13, 14, 15, 16, 26, 27, 28, 29, 39, 50 (partial)

### What to build

Add the first real tool path. `get_current_weather` is defined with LangChain's `@tool` decorator and a structured input schema (a single city/location field), and it's bound to the model with `bind_tools`. The user asks "What's the weather in Chicago?", and Grok calls `get_current_weather`.

The key check now also requires `OPENWEATHER_API_KEY`: a missing or placeholder value shows the setup message. The key is sent to OpenWeather as a request parameter and never appears in prompts, replies or tool results.

The tool validates the city argument in Python first (letters, spaces, commas, hyphens and periods only, at most 60 characters). It then geocodes the name to the top match and fetches current weather by coordinates. It returns structured data: temperature, feels-like, humidity, wind speed, condition description, icon and resolved location name.

The hand-written loop runs tool rounds up to `MAX_TOOL_ROUNDS = 3`, rejects repeated identical tool calls, and caps the reply at about 500 tokens. The UI shows the reply and a metric-tile card (with condition and icon) inside the chat message, and the card persists in the history.

All external calls time out after 10 seconds. Unknown cities produce a clean "city not found" result.

**Pause point:** the developer adds `OPENWEATHER_API_KEY` to `.env`.

### Acceptance criteria

- [x] `get_current_weather` is a LangChain `@tool` with a structured input schema, bound with `bind_tools`, and units aren't in its model-visible schema.
- [x] A missing or placeholder `OPENWEATHER_API_KEY` now shows the setup message, and the config-check tests are extended to cover it.
- [x] Asking for current weather in a named city triggers the tool, and the reply uses real OpenWeather data.
- [x] The card shows temperature, feels-like, humidity, wind, condition and icon, plus the resolved location (for example, "Paris, Île-de-France, FR").
- [x] "Springfield, IL"-style input is accepted and resolves correctly.
- [x] A nonsense or misspelled city produces a polite "city not found" message.
- [x] Invalid city arguments (bad characters, over 60 characters) are rejected before any network call.
- [x] The loop stops after 3 tool rounds and blocks a repeated identical tool call.
- [x] Cards from earlier messages still render after new messages are sent.
- [x] pytest covers city validation (valid, invalid characters, the 60/61-character boundary) and the current-weather parsing from sample JSON.

### TDD recommendation

**Use TDD for 3 behaviors:**
1. **City validation accepts real place names and rejects anything else before any network call.** It's a pure function with an exact boundary (60 vs. 61 characters) and a clear allowed-character rule, and it's the defense against injected tool arguments.
2. **The tool loop stops after 3 rounds.** With a fake model that keeps requesting tools, a test can prove the loop ends and returns a safe message. This is the core defense against credit-draining loops.
3. **A repeated identical tool call is blocked.** A fake model that asks for `get_current_weather("Paris")` twice makes the expected result unambiguous, and the rule is easy to get subtly wrong (same tool with a different city must still be allowed).

**No TDD for:** current-weather JSON parsing (straightforward field mapping, covered by a normal test against sample JSON), the geocoding HTTP call and timeouts (thin wrappers around the network), and the metric-tile card (UI, checked by running the app).

---

## Phase 3: 5-day forecast

**User stories**: 3, 4, 5, 9, 50 (partial), 52

### What to build

Add `get_weather_forecast`, defined with `@tool` and a structured input schema like Phase 2's tool, bound alongside it with `bind_tools`, and using the same validation and geocoding path. It fetches the 5-day / 3-hour forecast and groups the 40 entries by day in the city's local time zone. Each day gets a high, a low, the most common condition and the maximum chance of rain.

**The result always has exactly five days.** Grouping 40 three-hour entries by local date usually produces 6 calendar dates (a partial today, 4 full days and a partial sixth day), and sometimes 5. The rule is:
- **Keep the first five local dates, starting with today.** Any later dates are dropped.
- **A day with fewer than 8 entries is marked "partial"** in the table. Its high, low and so on come only from the entries available, and the label makes that clear.
- **If the API returns fewer than five dates** (which shouldn't happen with a normal response), show a friendly error. Never pad with invented days.

The UI renders the five days as a 5-row forecast table inside the chat message. Grok can answer practical questions ("Should I bring an umbrella in Seattle tomorrow?") from this data.

### Acceptance criteria

- [x] Asking for a forecast triggers the forecast tool and shows a 5-row table (day, high/low, condition, chance of rain).
- [x] `get_weather_forecast` is a LangChain `@tool` with a structured input schema, and both tools are bound with `bind_tools`.
- [x] The forecast always contains exactly five days: first five local dates starting today, later dates dropped, and days with fewer than 8 entries labeled "partial." Tests cover a 6-date response, a 5-date response (start exactly at local midnight) and a short response that produces the friendly error.
- [x] Days are grouped by the city's local date, not UTC. This is verified with a sample city whose UTC offset shifts entries across midnight.
- [x] Practical-advice questions are answered from the forecast data.
- [x] A single question can use both tools when needed, within the 3-round limit.
- [x] pytest covers per-day grouping, high/low, most-common condition, max chance of rain, time-zone boundary handling and partial first/last days.

### TDD recommendation

**Use TDD for 2 behaviors:**
1. **Forecast entries are grouped by the city's local date, not UTC, into exactly five days.** This is the easiest bug in the project to miss by eye. For a city like Tokyo or Los Angeles, entries near midnight land on the wrong day, or a sixth partial day sneaks in, and the table still "looks fine." Tests with a sample time-zone offset pin down both the grouping and the five-day rule.
2. **Each day's summary is correct: high, low, most common condition and highest chance of rain, with partial days labeled.** The expected values can be worked out by hand from a small sample, so the test describes exactly what "summarize" means in the requirements.

**No TDD for:** the forecast HTTP call (reuses Phase 2's tested validation and geocoding path), the forecast table (UI), and practical-advice answers (the model's wording, checked manually).

---

## Phase 4: Units toggle, follow-ups, caching

**User stories**: 6, 11, 33

### What to build

Add a sidebar °F/°C toggle (default °F). The UI passes the setting to the tools, and both cards and replies use the matching unit labels. The model can't set units.

Add conversation memory: the last 2 exchanges, text only (no raw tool payloads), so follow-ups like "What about tomorrow?" and "And in Boston?" work.

Cache tool results by city and units for 10 minutes. The cache is a small time-limited cache that uses the same injectable clock as the rate limiter, so a test can "jump ahead" 10 minutes without waiting.

### Acceptance criteria

- [x] Switching the toggle changes units in new lookups, and labels match (°F/mph or °C/m/s).
- [x] Asking the model to "use Celsius" doesn't change the units; only the toggle does.
- [x] "What about tomorrow?" after a Chicago question answers for Chicago.
- [x] Only the last 2 exchanges are sent as history.
- [x] A repeated lookup within 10 minutes doesn't call OpenWeather again, and a units change creates a separate cache entry.
- [x] pytest covers the history-trimming logic.
- [x] A normal automated test (not TDD) uses a fake OpenWeather client and a controllable clock to confirm that a repeated request within 10 minutes uses the cache (no second API call), that changing units creates a separate cache entry, and that an entry expires after 10 minutes.

### TDD recommendation

**Use TDD for 1 behavior:**
1. **History trimming keeps only the last 2 exchanges, as text only, with no raw tool payloads.** It's a clear input → output rule that controls both cost and the follow-up feature. Off-by-one mistakes (keeping 1 or 3 exchanges) are easy to make and easy to test.

**No TDD for:** the °F/°C toggle (Streamlit widget wiring, checked by running the app and by confirming that "use Celsius" in chat does nothing) and the 10-minute cache (simple storage, covered by the normal automated cache test above).

---

## Phase 5: Free gate (rate limits, pre-filter, security log)

**User stories**: 20, 21, 30, 31, 32, 40, 41, 42, 50 (partial)

### What to build

Add the zero-cost front of the pipeline, which runs before any Grok call:

- Rate limiter: 20 messages per session and a 3-second cooldown.
- Pre-filter: a 300-character input cap and attack-pattern matching (for example, "ignore previous instructions", "system prompt", "developer mode", ".env", "api key").

Each block returns a fixed refusal written in code and writes one line to `logs/security.log` with timestamp, layer, reason and a 100-character snippet. **Snippets are redacted before logging**: the two key values and any key-like strings are replaced with a placeholder like `[REDACTED]`. Phase 7 extends the same redaction to exception details.

The rate-limit counters (message count and last-message time) live in their own session-state entries, separate from chat history, and only the limiter changes them. They're checked and updated **before** any API call. No UI action, such as clearing or re-rendering the chat, resets them. One limitation, already accepted in the PRD: a full page refresh starts a new Streamlit session, and therefore new counters. That's a speed bump for a local app, not a wall.

The rate limiter takes an **injectable clock** (a time source passed in), so tests control time directly instead of sleeping.

### Acceptance criteria

- [x] Blocked messages never consume a Grok call, neither the classifier (once it exists) nor the main agent. This is verified by a test with a fake model client that records every call and shows zero calls for each blocked case.
- [x] The limits can't be bypassed through session state. Tests confirm that clearing chat history leaves the counters intact, that blocked attempts are still counted correctly, and that the counters are only modified through the limiter.
- [x] **20-message limit:** tests confirm messages 1–20 are allowed and message 21 is blocked.
- [x] **3-second cooldown:** tests with a controllable clock confirm a message at 2.99 s is blocked and one at exactly 3.00 s is allowed (and the first message of a session is always allowed). No test uses real sleeping.
- [x] **300-character limit:** tests confirm 300 characters pass and 301 are blocked, including a whitespace-padding case.
- [x] Tests confirm each attack pattern from the brief is blocked case-insensitively, and that ordinary weather questions aren't falsely blocked, including ones that use attack-adjacent words in a weather sense (for example, "Is a storm system heading to Miami?").
- [x] Each block writes exactly one log line with the correct layer name.
- [x] A test sends blocked input that deliberately contains both real key values (test fakes) and key-like strings, then confirms the log shows `[REDACTED]` and none of the keys.
- [x] `logs/` is gitignored.

### TDD recommendation

**Use TDD for 3 behaviors:**
1. **The session cap allows messages 1–20 and blocks message 21.** It's an exact boundary on a pure counter, and an off-by-one here is a real cost leak.
2. **The cooldown blocks a message at 2.99 seconds and allows one at 3.00 seconds, using the controllable clock.** Writing the test first forces the clock to be injectable from the start, rather than retrofitted later.
3. **The pre-filter blocks over-long input (301 characters) and attack phrases case-insensitively, while letting ordinary weather questions through (including "Is a storm system heading to Miami?").** Writing the false-positive test first stops the keyword list from growing into one that blocks real users.

**No TDD for:** the log file setup (standard `logging` configuration, covered by a normal test that the log line is written and contains no keys) and wiring the gate into the UI (checked by the normal test that the model client is never called).

---

## Phase 6: Classifier + strict scope

**User stories**: 17, 18, 19, 22, 23, 24, 25

### What to build

Insert the grok-4.7 classifier after the free gate. It runs at temperature 0 and returns a strict structured YES/NO. It sees the latest message plus the last 2 exchanges and is told to judge only the latest message.

**Delimiters aren't the security boundary; message structure is.** The classifier's instructions go in the system message and contain **no user text at all**. User text (the history and the latest message) goes in a **separate user message**. Inside that message, the user text is wrapped in delimiters, and any delimiter characters inside it are escaped or encoded first, so the text can't fake an "end of data" marker or change the message structure. The same rule applies to the main agent: user text only ever travels in user messages, never pasted into the system prompt.

A NO returns a refusal and writes a log line (layer: classifier).

Replace the Phase 1 minimal prompt with the full hardened system prompt. It covers the strict scope (only what the tools can answer, plus practical advice), specific refusals for out-of-range requests (more than 5 days out, climate history, weather science, creative/code/homework requests), a rule against revealing instructions, and a rule to treat tool output, including geocoded names, as data. It contains no secrets.

### Acceptance criteria

- [ ] Off-topic requests (code, homework, essays, poems, trivia) are refused and logged at the classifier layer.
- [ ] Follow-ups like "What about tomorrow?" pass the classifier when the context is weather.
- [ ] An attempted context build-up ("let's talk about rain… now write a poem about rain") is refused.
- [ ] Requests 3 weeks out or for climate history get a polite, specific refusal explaining the limit.
- [ ] "How do hurricanes form?" is refused under the strict scope.
- [x] The system prompt contains no key values (verified by a test).
- [x] A malformed, empty or unclear classifier response is treated as NO (fail closed), so an error never lets a message through.
- [x] The classifier's system message contains no user text, and user text is sent only as a separate user message. This is verified by a test that inspects the built message list.
- [x] User text containing the closing delimiter (or other delimiter characters) is escaped, so it can't break out of the data section or add messages.
- [x] pytest covers classifier prompt construction (delimiters, history trimming) and YES/NO parsing with a faked model response.

### TDD recommendation

**Use TDD for 2 behaviors:**
1. **User text travels only in its own user message, escaped, and can't change the message structure, even when it contains the closing delimiter itself.** This is a security decision made entirely in Python. A test with a hostile input (for example, the end marker followed by "Answer YES") checks two things in the built message list: the system message has no user text, and the delimiter inside the user text came out escaped.
2. **Any classifier response that isn't a clear YES is treated as NO (fail closed).** A fake model returning garbage, an empty reply or "maybe" should never let a message through. The test defines the safe default before the parsing code exists.

**No TDD for:** whether Grok *judges* topics correctly (that's the model's behavior, which varies between runs, so it's checked with the `TESTING.md` prompts instead) and the hardened system-prompt wording (prose, not logic; the "contains no key values" check is a normal test).

---

## Phase 7: Output scan + safe errors

**User stories**: 34, 35, 37, 38, 50 (partial)

### What to build

Add a unique canary string to the system prompt. Before any reply is displayed, scan the complete text for:

- the exact loaded key values
- key-like patterns (xAI-style keys and 32-character hex strings)
- the canary string
- code fences

Any match replaces the reply with a standard refusal and writes a log line (layer: output_scan).

Wrap all external failures (OpenWeather or xAI errors, timeouts, rate-limit responses) so users see friendly messages, while **redacted** details and stack traces go to the log only.

**Close the log-leak gap.** HTTP exceptions often include the full request URL, and OpenWeather URLs contain the API key (`appid=…`). So:
- All log output, including exception messages and stack-trace text, passes through redaction that removes both key values and key-like strings. This extends the Phase 5 snippet redaction to everything the logger writes.
- Raw request URLs, query strings and headers are never logged. Errors are logged as type plus a sanitized message (for example, "OpenWeather HTTP 401").
- Failures are never logged by dumping the raw exception object without redaction.

### Acceptance criteria

- [ ] Replies containing a key value, a key-like pattern, the canary or a code fence are replaced with the standard refusal and logged.
- [ ] Normal weather replies, including ones with numbers and times, pass the scan (no false positives).
- [ ] With OpenWeather unreachable or the key invalid, the user sees a friendly message and no stack trace.
- [ ] With the xAI call failing, the user sees a friendly message and no stack trace.
- [ ] pytest covers each scanner trigger, a set of clean weather replies, and error-to-friendly-message mapping.
- [ ] Tests deliberately raise exceptions whose messages contain each API key, including an OpenWeather-style URL with `appid=<key>`, log them through the normal error path, and confirm the log file contains `[REDACTED]` and neither key.
- [ ] No log line contains a raw request URL, query string or header.

### TDD recommendation

**Use TDD for 3 behaviors:**
1. **The output scanner blocks replies containing a key value, a key-like pattern, the canary or a code fence, and allows normal weather replies.** It's the last line of defense, so both mistakes matter: a miss leaks secrets, while a false positive (for example, a long number in a forecast flagged as a key) breaks real answers. Tests for both sides pin the behavior down.
2. **Failures become friendly messages with no internal details.** A test can raise a fake timeout, a 401 or an xAI error and check that the user-facing text is friendly and contains no stack trace, URL or key.

3. **Secret redaction removes both keys from everything the logger writes, including exception messages and URLs.** A test that raises an exception containing `appid=<OpenWeather key>` and the xAI key, logs it through the normal error path, and searches the log file is a precise, pass/fail definition of "keys never reach the logs." It's the most security-critical rule in this phase.

**No TDD for:** adding the canary to the system prompt (a one-line wording change) and the logging configuration itself (standard `logging` setup, covered by the redaction tests).

---

## Phase 8: Docs + full verification

**User stories**: 47, 48, 49, 51, 53, 54, 55, 56

### What to build

This phase produces the **complete submission package**: README, testing checklist, verification, video demo and GitHub repository.

Write the README:

- setup steps
- exactly when and where to add each key
- the OpenWeather activation delay
- how to run the app and tests
- **Architecture overview**: how LangChain, `ChatXAI(model="grok-4.7")`, the two `@tool` weather functions, `bind_tools` and the hand-written tool-calling loop fit together. It follows one question from the chat box through the security gate, the classifier, the tool calls and the output scan, to the weather card.
- **Security reflection**: an explicit explanation of the code-side security controls, covering at least prompt-injection defense (pre-filter, classifier with separate user message and escaping, hardened system prompt, canary and output scan) and API-hijacking prevention (strict scope, tool-round cap, repeated-call block, `max_tokens`, session cap, cooldown). It also covers secret handling (`.env`, `.gitignore`, startup check, log redaction) and the known limitations (keyword lists can be reworded around; a page refresh resets session limits).
- the GitHub repository link, once pushed

Write `TESTING.md` with about 15 manual prompts (normal questions, follow-ups, the brief's attacks, homework and essay requests, an unknown city), each with an expected result and a pass/fail column.

Then do a complete verification:

1. Run the **entire pytest suite** as a regression run, not just the newest tests.
2. Do a **clean-setup run**: start from a fresh virtual environment and a `.env` copied from `.env.example`, install from the pinned requirements, confirm the placeholder-key message appears, then add the real keys and confirm the app works.
3. Run the manual `TESTING.md` checklist and record pass/fail.
4. Do a final `git check-ignore` proof.

Then produce the submission:

5. **Video demo (recorded by the developer, 1–3 minutes).** Claude provides a short demo script listing the exact prompts in order, and the developer records the screen showing:
   1. current weather for a city
   2. the five-day forecast for a city
   3. a prompt-injection attempt being blocked
   4. an unrelated, off-topic question being refused

   The `TESTING.md` prompts help with rehearsal but don't replace the recording.
6. **GitHub submission (pushed by the developer).** Before pushing, verify that `.env` has never been committed: it's absent from `git ls-files` and from the entire history (`git log --all -- .env` shows nothing). The developer creates the GitHub repository and pushes. Afterward, confirm on GitHub that `.env` and `logs/` aren't present, and record the repository link in the README and for submission.

### Acceptance criteria

- [ ] README directions alone are enough to set up and run the app from scratch.
- [ ] The full pytest suite passes in one run, and the result is recorded.
- [ ] Clean setup works: a fresh virtual environment plus `.env` copied from `.env.example` shows the placeholder-key message, and after real keys are added the app runs and answers a weather question.
- [ ] Every `TESTING.md` prompt has a recorded pass/fail result. Any failure is fixed and re-run, or documented honestly.
- [ ] `git check-ignore -v .env` and `git check-ignore -v logs/security.log` both confirm the files are ignored, and `git status` shows no secrets staged.
- [ ] The README contains an architecture overview naming `ChatXAI(model="grok-4.7")`, the two `@tool` functions, `bind_tools` and the tool-calling loop.
- [ ] The README contains a security reflection explaining at least two code-side controls, including prompt-injection defense and API-hijacking prevention.
- [ ] A 1–3 minute screen recording exists showing current weather, a five-day forecast, a blocked prompt injection and a refused off-topic question.
- [ ] `git ls-files` and `git log --all -- .env` show `.env` was never committed.
- [ ] The code is pushed to GitHub, the repository on GitHub contains no `.env` or `logs/`, and the repository link is recorded in the README.

### TDD recommendation

**No TDD in this phase.** It's documentation (README, `TESTING.md`), verification runs (full regression, clean setup, manual checklist) and submission tasks (video, GitHub), so there's no new behavior for a failing test to drive. The full pytest run here also re-checks every TDD test written in Phases 1–7.
