"""The Bugsink alert receiver files one issue per error group (ADR-0146).

Bugsink has no GitHub integration — its only outbound path is a custom webhook
whose config is a bare URL, with no signing secret and no auth header. So two
properties carry the weight here: the URL token is the ONLY thing standing
between the open internet and this board, and a redelivery must not file a
second issue.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dashboard_routes._bugsink_routes import _authorised, register  # noqa: E402

TOKEN = "s3cret-token-value"

#: The upstream payload, field-for-field from Bugsink's own test message
#: (`alerts/service_backends/custom.py::custom_backend_send_test_message`).
#: Copied rather than paraphrased: a receiver tested against a payload we
#: invented would pass while mismatching what Bugsink actually posts.
ALERT = {
    "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
    "friendly_id": "TEST-1",
    "project": 1,
    "digest_order": 1,
    "first_seen": "2024-01-10T08:15:00Z",
    "last_seen": "2024-01-15T10:30:00Z",
    "digested_event_count": 15,
    "stored_event_count": 15,
    "calculated_type": "ValueError",
    "calculated_value": "invalid literal for int()",
    "transaction": "/api/users/login",
    "is_resolved": False,
    "is_muted": False,
    "title": "ValueError: invalid literal for int()",
    "project_name": "hydraflow",
    "url": "https://bugsink.example.com/issues/497f6eca/",
    "alert_reason": "NEW",
}


def _client(*, token: str = TOKEN, existing: int = 0, created: int = 4242):
    prs = SimpleNamespace(
        find_existing_issue=AsyncMock(return_value=existing),
        create_issue=AsyncMock(return_value=created),
    )
    ctx = SimpleNamespace(
        credentials=SimpleNamespace(bugsink_webhook_token=token),
        config=SimpleNamespace(
            find_label=["hydraflow-find"], exception_sensor_label=["bugsink"]
        ),
        pr_manager=prs,
    )
    router = APIRouter()
    register(router, ctx)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), prs


class TestTheUrlIsTheCredential:
    def test_the_right_token_files_an_issue(self) -> None:
        client, prs = _client()

        response = client.post(f"/api/bugsink/alert/{TOKEN}", json=ALERT)

        assert response.status_code == 200
        assert response.json()["created"] is True
        prs.create_issue.assert_awaited_once()

    def test_a_wrong_token_files_nothing(self) -> None:
        client, prs = _client()

        response = client.post("/api/bugsink/alert/not-the-token", json=ALERT)

        assert response.status_code == 404
        prs.create_issue.assert_not_awaited()

    def test_an_unconfigured_token_refuses_every_request(self) -> None:
        client, prs = _client(token="")

        for attempt in ("anything", TOKEN):
            response = client.post(f"/api/bugsink/alert/{attempt}", json=ALERT)
            assert response.status_code == 404, attempt
        prs.create_issue.assert_not_awaited()

    @pytest.mark.parametrize(
        "supplied",
        [
            pytest.param("", id="empty"),
            pytest.param(" ", id="space"),
            pytest.param(TOKEN, id="a-real-looking-token"),
        ],
    )
    def test_nothing_authorises_against_an_unconfigured_token(
        self, supplied: str
    ) -> None:
        """Tested on the decision, not through the route.

        The route cannot express this case: FastAPI will not match an empty
        path segment, so posting to `/api/bugsink/alert/` returns a routing 404
        and the guard never runs. The first version of this test did exactly
        that and passed with the guard deleted.
        """
        assert _authorised(supplied, "") is False

    def test_the_configured_token_still_authorises(self) -> None:
        """The decoy: a function that always returned False would pass above."""
        assert _authorised(TOKEN, TOKEN) is True


class TestOneIssuePerErrorGroup:
    def test_a_redelivery_does_not_file_a_second_issue(self) -> None:
        """Bugsink fires new-issue, regression and unmute for the SAME id."""
        client, prs = _client(existing=99)

        response = client.post(f"/api/bugsink/alert/{TOKEN}", json=ALERT)

        assert response.json() == {"issue": 99, "created": False}
        prs.create_issue.assert_not_awaited()

    def test_the_title_is_keyed_on_the_id_not_the_message(self) -> None:
        """Two events in a group can render different values; same group."""
        client, prs = _client()
        variant = {**ALERT, "calculated_value": "invalid literal for int(): 'b'"}

        client.post(f"/api/bugsink/alert/{TOKEN}", json=ALERT)
        first = prs.find_existing_issue.await_args.args[0]
        client.post(f"/api/bugsink/alert/{TOKEN}", json=variant)
        second = prs.find_existing_issue.await_args.args[0]

        assert first == second, "dedup key must not move when the message does"
        assert ALERT["id"] in first


class TestTheIssueEntersThePipeline:
    def test_it_carries_the_find_label_and_the_provenance_label(self) -> None:
        """Without find_label it is invisible; without bugsink it is anonymous."""
        client, prs = _client()

        client.post(f"/api/bugsink/alert/{TOKEN}", json=ALERT)

        labels = prs.create_issue.await_args.kwargs["labels"]
        assert "hydraflow-find" in labels, "must enter the triage pipeline"
        assert "bugsink" in labels, "must declare its provenance"

    def test_the_body_links_back_to_the_trace(self) -> None:
        client, prs = _client()

        client.post(f"/api/bugsink/alert/{TOKEN}", json=ALERT)

        body = prs.create_issue.await_args.args[1]
        assert ALERT["url"] in body
        assert "ValueError" in body


class TestBadInput:
    def test_a_non_object_body_is_rejected(self) -> None:
        client, prs = _client()

        response = client.post(f"/api/bugsink/alert/{TOKEN}", json=[1, 2, 3])

        assert response.status_code == 400
        prs.create_issue.assert_not_awaited()

    def test_a_malformed_body_is_rejected(self) -> None:
        """Exercises the decode path — `json=[1,2,3]` above is valid JSON."""
        client, prs = _client()

        response = client.post(
            f"/api/bugsink/alert/{TOKEN}",
            content=b"{not json at all",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400
        prs.create_issue.assert_not_awaited()

    def test_a_failed_filing_reports_upstream_rather_than_claiming_success(
        self,
    ) -> None:
        client, _prs = _client(created=0)

        response = client.post(f"/api/bugsink/alert/{TOKEN}", json=ALERT)

        assert response.status_code == 502
