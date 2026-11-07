"""Safe errors: friendly messages for the user, redacted details for the log.

The keys are obvious fakes set with ``monkeypatch``, and the log goes to a
temporary file (the autouse ``security_log`` fixture). The xAI errors are the
real ``openai`` exception classes that ``ChatXAI`` raises, built by hand, so
no network call is made.
"""

import re

import httpx2
import openai
import pytest

from tests.conftest import log_lines
from weather_chatbot.security import (
    CONTINUATION_INDENT,
    ERROR_DETAIL_LENGTH,
    LAYER_ERROR,
    REDACTED,
    UNAVAILABLE_MESSAGE,
    XAI_BUSY_MESSAGE,
    XAI_KEY_MESSAGE,
    XAI_TIMEOUT_MESSAGE,
    clean_error_text,
    friendly_error,
    log_error,
    security_logger,
)

# Obviously fake, but shaped like the real keys.
FAKE_XAI_KEY = "xai-FAKEtestKEYnotREAL0123456789abcdefABCDEF"
FAKE_OW_KEY = "0123456789abcdef0123456789abcdef"

# How xAI may echo a refused key: its start and end, with the middle masked.
# Too short to look like a key, so only leaving xAI's text out keeps it out.
MASKED_XAI_KEY = f"{FAKE_XAI_KEY[:12]}***{FAKE_XAI_KEY[-4:]}"

XAI_URL = "https://api.x.ai/v1/chat/completions"
OPENWEATHER_URL = (
    "https://api.openweathermap.org/data/2.5/weather"
    f"?lat=48.85&lon=2.35&units=metric&appid={FAKE_OW_KEY}"
)


@pytest.fixture
def fake_keys(monkeypatch):
    """Put both fake keys in the environment."""
    monkeypatch.setenv("XAI_API_KEY", FAKE_XAI_KEY)
    monkeypatch.setenv("OPENWEATHER_API_KEY", FAKE_OW_KEY)


def xai_status_error(cls: type[openai.APIStatusError], status: int, message: str):
    """An xAI HTTP error, as the openai client raises it for ``ChatXAI``."""
    request = httpx2.Request("POST", XAI_URL)
    return cls(message, response=httpx2.Response(status, request=request), body=None)


def xai_timeout() -> openai.APITimeoutError:
    """An xAI timeout, as the openai client raises it."""
    return openai.APITimeoutError(request=httpx2.Request("POST", XAI_URL))


def xai_connection_error() -> openai.APIConnectionError:
    """xAI couldn't be reached at all."""
    return openai.APIConnectionError(
        message=f"Connection error to {XAI_URL}",
        request=httpx2.Request("POST", XAI_URL),
    )


# --- Friendly messages (Phase 7 TDD behavior 2) ---------------------------------


