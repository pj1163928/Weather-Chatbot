# Weather Chatbot

A locally run Streamlit chat app that answers weather questions using xAI's
Grok (`grok-4.7`) through LangChain. It is a course project where security is
graded. It is being built in 8 phases. So far the app checks both keys,
answers current-weather and 5-day forecast questions through the
`get_current_weather` and `get_weather_forecast` tools and a capped
tool-calling loop, and shows a weather card or a forecast table in the chat.
A sidebar °F/°C toggle sets the units, the last 2 exchanges are sent as
memory for follow-ups, and lookups are cached for 10 minutes. A free gate
runs before any Grok call: 20 messages per session, a 3-second cooldown, a
300-character cap and attack-phrase matching, with each block written as one
redacted line to `logs/security.log`. Then a temperature-0 grok-4.7
classifier must return a clear YES (it fails closed) before the agent runs
with a hardened system prompt. The output scan and safe error handling are
still planned. The plan's ticked criteria show what is done.

The developer is a beginner, so code should favor clarity.

## Where things are

- [app.py](app.py) is the Streamlit UI. [weather_chatbot/](weather_chatbot/) holds the other modules. [tests/](tests/) holds the pytest suite and its sample OpenWeather JSON.
- [docs/](docs/): what is built, one topic per file: [ARCHITECTURE.md](docs/ARCHITECTURE.md) (modules, request flow), [SECURITY.md](docs/SECURITY.md) (controls and rules), [TESTING.md](docs/TESTING.md) (test files, fakes). "Read before…" says when to open each.
- [prd/weather-chatbot.md](prd/weather-chatbot.md): the requirements. Its wording is authoritative.
- [plans/weather-chatbot.md](plans/weather-chatbot.md): the phased plan, its cross-phase architectural decisions and the acceptance criteria.
- [PROMPTS.md](PROMPTS.md): a log of each build session, newest first.
- [README.md](README.md): setup and run steps for people.

## Conventions

- Always create the model as `ChatXAI(model="grok-4.7")`. The grading rubric requires it. Use no other model class or name.
- Give each module one job (UI, agent, weather tools, security, config, as the plan sets out).
- Make security limits visible, named module-level constants.
- Give every public function a docstring and type hints.
- Never put a key value in code, prompts, logs, user messages or test output. See [docs/SECURITY.md](docs/SECURITY.md).
- User text goes only in a user message, never in a system prompt.
- Tests need no API keys and make no network calls.
- Pin dependencies to exact versions (`==`) in `pyproject.toml`. `uv.lock` pins the rest.
- Stay inside the current phase. Stand-ins that a later phase replaces get a comment naming that phase (for example, "Phase 7 replaces this").
- Before finishing any change, `uv run pytest`, `uv run ruff check .` and `uv run ruff format .` must all be clean.

## Read before…

- **changing keys, config, logging, error messages, tools or loop limits, or anything that handles user text, model output or OpenWeather data:** [docs/SECURITY.md](docs/SECURITY.md)
- **adding a module, changing the request flow or the Streamlit page:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **writing or changing tests:** [docs/TESTING.md](docs/TESTING.md)
- **starting a phase:** the phase in the plan and the PRD sections behind its user stories (the `/implement` skill does this)

## Keeping the docs organized

- `docs/` describes what is built. Planned work lives in `prd/` and `plans/`. Link to it rather than copying it.
- When a phase changes an area, update that area's topic file. List new modules and public functions in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and new test files in [docs/TESTING.md](docs/TESTING.md).
- Give each fact one home and link to it from elsewhere. Add a topic file only when a subject outgrows its current file, and add it to "Read before…".
- `PROMPTS.md` only ever gets new entries at the top. Never edit an older entry.
