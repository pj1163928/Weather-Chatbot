# Weather Chatbot

A secure, locally run AI weather chatbot built with LangChain, xAI's Grok, OpenWeather and Streamlit.

See [prd/weather-chatbot.md](prd/weather-chatbot.md) for requirements and [plans/weather-chatbot.md](plans/weather-chatbot.md) for the build plan.

## Setup

1. Copy `.env.example` to `.env`.
2. Replace the placeholders in `.env` with your real `XAI_API_KEY` and `OPENWEATHER_API_KEY`.

`.env` is gitignored and must never be committed.

Both keys are required. The app shows a setup message instead of starting if
either is missing or still a placeholder. Sign up for OpenWeather early: new keys
can take up to 2 hours to activate. Until then OpenWeather rejects the key
(HTTP 401): the terminal shows `OpenWeather HTTP 401` and the chat says the
weather service is unavailable.

## Run

This project uses [uv](https://docs.astral.sh/uv/) and Python 3.13.

```
uv sync                          # install the pinned dependencies
uv run streamlit run app.py      # start the chat at http://localhost:8501
uv run pytest                    # run the tests (no API keys needed)
```

Blocked messages (rate limits and the pre-filter) are recorded in
`logs/security.log`, one line each, with keys redacted. The folder is
gitignored and created on the first block.