@pytest.mark.parametrize(
    ("make_error", "expected"),
    [
        pytest.param(xai_timeout, XAI_TIMEOUT_MESSAGE, id="xai-timeout"),
        pytest.param(
            lambda: TimeoutError(f"timed out calling {XAI_URL}"),
            XAI_TIMEOUT_MESSAGE,
            id="plain-timeout",
        ),
        pytest.param(
            lambda: xai_status_error(
                openai.RateLimitError, 429, "Error code: 429 - too many requests"
            ),
            XAI_BUSY_MESSAGE,
            id="xai-429-rate-limit",
        ),
        pytest.param(
            lambda: xai_status_error(
                openai.AuthenticationError,
                401,
                f"Error code: 401 - Incorrect API key provided: {FAKE_XAI_KEY}",
            ),
            XAI_KEY_MESSAGE,
            id="xai-401-bad-key",
        ),
        pytest.param(
            lambda: xai_status_error(
                openai.PermissionDeniedError,
                403,
                f"Error code: 403 - key {FAKE_XAI_KEY} has no access",
            ),
            XAI_KEY_MESSAGE,
            id="xai-403-no-access",
        ),
        pytest.param(
            lambda: xai_status_error(
                openai.InternalServerError, 500, f"Error code: 500 from {XAI_URL}"
            ),
            UNAVAILABLE_MESSAGE,
            id="xai-500",
        ),
        pytest.param(xai_connection_error, UNAVAILABLE_MESSAGE, id="xai-unreachable"),
        pytest.param(
            lambda: RuntimeError(
                f"500 from {XAI_URL} with Authorization: Bearer {FAKE_XAI_KEY}; "
                f"then GET {OPENWEATHER_URL}"
            ),
            UNAVAILABLE_MESSAGE,
            id="unexpected-error-with-url-and-keys",
        ),
    ],
)
def test_failures_become_friendly_messages_with_no_internal_details(
    fake_keys, make_error, expected
):
    error = make_error()

    message = friendly_error(error)

    assert message == expected
    # Deterministic: the same failure always gives the same message.
    assert friendly_error(make_error()) == message
    # Nothing from the exception or its internals reaches the user.
    assert str(error) not in message
    assert type(error).__name__ not in message
    for internal in ("Traceback", "://", "api.x.ai", "appid", "Bearer"):
        assert internal not in message, f"{internal!r} reached the user"
    for key in (FAKE_XAI_KEY, FAKE_OW_KEY):
        assert key not in message


# --- Redacted error logging (Phase 7 TDD behavior 3) -----------------------------

# The first line of an error event. Every other line of the event (the stack
# trace) is indented, so it can't pass for a new event.
ERROR_LINE = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} \| layer=error "
    r'\| source=openweather \| error=RuntimeError \| detail=".*"$'
)


def pieces(secret: str, size: int = 8) -> list[str]:
    """Every run of ``size`` characters in ``secret``, to catch partial leaks."""
    return [secret[i : i + size] for i in range(len(secret) - size + 1)]


def fail_like_a_leaky_http_client() -> None:
    """Raise the worst kind of error: keys, a URL, a header and a chained cause."""
    try:
        inner_message = f"inner-failure-detail from {OPENWEATHER_URL}"
        raise ValueError(inner_message)
    except ValueError as inner:
        message = (
            f"outer-failure-detail: GET {OPENWEATHER_URL} failed. "
            f"Sent Authorization: Bearer {FAKE_XAI_KEY}. "
            f"Keys were {FAKE_XAI_KEY} and {FAKE_OW_KEY}."
        )
        raise RuntimeError(message) from inner


def test_logged_errors_never_contain_either_key(fake_keys, security_log):
    try:
        fail_like_a_leaky_http_client()
    except RuntimeError as exc:
        log_error("openweather", exc)

    lines = log_lines(security_log)
    log = "\n".join(lines)

    # One event: its first line, then an indented stack trace.
    assert lines, "nothing was logged"
    assert ERROR_LINE.match(lines[0]), lines[0]
    assert f"layer={LAYER_ERROR}" in lines[0]
    trace = lines[1:]
    assert trace, "no stack trace was logged"
    assert all(line.startswith("    ") for line in trace)

    # The keys are redacted, with no piece of either left behind.
    assert REDACTED in log
    for key in (FAKE_XAI_KEY, FAKE_OW_KEY):
        for piece in pieces(key):
            assert piece.casefold() not in log.casefold(), f"key leaked: {piece}"

    # No request URL, query string or header.
    for detail in (
        "://",
        "openweathermap",
        "appid=",
        "?lat=",
        "Authorization",
        "Bearer",
    ):
        assert detail not in log, f"{detail!r} reached the log"

    # The stack trace has file, line and source code...
    trace_text = "\n".join(trace)
    assert 'File "' in trace_text and "test_errors.py" in trace_text
    assert re.search(r"line \d+", trace_text)
    assert "fail_like_a_leaky_http_client" in trace_text
    assert "raise RuntimeError(message) from inner" in trace_text
    # ...but no exception messages, and nothing from the chained exception.
    assert "outer-failure-detail" not in trace_text
    assert "inner-failure-detail" not in log
    assert "ValueError" not in log
    assert "direct cause" not in log and "During handling" not in log


