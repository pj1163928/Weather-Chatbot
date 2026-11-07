# Prompts log

A record of each Claude Code build session: the prompts given, what was built
and the decisions made along the way. Newest entries first.

---

## 2026-11-06 — Weather chatbot: Phase 1/8, Secure skeleton + "hello Grok"

### Prompts

1. The `/implement` skill, given `weather-chatbot phase 1 - All API keys have been stored in the .env folder`.
2. "One small addition: make sure the fake-model test also verifies that ask() returns the model's reply text correctly. Otherwise, I have no requested changes. Proceed with setup and write the failing check_keys(env) test for review before implementing it."
3. "Looks good go ahead and move forward" (approved the failing test).
4. "This looks good go ahead and proceed with the rest of phase 1" (approved the green implementation).

### Summary

- **Outcome:** A Streamlit chat page backed by `ChatXAI(model="grok-4.7")` with a minimal weather-assistant system prompt and a startup key check. 20 tests pass; `ruff check` and `ruff format` are clean. A live call to grok-4.7 replied in role and declined a coding request.
- **Changes:**
  - `pyproject.toml`, `uv.lock`, `.python-version` — uv project on Python 3.13 with exact dependency pins (langchain-core, langchain-xai, python-dotenv, streamlit; dev: pytest, ruff) plus pytest and ruff settings.
  - `weather_chatbot/config.py` — `check_keys`, `load_env` (`.env` overrides shell variables) and `setup_message`; `REQUIRED_KEYS` holds only `XAI_API_KEY` this phase.
  - `weather_chatbot/agent.py` — `MODEL_NAME`, minimal `SYSTEM_PROMPT`, `create_model()`, `build_messages()` and `ask()`.
  - `app.py` — chat page: key check, then `st.stop()` with a setup message; otherwise chat input, "Checking the weather…" spinner and the complete reply (no streaming).
  - `tests/test_config.py` — the TDD key-check test (11 cases).
  - `tests/test_agent.py` — fake-model tests: `ask()` returns the reply text, system prompt first in every request, user text only in the user message, model is ChatXAI grok-4.7.
  - `tests/test_app.py` — Streamlit `AppTest` runs: setup message for missing/placeholder key; chat works with an OpenWeather placeholder.
  - `tests/test_no_secrets_in_source.py` — no real `.env` key value appears in any project file (skipped without `.env`).
  - `.env.example` — placeholders changed to the PRD's exact lines.
  - `README.md` — key timing note and Run section.
  - `plans/weather-chatbot.md` — Phase 1 criteria ticked.
- **TDD:** One behavior: `check_keys(env)` refuses a missing, blank, whitespace or placeholder `XAI_API_KEY` (PRD placeholders, the old `your_…_here` wording, anything in `<…>`) and accepts a configured one, while ignoring `OPENWEATHER_API_KEY` in Phase 1. Red on 7 assertion failures against a stub, then green.
- **Decisions:** `.env.example` aligned with the PRD placeholders, and both placeholder styles are recognized. `.env` overrides shell variables (`override=True`). Only the latest message is sent (memory is Phase 4). `max_tokens` left for Phase 2. A failing xAI call shows a fixed "unavailable" message and logs only the exception type (full error mapping is Phase 7). No `CLAUDE.md` or `docs/TESTING.md` exists yet, so only the README was updated. `load_env` reads `ENV_PATH` at call time so `AppTest` can use a temporary `.env`.
- **Deviations:** The user asked that the fake-model test also confirm `ask()` returns the reply text; added as `test_ask_returns_the_model_reply_text`. The "reply after a spinner" criterion stays unticked until the user sees the spinner in a browser; the reply itself was confirmed with a live call.
- **Sideways:** The repo already existed with `.gitignore` in its first commit, so `git init` was not re-run; ignore status was confirmed with `git check-ignore`. A stray leftover line in `tests/test_app.py` was caught and removed before the first run.
