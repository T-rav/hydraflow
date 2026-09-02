"""One authenticated front door for filing issues into the pipeline.

Anything that wants to put work on the board from outside a loop comes through
here: the UI's "report a problem" action, and the exception sensor's alerts
(ADR-0146). One boundary rather than one endpoint per source, because each new
bespoke entry point is another place to get authentication subtly wrong — and
the first draft of this did exactly that, inventing a URL token that was both
weaker than the house mechanism and invisible to the ADR-0085 secret scrubber.

**Authentication is ADR-0140's, unchanged.** ``authenticate_operator`` for the
credential (bearer, constant-time, unconfigured authenticates nobody) and a
gate with ``write_gate``'s shape and ordering: the bind that makes
authentication meaningful, then the credential itself. A deployment that is not
on loopback does not get an issue-filing endpoint at all.

**Webhooks that cannot set headers do not get an exception here.** Bugsink's
alert config is a bare URL — no signing secret, no auth header — so it cannot
present a bearer token. The answer is a proxy in front
(``docker-compose.bugsink.yml``) that turns its URL token into an
``Authorization`` header, NOT a second credential path through this module.
The concession lives at the edge; the application keeps one way in.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from operator_identity import (
    OPERATOR_TOKEN_ENV,
    OperatorIdentity,
    authenticate_operator,
    is_loopback,
)

if TYPE_CHECKING:
    from dashboard_routes._routes import RouteContext

logger = logging.getLogger("hydraflow.dashboard.issue_intake")


def intake_open(config: Any, env: Any = None) -> bool:
    """Whether the intake plane may serve a request at all.

    Mirrors ``operator_identity.write_gate``'s ordering deliberately: the bind
    first, because a credential checked on an interface the world can reach is
    a credential the world can brute-force, then the credential.
    """
    environment = os.environ if env is None else env
    if not is_loopback(str(getattr(config, "dashboard_host", "") or "")):
        return False
    return bool(environment.get(OPERATOR_TOKEN_ENV, "").strip())


def _bugsink_issue(payload: dict[str, Any]) -> tuple[str, str]:
    """Normalise a Bugsink alert into a title and body.

    The title is keyed on the Bugsink issue ``id`` and not on the message:
    Bugsink re-fires the SAME id on regression and unmute, and two events in one
    group can render different values (``invalid literal for int(): 'a'`` vs
    ``'b'``), so keying on the text would file one issue per variation.
    """
    issue_id = str(payload.get("id") or "").strip()
    title = str(payload.get("title") or "").strip() or "Unnamed error"
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
    body = (
        "## Incoming system exception\n\n"
        "Filed by the exception sensor (ADR-0146), not by a person. The evidence "
        "below is the backend's; the stack trace is behind the link.\n\n"
        "| Field | Value |\n| --- | --- |\n"
        f"{table}{link}\n"
    )
    return f"[bugsink] {title} ({issue_id})", body


def _ui_issue(payload: dict[str, Any]) -> tuple[str, str]:
    """Normalise a report raised from the operator console."""
    title = str(payload.get("title") or "").strip()
    body = str(payload.get("body") or "").strip()
    return title, body or "_No description supplied._"


#: source -> (normaliser, provenance-label attribute on config).
_SOURCES = {
    "bugsink": (_bugsink_issue, "exception_sensor_label"),
    "ui": (_ui_issue, None),
}


async def _read_object(request: Request) -> dict[str, Any] | JSONResponse:
    """The request body as a JSON object, or the response explaining why not."""
    try:
        payload = await request.json()
    except ValueError:
        # json.JSONDecodeError and UnicodeDecodeError both subclass this; a
        # broad catch would also swallow a mid-read client disconnect and answer
        # 400 to something that was not the caller's syntax error.
        return JSONResponse({"detail": "invalid JSON"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"detail": "expected an object"}, status_code=400)
    return payload


def _refuse(
    ctx: RouteContext, source: str, authorization: str | None
) -> tuple[JSONResponse | None, OperatorIdentity | None]:
    """The refusal this request earns, or the operator it authenticated as."""
    if not intake_open(ctx.config):
        # A closed deployment does not advertise the endpoint's existence.
        return JSONResponse({"detail": "Not Found"}, status_code=404), None
    operator = authenticate_operator(authorization)
    if operator is None:
        logger.warning("issue intake refused: bad or absent operator token")
        return JSONResponse({"detail": "Unauthorized"}, status_code=401), None
    if source not in _SOURCES:
        return JSONResponse(
            {"detail": f"unknown source {source!r}"}, status_code=400
        ), None
    return None, operator


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Mount the issue intake boundary."""

    @router.post("/api/issues/intake")
    async def intake_issue(
        request: Request,
        source: str = "ui",
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        refusal, operator = _refuse(ctx, source, authorization)
        if refusal is not None or operator is None:
            return refusal or JSONResponse({"detail": "Not Found"}, status_code=404)

        payload = await _read_object(request)
        if isinstance(payload, JSONResponse):
            return payload

        normalise, label_attr = _SOURCES[source]
        title, body = normalise(payload)
        if not title:
            return JSONResponse({"detail": "a title is required"}, status_code=400)

        existing = await ctx.pr_manager.find_existing_issue(title)
        if existing:
            logger.info(
                "issue intake (%s) deduplicated onto #%d by %s",
                source,
                existing,
                operator.actor,
            )
            return JSONResponse({"issue": existing, "created": False})

        labels = list(ctx.config.find_label[:1])
        if label_attr:
            labels += list(getattr(ctx.config, label_attr)[:1])
        number = await ctx.pr_manager.create_issue(title, body, labels=labels)
        if not number:
            logger.error("issue intake (%s) could not file an issue", source)
            return JSONResponse({"detail": "could not file issue"}, status_code=502)

        logger.info("issue intake (%s) filed #%d by %s", source, number, operator.actor)
        return JSONResponse({"issue": number, "created": True})
