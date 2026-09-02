"""Inbound half of the exception sensor: Bugsink alerts become issues (ADR-0146).

Bugsink has **no GitHub integration**. Its only outbound mechanism is a custom
webhook that POSTs a JSON representation of the issue to a URL you control
(`alerts/service_backends/custom.py` upstream), firing on a new issue, a
regression, or an unmute. So the half that turns an error into a board item has
to live here.

This is still not a polling loop, which is the thing ADR-0146 declined to build:
Bugsink pushes, so there is no interval, no cursor and no backoff to keep
correct. The receiver is a route.

**The URL is the credential.** Bugsink's webhook config is a URL and nothing
else — no signing secret, no auth header — so an endpoint that files GitHub
issues from unauthenticated POSTs would be an open invitation. The token is a
path segment, compared in constant time, and a mismatch is a 404 rather than a
401 so the endpoint does not confirm its own existence to a prober.
"""

from __future__ import annotations

import hmac
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from dashboard_routes._routes import RouteContext

logger = logging.getLogger("hydraflow.dashboard.bugsink")

#: Bugsink fires the same issue at us more than once by design — a new issue,
#: then a regression, then an unmute all carry the SAME ``id``. The id is
#: therefore what the title is keyed on, so a redelivery finds the open issue
#: instead of filing a second one.
_TITLE_PREFIX = "[bugsink]"


def _title_for(payload: dict[str, Any]) -> str:
    """A stable, greppable title keyed on the Bugsink issue id.

    The id and not the message: two events in one error group can render
    different values (``invalid literal for int(): 'a'`` vs ``'b'``) while being
    the same group, and keying on the text would file one issue per variation.
    """
    issue_id = str(payload.get("id") or "").strip()
    title = str(payload.get("title") or "").strip() or "Unnamed error"
    return f"{_TITLE_PREFIX} {title} ({issue_id})"


def _body_for(payload: dict[str, Any]) -> str:
    """The evidence a triager needs, and a link back to the full trace."""
    rows = [
        ("Bugsink id", payload.get("id")),
        ("Reference", payload.get("friendly_id")),
        ("Project", payload.get("project_name")),
        ("Type", payload.get("calculated_type")),
        ("Value", payload.get("calculated_value")),
        ("Transaction", payload.get("transaction")),
        ("First seen", payload.get("first_seen")),
        ("Last seen", payload.get("last_seen")),
        ("Events digested", payload.get("digested_event_count")),
        ("Alert reason", payload.get("alert_reason")),
    ]
    table = "\n".join(
        f"| {label} | {value} |" for label, value in rows if value not in (None, "")
    )
    url = str(payload.get("url") or "").strip()
    link = f"\n\n[Open in Bugsink]({url})" if url else ""
    return (
        "## Incoming system exception\n\n"
        "Filed by the exception sensor (ADR-0146), not by a person. The "
        "evidence below is Bugsink's; the stack trace is behind the link.\n\n"
        "| Field | Value |\n| --- | --- |\n"
        f"{table}{link}\n"
    )


def _authorised(supplied: str, expected: str) -> bool:
    """Is *supplied* the configured webhook token?

    A function rather than an inline check because the "unconfigured" case is
    not reachable through the route — FastAPI will not match an empty path
    segment, so a test that posts to ``/api/bugsink/alert/`` gets a routing 404
    and proves nothing about this decision. Mutation testing caught exactly
    that: the whole suite passed with the empty-token guard deleted. Pulling the
    decision out makes it directly testable, which is the only way the guard is
    more than decoration.

    Unconfigured means CLOSED. An empty expected token must never compare equal
    to anything, or a deployment that simply forgot to set it becomes an
    anonymous issue-filing endpoint pointed at a public board.
    """
    if not expected:
        return False
    return hmac.compare_digest(supplied, expected)


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Mount the Bugsink alert receiver."""

    @router.post("/api/bugsink/alert/{token}")
    async def receive_bugsink_alert(token: str, request: Request) -> JSONResponse:
        expected = (ctx.credentials.bugsink_webhook_token or "").strip()
        # One exit for both refusals, so the endpoint cannot be probed for the
        # difference between "no token configured" and "wrong token".
        if not _authorised(token, expected):
            logger.warning(
                "bugsink alert refused (%s)",
                "unconfigured" if not expected else "token mismatch",
            )
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        try:
            payload = await request.json()
        except ValueError:
            # Narrow deliberately: json.JSONDecodeError and UnicodeDecodeError
            # both subclass ValueError, which covers every way a body can be
            # malformed. A broad catch here would also swallow a client
            # disconnect mid-read and answer 400 to something that was not the
            # caller's syntax error.
            return JSONResponse({"detail": "invalid JSON"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "expected an object"}, status_code=400)

        title = _title_for(payload)
        existing = await ctx.pr_manager.find_existing_issue(title)
        if existing:
            # A regression or unmute on a group already on the board. Say so
            # rather than filing a duplicate; the sensor's job is one issue per
            # error group.
            logger.info("bugsink alert deduplicated onto issue #%d", existing)
            return JSONResponse({"issue": existing, "created": False})

        labels = [*ctx.config.find_label[:1], *ctx.config.exception_sensor_label[:1]]
        number = await ctx.pr_manager.create_issue(
            title, _body_for(payload), labels=labels
        )
        if not number:
            logger.error("bugsink alert could not be filed as an issue")
            return JSONResponse({"detail": "could not file issue"}, status_code=502)

        logger.info("bugsink alert filed as issue #%d", number)
        return JSONResponse({"issue": number, "created": True})
