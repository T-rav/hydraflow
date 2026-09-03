"""#12067: an `error` heartbeat must carry the exception that caused it.

`term_proposer` tripped the persistent-error actuator for five consecutive
cycles and the issue it filed was undiagnosable: its own operator playbook
said "check orchestrator logs for recent cycle exceptions (heartbeat details
carry no error message)". The loop had the exception in hand — `_execute_cycle`
logs it with `logger.exception` — and then called `_report_cycle_failure` with
a generic string and `details={}`, dropping the cause at the one boundary that
survives into the filed issue.

The logs are not a substitute: they roll over, they are per-host, and the
actuator files the issue hours later from persisted heartbeat state.
"""

from __future__ import annotations

from typing import Any

import pytest

from base_background_loop import BaseBackgroundLoop


class _Bus:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.published.append(event)


class _Loop(BaseBackgroundLoop):
    """Minimal concrete loop whose cycle raises a distinctive exception."""

    def __init__(self, *, bus: _Bus, statuses: list[tuple[str, str, dict]]) -> None:
        self._bus = bus
        self._worker_name = "term_proposer"
        self._statuses = statuses
        self._status_cb = lambda n, s, d: statuses.append((n, s, dict(d)))

    def _get_default_interval(self) -> int:  # pragma: no cover - unused
        return 60

    async def _do_work(self) -> dict[str, Any] | None:  # pragma: no cover - unused
        return None


@pytest.mark.asyncio
async def test_error_heartbeat_details_name_the_exception() -> None:
    """The persisted heartbeat carries the exception type and message."""
    bus = _Bus()
    statuses: list[tuple[str, str, dict]] = []
    loop = _Loop(bus=bus, statuses=statuses)

    try:
        raise KeyError("gateway_role")
    except KeyError as exc:
        await loop._report_cycle_failure("Term proposer loop error", exc=exc)

    assert len(statuses) == 1
    _name, status, details = statuses[0]
    assert status == "error"
    assert details.get("error_type") == "KeyError"
    assert "gateway_role" in str(details.get("error"))


@pytest.mark.asyncio
async def test_error_event_message_carries_the_cause() -> None:
    """The ERROR event is the operator-visible copy — it must say why too."""
    bus = _Bus()
    loop = _Loop(bus=bus, statuses=[])

    try:
        raise ValueError("no draft adapter configured")
    except ValueError as exc:
        await loop._report_cycle_failure("Term proposer loop error", exc=exc)

    messages = [
        e.data["message"]
        for e in bus.published
        if isinstance(getattr(e, "data", None), dict) and "message" in e.data
    ]
    assert messages, "no ERROR event published"
    assert any("no draft adapter configured" in m for m in messages)
    assert any("ValueError" in m for m in messages)


@pytest.mark.asyncio
async def test_watchdog_timeout_still_reports_without_an_exception() -> None:
    """The watchdog branch has no exception — it must stay a clean report.

    The decoy for the fix: making `exc` required would break the timeout path,
    which reports a bounded overrun rather than a code fault (#9556).
    """
    bus = _Bus()
    statuses: list[tuple[str, str, dict]] = []
    loop = _Loop(bus=bus, statuses=statuses)

    await loop._report_cycle_failure("Term proposer loop watchdog timeout")

    assert statuses == [("term_proposer", "error", {})]


@pytest.mark.asyncio
async def test_secrets_in_the_exception_are_scrubbed() -> None:
    """Heartbeats persist to disk and land in a public issue body."""
    bus = _Bus()
    statuses: list[tuple[str, str, dict]] = []
    loop = _Loop(bus=bus, statuses=statuses)

    token = "ghp_" + "A" * 36
    try:
        raise RuntimeError(f"gh auth failed with token {token}")
    except RuntimeError as exc:
        await loop._report_cycle_failure("Term proposer loop error", exc=exc)

    blob = repr(statuses) + repr([getattr(e, "data", None) for e in bus.published])
    assert token not in blob


# ---------------------------------------------------------------------------
# The other half: the actuator must render what the loop now records. A cause
# stored in the heartbeat but dropped from the issue body is the same bug one
# module over.
# ---------------------------------------------------------------------------


def test_issue_body_renders_the_recorded_cause() -> None:
    from health_monitor_loop._errors import _cause_line

    line = _cause_line(
        {"status": "error", "details": {"error_type": "KeyError", "error": "role"}}
    )

    assert "KeyError" in line
    assert "role" in line


def test_issue_body_says_so_when_no_cause_was_recorded() -> None:
    """A loop reporting `error` by another route still files a legible issue."""
    from health_monitor_loop._errors import _cause_line

    assert "not recorded" in _cause_line({"status": "error", "details": {}})
    assert "not recorded" in _cause_line({"status": "error"})
    assert "not recorded" in _cause_line({"status": "error", "details": "junk"})


def test_playbook_no_longer_claims_heartbeats_carry_no_error() -> None:
    """The sentence that made #12067 undiagnosable must be gone.

    Pinned as text because it is the operator-facing instruction, and the fix
    is only real if the issue stops sending people to logs that rolled over.
    """
    from pathlib import Path

    source = Path("src/health_monitor_loop/_errors.py").read_text(encoding="utf-8")

    assert "heartbeat details carry no error message" not in source
    assert "_cause_line(hb)" in source
