"""Checks that no real key from .env appears in any project file.

Skipped when .env is absent, so the suite still runs without keys. Failure
messages name only the key and the file, never the value.
"""

from pathlib import Path

import pytest
from dotenv import dotenv_values

from weather_chatbot.config import ENV_PATH, check_keys

PROJECT_ROOT = ENV_PATH.parent
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "logs"}


def _project_files() -> list[Path]:
    files = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or path == ENV_PATH:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(PROJECT_ROOT).parts):
            continue
        files.append(path)
    return files


@pytest.mark.skipif(not ENV_PATH.exists(), reason="no .env file to compare against")
def test_no_real_key_value_appears_in_any_project_file():
    env = dotenv_values(ENV_PATH)
    # Only keys that are really configured (not blank or placeholders).
    real_keys = {
        name: value.strip()
        for name, value in env.items()
        if name.endswith("_API_KEY") and not check_keys(env, (name,))
    }
    if not real_keys:
        pytest.skip("no real keys configured in .env")

    offenders = []
    for path in _project_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, value in real_keys.items():
            if value in text:
                offenders.append(f"{name} in {path.relative_to(PROJECT_ROOT)}")

    assert offenders == [], f"Real key values found in: {offenders}"
