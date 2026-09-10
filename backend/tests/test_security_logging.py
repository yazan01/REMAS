"""Single-use credentials must never reach a production log.

Written after finding three `log.info(... token ...)` calls that ran in every
environment. The neighbouring `dev-token` endpoint already gated on
`settings.environment`; these did not, which is the shape most log leaks take —
one path guarded, a sibling missed.

The tests below cover both halves: the value is present in development, where
the flow has to be completable without a mail server, and absent everywhere
else.
"""

from __future__ import annotations

import io
import logging
import re
from pathlib import Path

import pytest

from app.core import security

ROUTES = Path(__file__).resolve().parent.parent / "app" / "api" / "routes"

SECRET = "reset-token-DO-NOT-LEAK-9f2a"


@pytest.fixture
def captured_log():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("remas.security")
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


@pytest.mark.parametrize("environment", ["production", "staging", "test"])
def test_the_token_value_never_reaches_a_non_development_log(
    monkeypatch, captured_log, environment: str
) -> None:
    monkeypatch.setattr(security.settings, "environment", environment)
    security.log_delivery_token("password reset", "victim@example.com", SECRET)
    written = captured_log.getvalue()

    assert SECRET not in written, f"token leaked in {environment}"
    assert "victim@example.com" in written, "the event itself must still be recorded"
    assert "withheld" in written


def test_development_still_logs_the_token(monkeypatch, captured_log) -> None:
    """The comment on the call sites asks for a completable flow without a mail
    server; removing that would break local development, not improve security."""
    monkeypatch.setattr(security.settings, "environment", "development")
    security.log_delivery_token("password reset", "dev@example.com", SECRET)
    assert SECRET in captured_log.getvalue()


def test_no_route_logs_a_credential_directly() -> None:
    """A static sweep, so a fourth call site cannot be added the old way.

    Matches a logging call whose arguments mention a credential-shaped
    attribute. It is deliberately broad: a false positive costs one line of
    thought, a false negative costs an account.
    """
    pattern = re.compile(
        r"log\.(info|warning|error|debug)\([^)]*"
        r"(reset_token|verification_token|\.token\b|password|api_key|secret)",
        re.IGNORECASE | re.DOTALL,
    )
    offenders = []
    for path in sorted(ROUTES.rglob("*.py")):
        source = io.open(path, encoding="utf-8").read()
        for match in pattern.finditer(source):
            line = source[: match.start()].count("\n") + 1
            offenders.append(f"{path.name}:{line}: {match.group(0)[:70]}")
    assert not offenders, (
        "a credential is being logged directly; route it through "
        "core.security.log_delivery_token instead:\n  " + "\n  ".join(offenders)
    )
