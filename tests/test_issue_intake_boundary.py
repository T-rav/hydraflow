"""One authenticated front door for filing issues (ADR-0140 auth, ADR-0146 sensor).

The first version of this feature invented a URL token of its own. It was weaker
than the mechanism the repo already had — no loopback requirement — and invisible
to the ADR-0085 secret scrubber, which only recognises the `hfop_` grammar. These
pin the boundary onto `operator_identity` instead, in both directions.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dashboard_routes import _issue_intake_routes as intake_module  # noqa: E402
from dashboard_routes._issue_intake_routes import (  # noqa: E402
    _stacktrace_for,
    intake_open,
    register,
)
from operator_identity import OPERATOR_TOKEN_ENV  # noqa: E402

TOKEN = "hfop_" + "z" * 43
AUTH = {"Authorization": f"Bearer {TOKEN}"}

#: Field-for-field from Bugsink's own test message
#: (upstream `alerts/service_backends/custom.py`). Copied rather than invented:
#: a receiver tested against a payload we made up would pass while mismatching
#: what Bugsink actually posts.
ALERT = {
    "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
    "friendly_id": "TEST-1",
    "project_name": "hydraflow",
    "calculated_type": "ValueError",
    "calculated_value": "invalid literal for int()",
    "transaction": "/api/users/login",
    "first_seen": "2024-01-10T08:15:00Z",
    "last_seen": "2024-01-15T10:30:00Z",
    "digested_event_count": 15,
    "title": "ValueError: invalid literal for int()",
    "url": "https://bugsink.example.com/issues/497f6eca/",
    "alert_reason": "NEW",
}


@pytest.fixture(autouse=True)
def _configured_operator(monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)


def _client(
    *,
    host: str = "127.0.0.1",
    existing: int = 0,
    created: int = 4242,
    base_url: str = "",
    api_token: str = "",
):
    prs = SimpleNamespace(
        find_existing_issue=AsyncMock(return_value=existing),
        create_issue=AsyncMock(return_value=created),
    )
    ctx = SimpleNamespace(
        config=SimpleNamespace(
            dashboard_host=host,
            find_label=["hydraflow-find"],
            exception_sensor_label=["bugsink"],
            # Empty by default: enrichment is off unless a test opts in, so no
            # test reaches the network.
            bugsink_base_url=base_url,
        ),
        credentials=SimpleNamespace(bugsink_api_token=api_token),
        pr_manager=prs,
    )
    router = APIRouter()
    register(router, ctx)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), prs


class TestTheBoundaryUsesTheHouseCredential:
    def test_a_valid_operator_token_files_an_issue(self) -> None:
        client, prs = _client()

        response = client.post(
            "/api/issues/intake?source=bugsink", json=ALERT, headers=AUTH
        )

        assert response.status_code == 200
        prs.create_issue.assert_awaited_once()

    def test_no_token_is_refused(self) -> None:
        client, prs = _client()

        response = client.post("/api/issues/intake?source=bugsink", json=ALERT)

        assert response.status_code == 401
        prs.create_issue.assert_not_awaited()

    def test_a_wrong_token_is_refused(self) -> None:
        client, prs = _client()

        response = client.post(
            "/api/issues/intake?source=bugsink",
            json=ALERT,
            headers={"Authorization": "Bearer hfop_wrong"},
        )

        assert response.status_code == 401
        prs.create_issue.assert_not_awaited()

    def test_a_non_loopback_dashboard_has_no_intake_at_all(self) -> None:
        """ADR-0140's rule, not a new one: a credential checked on an interface
        the world can reach is a credential the world can brute-force."""
        client, prs = _client(host="0.0.0.0")  # noqa: S104

        response = client.post(
            "/api/issues/intake?source=bugsink", json=ALERT, headers=AUTH
        )

        assert response.status_code == 404
        prs.create_issue.assert_not_awaited()

    def test_an_unconfigured_operator_token_closes_the_gate(self, monkeypatch) -> None:
        monkeypatch.delenv(OPERATOR_TOKEN_ENV, raising=False)

        assert intake_open(SimpleNamespace(dashboard_host="127.0.0.1")) is False

    def test_a_configured_loopback_deployment_opens_it(self) -> None:
        """The decoy: a gate that always returned False would pass above."""
        assert intake_open(SimpleNamespace(dashboard_host="127.0.0.1")) is True


class TestSources:
    def test_a_bugsink_alert_gets_the_provenance_label(self) -> None:
        client, prs = _client()

        client.post("/api/issues/intake?source=bugsink", json=ALERT, headers=AUTH)

        labels = prs.create_issue.await_args.kwargs["labels"]
        assert "hydraflow-find" in labels, "must enter the triage pipeline"
        assert "bugsink" in labels, "must declare its provenance"

    def test_a_ui_report_is_not_labelled_as_a_system_exception(self) -> None:
        """The decoy for the label rule: `ui` must NOT claim sensor provenance."""
        client, prs = _client()

        client.post(
            "/api/issues/intake?source=ui",
            json={"title": "Board filter is stuck", "body": "steps..."},
            headers=AUTH,
        )

        labels = prs.create_issue.await_args.kwargs["labels"]
        assert "hydraflow-find" in labels
        assert "bugsink" not in labels

    def test_an_unknown_source_is_rejected(self) -> None:
        client, prs = _client()

        response = client.post(
            "/api/issues/intake?source=nonsense", json=ALERT, headers=AUTH
        )

        assert response.status_code == 400
        prs.create_issue.assert_not_awaited()


class TestOneIssuePerErrorGroup:
    def test_a_redelivery_does_not_file_a_second_issue(self) -> None:
        """Bugsink re-fires the SAME id on regression and unmute."""
        client, prs = _client(existing=99)

        response = client.post(
            "/api/issues/intake?source=bugsink", json=ALERT, headers=AUTH
        )

        assert response.json() == {"issue": 99, "created": False}
        prs.create_issue.assert_not_awaited()

    def test_the_dedup_key_is_the_group_id_not_the_message(self) -> None:
        client, prs = _client()
        variant = {**ALERT, "calculated_value": "invalid literal for int(): 'b'"}

        client.post("/api/issues/intake?source=bugsink", json=ALERT, headers=AUTH)
        first = prs.find_existing_issue.await_args.args[0]
        client.post("/api/issues/intake?source=bugsink", json=variant, headers=AUTH)
        second = prs.find_existing_issue.await_args.args[0]

        assert first == second, "dedup key must not move when the message does"
        assert ALERT["id"] in first


class TestStackTraceEnrichment:
    """The alert payload carries no frames, so triage would classify blind.

    Bugsink's IssueSerializer comments out last_frame_filename / _module /
    _function, so the webhook body is a type, a message, a transaction path and
    some counts. That matters more than it looks: a sensor issue that FAILS
    triage is auto-closed as a transient, so thin evidence does not just misfile
    a bug, it discards one.
    """

    def test_the_trace_is_appended_to_the_body(self, monkeypatch) -> None:
        async def _fake(issue_id, base_url, token, *, timeout=5.0):
            assert issue_id == ALERT["id"]
            return "```\nFile 'x.py', line 1\n```"

        monkeypatch.setattr(intake_module, "_stacktrace_for", _fake)
        client, prs = _client(base_url="http://bugsink:8000", api_token="tok")

        client.post("/api/issues/intake?source=bugsink", json=ALERT, headers=AUTH)

        body = prs.create_issue.await_args.args[1]
        assert "Stack trace" in body
        assert "File 'x.py', line 1" in body

    def test_an_unreachable_backend_still_files_the_issue(self, monkeypatch) -> None:
        """The signal is the issue; the trace is a bonus.

        Exercises the REAL failure — a transport error out of httpx — rather
        than monkeypatching the helper to raise. An earlier version did the
        latter, which tested the call site's robustness against an exception the
        helper cannot actually produce, and would have argued for a blind catch
        that `httpx.HTTPError` (the base of every transport AND status error)
        already covers.
        """

        class _DeadClient:
            def __init__(self, *_a, **_k) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc) -> bool:
                return False

            async def get(self, *_a, **_k):
                raise httpx.ConnectError("bugsink unreachable")

        monkeypatch.setattr(httpx, "AsyncClient", _DeadClient)
        client, prs = _client(base_url="http://bugsink:8000", api_token="tok")

        response = client.post(
            "/api/issues/intake?source=bugsink", json=ALERT, headers=AUTH
        )

        assert response.status_code == 200, "a dead backend must not lose the signal"
        prs.create_issue.assert_awaited_once()
        body = prs.create_issue.await_args.args[1]
        assert "Stack trace" not in body, "no trace, but the issue still lands"

    @pytest.mark.asyncio
    async def test_enrichment_is_off_without_a_token_or_url(self) -> None:
        """No network call is even attempted when unconfigured."""
        assert await _stacktrace_for("abc", "", "tok") == ""
        assert await _stacktrace_for("abc", "http://bugsink:8000", "") == ""
        assert await _stacktrace_for("", "http://bugsink:8000", "tok") == ""


class TestBadInput:
    def test_a_malformed_body_is_rejected(self) -> None:
        client, prs = _client()

        response = client.post(
            "/api/issues/intake?source=bugsink",
            content=b"{not json",
            headers={**AUTH, "Content-Type": "application/json"},
        )

        assert response.status_code == 400
        prs.create_issue.assert_not_awaited()

    def test_a_ui_report_with_no_title_is_rejected(self) -> None:
        client, prs = _client()

        response = client.post(
            "/api/issues/intake?source=ui", json={"body": "no title"}, headers=AUTH
        )

        assert response.status_code == 400
        prs.create_issue.assert_not_awaited()

    def test_a_failed_filing_reports_upstream_rather_than_claiming_success(
        self,
    ) -> None:
        client, _prs = _client(created=0)

        response = client.post(
            "/api/issues/intake?source=bugsink", json=ALERT, headers=AUTH
        )

        assert response.status_code == 502
