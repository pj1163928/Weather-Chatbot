# Security

Security is a graded requirement. This file covers the controls that exist now
and the rules all code must follow. The planned defense layers (pre-filter,
rate limits, classifier, tool-loop caps, output scan, redacted security log)
are not built yet. They are described in the [PRD](../prd/weather-chatbot.md#implementation-decisions)
and assigned to phases in the [plan](../plans/weather-chatbot.md).

## Secrets: what exists

- **Storage:** keys live only in `.env` at the project root (`config.ENV_PATH`). `.gitignore` excludes `.env` and `.env.*` but not `.env.example`. [.env.example](../.env.example) holds the placeholder lines exactly as the PRD gives them.
- **Loading:** `load_env()` calls `load_dotenv(..., override=True)`, so values in `.env` win over shell variables with the same name.
- **Checking:** `check_keys(env)` returns the names of required keys that fail. A key fails if it is missing, blank, only whitespace, matches a `KNOWN_PLACEHOLDERS` value (case-insensitive) or is wrapped in `<angle brackets>`. Passing proves only that a key is configured. It does not prove the provider accepts the key.
- **Required keys:** `REQUIRED_KEYS` is `("XAI_API_KEY",)`. `OPENWEATHER_API_KEY` is not checked yet.
- **Startup:** if any key fails, the app shows `setup_message()` and stops before a model is created. The message names the keys but never shows their values.
- **Leak test:** `tests/test_no_secrets_in_source.py` checks that no real `.env` key value appears in any project file.

## Rules for all code

- Never print, log, return or embed a key value. This includes prompts, user-facing messages, exception text and test failure messages. Report key names only.
- Log a failure by its exception type, not its message, because messages can carry request details. Show the user a fixed, friendly message instead of exception text. For an example, see the `except` block in [app.py](../app.py).
- User text goes only in a `HumanMessage`. Never format it into the system prompt. `build_messages()` enforces this today, and `tests/test_agent.py` checks it.
- The system prompt must contain no secrets.
- Tests use obviously fake keys, such as `xai-test-not-a-real-key`, set with `monkeypatch`. Never commit a real key, even in a skipped test.
