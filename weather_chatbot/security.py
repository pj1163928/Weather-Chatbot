"""Security module: the free gate (rate limits and pre-filter) and the security log.

The free gate runs before any Grok call, so a blocked message costs nothing.
Its limits are the visible constants below.
"""

import json
import logging
import os
import re
import threading
import time
import unicodedata
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from weather_chatbot.config import secret_values

# --- Security limits --------------------------------------------------------

# Messages one chat session may send. Message 21 is blocked.
MAX_MESSAGES_PER_SESSION: int = 20

# Seconds that must pass between messages. A message at 2.99 s is blocked; one
# at exactly 3.00 s is allowed.
COOLDOWN_SECONDS: float = 3.0

# Longest message allowed, in characters, after trimming spaces at the start
# and end. 300 characters pass; 301 are blocked.
MAX_INPUT_CHARS: int = 300

# Up to three words in between, as in "ignore ALL YOUR PREVIOUS rules".
_A_FEW_WORDS = r"(?:\W+\w+){0,3}?\W+"

# Known attack phrases, checked in this order against normalized text (see
# ``normalize_for_matching``). The name is the reason written to the log.
# Each needs its whole phrase, so a single word like "system", "ignore",
# "environment" or "key" in a weather question doesn't match.
ATTACK_PATTERNS: dict[str, re.Pattern[str]] = {
    # "ignore previous instructions", "disregard your earlier rules"
    "ignore_instructions": re.compile(
        r"\b(?:ignore|disregard|forget|override)\b"
        + _A_FEW_WORDS
        + r"(?:instructions?|rules|directions|prompts?)\b"
    ),
    # "reveal your system prompt", "repeat your instructions"
    "system_prompt": re.compile(
        r"\bsystem\s*prompts?\b"
        r"|\b(?:reveal|show|print|repeat|display|output|share)\b"
        + _A_FEW_WORDS
        + r"(?:instructions|prompts?)\b"
    ),
    # "developer mode", "jailbreak", "you are now ..."
    "developer_mode": re.compile(
        r"\b(?:developer|dev|debug|god|admin)\s*mode\b"
        r"|\bjailbreak"
        r"|\byou\s+are\s+now\b"
    ),
    # ".env", "environment variables", "env vars"
    "env_file": re.compile(
        r"\.env\b|\bdotenv\b|\benv(?:ironment)?\s+var(?:iable)?s?\b"
    ),
    # "api key", "api_key", "apikey", "secret key", "access token"
    "api_key": re.compile(
        r"\bapi[\s_-]*keys?\b|\bsecret[\s_-]*keys?\b|\baccess[\s_-]*tokens?\b"
    ),
}

# --- Layer names, as written in the security log ------------------------------

LAYER_RATE_LIMIT: str = "rate_limit"
LAYER_PREFILTER: str = "prefilter"
LAYER_LOOP_LIMIT: str = "loop_limit"

# --- Fixed refusals (written in code, so refusing costs nothing) ---------------

SESSION_CAP_MESSAGE: str = (
    f"You've reached this session's limit of {MAX_MESSAGES_PER_SESSION} "
    "messages. Thanks for chatting!"
)
COOLDOWN_MESSAGE: str = (
    f"Please wait {COOLDOWN_SECONDS:g} seconds between messages, then try again."
)
TOO_LONG_MESSAGE: str = (
    f"That message is too long. Please keep questions to {MAX_INPUT_CHARS} "
    "characters or fewer."
)
# Deliberately says nothing about which rule matched.
BLOCKED_REQUEST_MESSAGE: str = (
    "Sorry, I can't help with that. I can only answer questions about the "
    "current weather or the 5-day forecast for a city."
)

# --- The security log -------------------------------------------------------

# One line per blocked event. The logs/ folder is gitignored.
LOG_PATH: Path = Path(__file__).resolve().parent.parent / "logs" / "security.log"

# The logger that writes the file. It doesn't pass lines on to the terminal.
SECURITY_LOGGER_NAME: str = "weather_chatbot.security_log"

# How much of the blocked message is logged, in characters (after redaction).
SNIPPET_LENGTH: int = 100

# What replaces a secret in the log.
REDACTED: str = "[REDACTED]"

# Strings that look like keys, redacted even if they aren't this app's keys:
# xAI-style keys, and runs of 32 or more hex digits (OpenWeather keys are 32).
# There are no word boundaries, so a key inside a longer string, such as
# "appid=<key>&units=metric", is still removed, and each pattern takes the
# whole run, so no piece of it is left behind.
KEY_LIKE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"xai-[A-Za-z0-9_-]{16,}", re.IGNORECASE),
    re.compile(r"[0-9a-f]{32,}", re.IGNORECASE),
)

# The session-state entry that holds the rate-limit counters. It is separate
# from the chat history, and only ``RateLimiter`` changes it.
RATE_LIMIT_KEY: str = "rate_limit_counters"


@dataclass(frozen=True)
class Block:
    """Why a message was blocked: the layer, a short reason and the refusal shown."""

    layer: str
    reason: str
    message: str


@dataclass(frozen=True)
class UsageCounters:
    """How many messages this session has sent, and when the last one was.

    It is frozen, so it can't be changed in place: ``RateLimiter`` replaces it
    with a new one each time it lets a message through.
    """

    messages_allowed: int = 0
    last_message_at: float | None = None


