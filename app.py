"""UI module: the Streamlit chat page.

Run with:  uv run streamlit run app.py
"""

import logging

import streamlit as st

from weather_chatbot.agent import ask, create_model
from weather_chatbot.config import check_keys, load_env, setup_message

# Shown when the xAI call fails. Phase 7 replaces this with full error mapping
# and redacted logging.
UNAVAILABLE_MESSAGE = (
    "Sorry, the weather assistant is unavailable right now. Please try again "
    "shortly. If this keeps happening, check that `XAI_API_KEY` in `.env` is "
    "correct."
)

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Weather Chatbot", page_icon="🌦️")
st.title("🌦️ Weather Chatbot")
st.caption("Ask about the current weather or forecast for a city.")

# Startup key check: stop before any model is created or API call is made.
problems = check_keys(load_env())
if problems:
    st.error(setup_message(problems))
    st.stop()


@st.cache_resource
def get_model():
    """Create the Grok model once and reuse it across reruns."""
    return create_model()


if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about the weather in a city…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        # No streaming: the reply appears only once it is complete.
        with st.spinner("Checking the weather…"):
            try:
                reply = ask(get_model(), prompt)
            except Exception as exc:  # noqa: BLE001 - user sees a safe message
                # Log only the error type: messages can carry request details.
                logger.warning("xAI call failed: %s", type(exc).__name__)
                reply = UNAVAILABLE_MESSAGE
        st.markdown(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})
