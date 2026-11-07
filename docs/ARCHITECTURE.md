# Architecture

This file covers the modules and the request flow that exist now. The target
design (all five modules and the full request pipeline) is in the plan's
[Architectural decisions](../plans/weather-chatbot.md#architectural-decisions).

## Modules

| Module | File | Job | Public names |
|---|---|---|---|
| UI | [app.py](../app.py) | Streamlit chat page: the key check, chat history and the spinner | `UNAVAILABLE_MESSAGE` |
| Agent | [weather_chatbot/agent.py](../weather_chatbot/agent.py) | Talks to Grok through LangChain | `MODEL_NAME`, `SYSTEM_PROMPT`, `ChatModel`, `create_model()`, `build_messages()`, `ask()` |
| Config | [weather_chatbot/config.py](../weather_chatbot/config.py) | Loads `.env` and checks the keys | `ENV_PATH`, `REQUIRED_KEYS`, `KNOWN_PLACEHOLDERS`, `check_keys()`, `load_env()`, `setup_message()` |

The weather tools module and the security module do not exist yet.

## Request flow

Streamlit runs `app.py` from the top on every interaction:

1. `check_keys(load_env())` runs first. If it reports a problem, the page shows `setup_message()` with `st.error` and calls `st.stop()`. This happens before any model is created.
2. `get_model()` wraps `create_model()` in `@st.cache_resource`, so a single `ChatXAI` instance is reused across reruns.
3. Chat history lives in `st.session_state.messages` as `{"role", "content"}` dicts. It is only displayed. Only the newest message goes to the model, because conversation memory is not built yet.
4. `ask(model, text)` calls `build_messages()`, which returns `[SystemMessage(SYSTEM_PROMPT), HumanMessage(text)]`. It then calls `model.invoke(...)` and returns `response.text`.
5. A "Checking the weather…" spinner runs while the reply is fetched. The reply appears once it is complete, with no streaming. If the call raises an exception, the user sees `UNAVAILABLE_MESSAGE`, and a warning logs only the exception's type.

## Gotchas

- `agent.py` and `app.py` take the model through the `ChatModel` protocol, meaning any object with `invoke(messages)`. Tests rely on this to pass in fakes. Keep new model-facing code behind the same interface.
- `create_model()` writes the literal `"grok-4.7"` instead of using `MODEL_NAME`. The two must stay equal. `test_model_is_chatxai_grok_4_7` checks the model name.
- `load_env()` reads `ENV_PATH` when it is called, not at import time, so tests can point it at a temporary `.env`. See [TESTING.md](TESTING.md).
- No logging handler or log file is configured yet. `logs/` is already gitignored for the planned security log.