def monotonic_now() -> float:
    """The rate limiter's default clock, in seconds. Tests replace it."""
    return time.monotonic()


class RateLimiter:
    """The session cap and the cooldown, kept in the session's own state.

    ``state`` is where the counters live (``st.session_state`` in the app, a
    plain dict in tests). ``clock`` returns the current time in seconds; it
    defaults to ``monotonic_now``, and tests pass a fake clock so they never
    wait.
    """

    def __init__(
        self,
        state: MutableMapping[str, Any],
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.state = state
        self.clock = clock or monotonic_now

    @property
    def counters(self) -> UsageCounters:
        """The counters so far (all zero for a new session)."""
        return self.state.get(RATE_LIMIT_KEY, UsageCounters())

    def check(self) -> Block | None:
        """Decide whether one more message may go through. None means allowed.

        An allowed message is counted. A blocked one changes nothing.
        """
        counters = self.counters
        if counters.messages_allowed >= MAX_MESSAGES_PER_SESSION:
            return Block(LAYER_RATE_LIMIT, "session_cap", SESSION_CAP_MESSAGE)

        now = self.clock()
        last = counters.last_message_at
        if last is not None and now - last < COOLDOWN_SECONDS:
            return Block(LAYER_RATE_LIMIT, "cooldown", COOLDOWN_MESSAGE)

        self.state[RATE_LIMIT_KEY] = UsageCounters(
            messages_allowed=counters.messages_allowed + 1,
            last_message_at=now,
        )
        return None


def normalize_for_matching(text: str) -> str:
    """Prepare text for the attack patterns, so simple disguises don't hide a phrase.

    Full-width and other look-alike letters become plain ones (NFKC),
    invisible characters such as zero-width spaces are removed, every run of
    whitespace becomes one space, and the text is lower-cased.
    """
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return " ".join(text.split()).casefold()


def prefilter(text: str) -> Block | None:
    """Block over-long messages and known attack phrases. None means allowed.

    The length is counted after trimming spaces at the start and end, so the
    app sends the trimmed text on. Spaces in the middle still count.
    """
    if len(text.strip()) > MAX_INPUT_CHARS:
        return Block(LAYER_PREFILTER, "too_long", TOO_LONG_MESSAGE)

    normalized = normalize_for_matching(text)
    for reason, pattern in ATTACK_PATTERNS.items():
        if pattern.search(normalized):
            return Block(LAYER_PREFILTER, reason, BLOCKED_REQUEST_MESSAGE)
    return None


def check_free_gate(text: str, limiter: RateLimiter) -> Block | None:
    """Run the free gate on one message: rate limits first, then the pre-filter.

    Returns None if the message may go on to Grok, or the ``Block`` whose
    fixed refusal the user should see. Every block writes one line to the
    security log. A message the pre-filter blocks has already passed the rate
    limiter, so it still uses one of the session's messages.
    """
    block = limiter.check()
    if block is None:
        block = prefilter(text)
    if block is not None:
        log_block(block.layer, block.reason, text)
    return block


# --- Logging ------------------------------------------------------------------


def redact(text: str) -> str:
    """Replace secrets in ``text`` with ``[REDACTED]``.

    First the app's loaded key values, matched in any letter case and longest
    first (so one key inside another can't leave a piece behind), then any
    key-like string (see ``KEY_LIKE_PATTERNS``). A key is removed even when it
    sits inside a longer string. Phase 7 uses this for exception details too.
    """
    for secret in sorted(secret_values(), key=len, reverse=True):
        text = re.sub(re.escape(secret), REDACTED, text, flags=re.IGNORECASE)
    for pattern in KEY_LIKE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def make_snippet(text: str) -> str:
    """The first ``SNIPPET_LENGTH`` characters of a message, safe to log.

    Redaction runs on the whole message before it is cut, so a key that
    crosses the cut is still removed whole. The snippet is then quoted the
    way JSON quotes text: newlines, quotes and non-ASCII characters become
    escapes, so user text can't start a fake log line.
    """
    return json.dumps(redact(text)[:SNIPPET_LENGTH])


_logger_lock = threading.Lock()


def security_logger() -> logging.Logger:
    """The logger that writes ``LOG_PATH``, set up the first time it is needed.

    If ``LOG_PATH`` has changed since (tests point it at a temporary file),
    the old file is closed and the new one opened.
    """
    logger = logging.getLogger(SECURITY_LOGGER_NAME)
    path = os.path.abspath(LOG_PATH)
    with _logger_lock:
        if not any(
            isinstance(handler, logging.FileHandler) and handler.baseFilename == path
            for handler in logger.handlers
        ):
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(path, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
    return logger


def log_block(layer: str, reason: str, text: str) -> None:
    """Write one line to the security log for a blocked event.

    For example: ``2026-11-06 14:03:22,123 | layer=prefilter |
    reason=ignore_instructions | snippet="Ignore previous instructions"``.
    ``text`` is the user's message. Only a redacted snippet of it is written.
    """
    security_logger().warning(
        "layer=%s | reason=%s | snippet=%s", layer, reason, make_snippet(text)
    )