# --- More on error logging ------------------------------------------------------


@pytest.mark.parametrize(
    ("make_error", "detail"),
    [
        pytest.param(xai_timeout, "xAI timeout", id="timeout"),
        pytest.param(xai_connection_error, "xAI connection failed", id="unreachable"),
        pytest.param(
            lambda: xai_status_error(
                openai.AuthenticationError,
                401,
                f"Incorrect API key provided: {MASKED_XAI_KEY}",
            ),
            "xAI HTTP 401",
            id="401-with-a-masked-key",
        ),
        pytest.param(
            lambda: xai_status_error(openai.RateLimitError, 429, "slow down"),
            "xAI HTTP 429",
            id="429",
        ),
    ],
)
def test_xai_errors_are_logged_by_status_alone(
    fake_keys, security_log, make_error, detail
):
    error = make_error()

    log_error("xai", error)

    log = "\n".join(log_lines(security_log))
    assert f'| detail="{detail}"' in log
    # xAI's own text never reaches the log, so a masked piece of the key
    # (which redaction can't recognize) can't either.
    assert str(error) not in log
    assert FAKE_XAI_KEY[:12] not in log and FAKE_XAI_KEY[-4:] not in log


def test_a_long_error_detail_is_cut_short(fake_keys, security_log):
    log_error("xai", RuntimeError("x" * 1000))

    [first, *_] = log_lines(security_log)
    assert f'detail="{"x" * ERROR_DETAIL_LENGTH}"' in first
    assert "x" * (ERROR_DETAIL_LENGTH + 1) not in first


@pytest.mark.parametrize(
    ("text", "label"),
    [
        pytest.param("GET https://api.example.test/v1/x?y=1 failed", "[URL]", id="url"),
        pytest.param("sent ?lat=1&appid=abc", "[QUERY]", id="query-string"),
        pytest.param("Authorization: Bearer abc.def", "[HEADER]", id="auth-header"),
        pytest.param("x-api-key: abc123", "[HEADER]", id="api-key-header"),
        pytest.param("token Bearer abc.def", "[HEADER]", id="bearer-token"),
    ],
)
def test_clean_error_text_removes_request_details(text, label):
    cleaned = clean_error_text(text)

    assert label in cleaned
    for detail in ("://", "appid=", "abc"):
        assert detail not in cleaned


def test_clean_error_text_keeps_ordinary_text():
    text = "OpenWeather HTTP 503 after 10 seconds: what now?"

    assert clean_error_text(text) == text


def test_anything_written_to_the_log_file_is_redacted(fake_keys, security_log):
    # Even a careless direct call, bypassing log_block and log_error, can't
    # write a key: the file's formatter redacts every line.
    logger = security_logger()
    logger.warning("oops %s and %s", FAKE_XAI_KEY, FAKE_OW_KEY)
    try:
        raise RuntimeError(f"GET https://x.test/?appid={FAKE_OW_KEY}")
    except RuntimeError:
        logger.exception("attached exception")

    log = security_log.read_text(encoding="utf-8")
    assert FAKE_XAI_KEY not in log and FAKE_OW_KEY not in log
    assert REDACTED in log
    # Attached exception text loses its URL too, and every extra line is
    # indented, so none of it looks like a new event.
    assert "://" not in log
    lines = log.splitlines()
    assert lines[0].startswith("20") and lines[1].startswith("20")
    assert all(line.startswith(CONTINUATION_INDENT) for line in lines[2:])


def test_a_newline_in_an_error_message_cant_fake_a_log_line(fake_keys, security_log):
    fake_event = "2026-01-01 00:00:00,000 | layer=prefilter | reason=fake"
    log_error("xai", RuntimeError(f"boom\n{fake_event} {fake_event}"))

    lines = log_lines(security_log)
    events = [line for line in lines if not line.startswith(CONTINUATION_INDENT)]
    assert len(events) == 1
    assert "layer=error" in events[0]
