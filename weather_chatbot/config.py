"""Config module: loads API keys from .env and checks they are really set.

Keys live only in the local ``.env`` file. This module never prints, logs or
returns a key value in a message.
"""

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv

# The local secrets file, at the project root. It is gitignored.
ENV_PATH: Path = Path(__file__).resolve().parent.parent / ".env"

# Keys the app refuses to start without. Phase 2 adds OPENWEATHER_API_KEY.
REQUIRED_KEYS: tuple[str, ...] = ("XAI_API_KEY",)

# Placeholder values copied from .env.example (current and earlier wording).
# Any value wrapped in <angle brackets> is also treated as a placeholder.
KNOWN_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "your_xai_api_key_here",
        "your_openweather_api_key_here",
    }
)


def _is_placeholder(value: str) -> bool:
    """True if ``value`` (already stripped) is a known or <bracketed> placeholder."""
    if value.lower() in KNOWN_PLACEHOLDERS:
        return True
    return value.startswith("<") and value.endswith(">")


def check_keys(
    env: Mapping[str, str | None], required: tuple[str, ...] = REQUIRED_KEYS
) -> list[str]:
    """Return the names of required keys that are missing, blank or placeholders.

    An empty list means every required key is configured. This proves only that
    a key is present and not a placeholder, not that the provider accepts it.
    """
    problems: list[str] = []
    for name in required:
        value = (env.get(name) or "").strip()
        if not value or _is_placeholder(value):
            problems.append(name)
    return problems


def load_env(path: Path | None = None) -> Mapping[str, str]:
    """Load ``.env`` (default ``ENV_PATH``) into the environment and return it.

    Values in ``.env`` win over any older variables of the same name already
    set in the shell, so the file is the single source of truth.
    """
    load_dotenv(path or ENV_PATH, override=True)
    return os.environ


def setup_message(problems: list[str]) -> str:
    """Build the friendly startup message for keys that aren't configured.

    It names the keys and says where to put them. It never includes a value.
    """
    names = ", ".join(f"`{name}`" for name in problems)
    return (
        f"**Setup needed:** {names} is missing or still a placeholder.\n\n"
        "1. In the project folder, copy `.env.example` to `.env` "
        "(if you haven't already).\n"
        "2. Open `.env` and replace the placeholder with your real key.\n"
        "3. Save the file and refresh this page.\n\n"
        "Never paste keys into the code. `.env` is gitignored, so it stays "
        "on your machine."
    )
