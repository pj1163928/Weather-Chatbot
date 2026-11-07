# Testing

Run the suite with `uv run pytest`. The pytest settings in `pyproject.toml`
set `testpaths = ["tests"]` and `pythonpath = ["."]`. The suite needs no API
keys and makes no network calls.

## Test files

| File | Covers |
|---|---|
| [tests/test_config.py](../tests/test_config.py) | `check_keys()`: missing, blank, whitespace, placeholder and configured keys. This was the Phase 1 TDD behavior. |
| [tests/test_agent.py](../tests/test_agent.py) | `ask()` returns the reply text, the system prompt comes first, user text stays in the user message, and `create_model()` builds `ChatXAI` with `grok-4.7` |
| [tests/test_app.py](../tests/test_app.py) | The Streamlit page run headlessly with `AppTest`: the setup message for a missing or placeholder key, and a chat that works while `OPENWEATHER_API_KEY` is a placeholder |
| [tests/test_no_secrets_in_source.py](../tests/test_no_secrets_in_source.py) | No real `.env` key value appears in any project file. Skipped when there is no `.env` or no real keys. |

## Patterns

- **Fake the model.** Any object with `invoke(messages)` that returns an `AIMessage` will work (see `ChatModel` in `agent.py`). To check the messages that were built, record each call, as `RecordingFakeModel` in `test_agent.py` does.
- **Fake keys.** Use obviously fake values set with `monkeypatch.setenv`. Constructing `ChatXAI` with a fake key makes no network call.
- **App tests.** In `test_app.py`:
  - The `use_env_file` fixture writes a temporary `.env`, monkeypatches `config.ENV_PATH` and clears `st.cache_resource` before and after each test.
  - To swap in a fake model, monkeypatch `agent.create_model`. This works because `AppTest` re-runs `app.py`, so its `from … import` lines pick up the patched attribute.
  - The `no_model_allowed` fixture fails the test if a model is created.
- **Parametrize with ids.** Use `pytest.param(..., id="...")` so each case's name explains the case.
- **Time.** By plan decision, anything time-dependent takes an injectable clock, and no test sleeps.
- **TDD.** At most 3 behaviors per phase, run through the `tdd` skill. The plan's [TDD recommendations](../plans/weather-chatbot.md#tdd-recommendations) list each phase's candidates.

## What tests can't prove

Tests cannot check live Grok behavior: whether it stays in role, how it words refusals, or the spinner in a real browser. Those are checked by hand in a running app (`uv run streamlit run app.py`).
