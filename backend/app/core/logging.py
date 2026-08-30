"""Logging configuration.

WHAT IS LOGGED, AND WHAT IS DELIBERATELY NOT
============================================

ANCHOR handles a student's private course material and their answers. Almost
everything interesting to log is also something that should not be written to a
log aggregator, so the rule here is narrow and explicit:

    logged        identifiers, counts, durations, outcomes, error CLASS
    never logged  passwords, tokens, API keys, connection strings,
                  document text, question text, student answers, feedback

`redact()` exists for the one place that rule is hard to keep by hand: an
exception string from a provider or a database driver, which routinely contains a
connection URL or an echoed prompt. Nothing reaches a log through this module
without passing that filter.

Format is plain text in development, where a person reads it, and JSON in
production, where a platform ingests it. No third-party logging dependency: the
standard library does both, and one fewer package is one fewer supply-chain risk
for a project that gains nothing from structlog here.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings

# Patterns whose matches are replaced before anything is written. These are the
# shapes that leak: a driver error quoting the DSN, a provider error echoing a key.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb|redis)(?:\+\w+)?://[^\s\"']+"),
        "<database-url-redacted>",
    ),
    # No trailing \b: a real Google key is AIza + 35 chars, but anchoring the end
    # means a longer key-shaped run would not be redacted at all. Over-redacting a
    # log line is free; under-redacting one is the failure this exists to prevent.
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35,}"), "<api-key-redacted>"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), "<api-key-redacted>"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]*"),
        "<token-redacted>",
    ),
    (
        re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\s*[=:]\s*\S+"),
        r"\1=<redacted>",
    ),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_\-.]+"), "Bearer <redacted>"),
)

# Log lines are capped: a provider error can carry an entire prompt back, and a
# truncated message is a far smaller problem than a student's material in a log.
MAX_MESSAGE_CHARS = 500


def redact(text: str) -> str:
    """Strip credential-shaped substrings and truncate.

    Applied to every record this configuration emits, including ones from
    third-party libraries — SQLAlchemy and httpx both log connection details at
    levels that are easy to enable by accident.
    """
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[:MAX_MESSAGE_CHARS] + "…[truncated]"
    return text


class RedactingFilter(logging.Filter):
    """Applies `redact` to the formatted message of every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # a broken format string must not break logging
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for a platform's log ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        if record.exc_info:
            # The exception TYPE, not its text or traceback: a traceback carries
            # local variables, which here means document text and student answers.
            payload["error"] = (
                record.exc_info[0].__name__ if record.exc_info[0] else "Error"
            )
        for key in (
            "event",
            "course_id",
            "document_id",
            "user_id",
            "status_code",
            "duration_ms",
            "provider",
            "bucket",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Install handlers once, at application start.

    Idempotent: `create_app` may be called more than once in a test session, and
    duplicate handlers would multiply every line.
    """
    root = logging.getLogger()
    if any(getattr(h, "_anchor", False) for h in root.handlers):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler._anchor = True  # type: ignore[attr-defined]
    handler.addFilter(RedactingFilter())

    if settings.is_production:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))

    root.handlers = [h for h in root.handlers if not getattr(h, "_anchor", False)]
    root.addHandler(handler)
    root.setLevel(logging.INFO if settings.is_production else logging.DEBUG)

    # These are chatty and their DEBUG output includes SQL parameters and request
    # bodies. Pinned to WARNING regardless of the root level so turning on debug
    # logging for ANCHOR never turns on data logging for its dependencies.
    for noisy in ("sqlalchemy.engine", "httpx", "httpcore", "google_genai", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Module-level logger. Use `extra={...}` for structured fields."""
    return logging.getLogger(name)
