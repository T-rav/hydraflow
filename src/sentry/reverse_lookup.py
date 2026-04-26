"""Sentry reverse lookup — given an issue title or fingerprint, find recent events.

Spec §3.2 / §3.6. Used by PreflightContext to enrich the agent's prompt with
recent Sentry events relevant to the escalated issue.

Failure mode: returns [] and logs a warning. Never raises to the caller —
absent Sentry data is a degraded but valid pre-flight context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("hydraflow.sentry.reverse_lookup")


@dataclass(frozen=True)
class SentryEvent:
    sentry_id: str
    title: str
    message: str
    level: str
    last_seen: str  # ISO 8601
    permalink: str
    event_count: int
    user_count: int


async def query_sentry_by_title(
    title: str,
    *,
    auth_token: str,
    org: str,
    project: str | None = None,
    limit: int = 5,
    client: httpx.AsyncClient | None = None,
) -> list[SentryEvent]:
    """Query Sentry's issue-search API for events matching `title`.

    Returns up to `limit` events, newest first. Returns [] on any failure
    (auth, HTTP, parse). Never raises.
    """
    if not auth_token or not org:
        logger.info("Sentry reverse lookup skipped — missing creds")
        return []

    base = "https://sentry.io/api/0"
    if project:
        url = f"{base}/projects/{org}/{project}/issues/"
    else:
        url = f"{base}/organizations/{org}/issues/"

    params = {"query": title, "limit": str(limit)}
    headers = {"Authorization": f"Bearer {auth_token}"}

    own_client = client is None
    cli = client or httpx.AsyncClient(timeout=10.0)

    try:
        try:
            resp = await cli.get(url, params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Sentry reverse-lookup HTTP error: %s", exc)
            return []
        except ValueError as exc:
            logger.warning("Sentry reverse-lookup parse error: %s", exc)
            return []

        return [_parse(item) for item in payload[:limit]]
    finally:
        if own_client:
            await cli.aclose()


def _parse(item: dict[str, Any]) -> SentryEvent:
    return SentryEvent(
        sentry_id=str(item.get("id", "")),
        title=str(item.get("title", "")),
        message=str(
            item.get("metadata", {}).get("value", "") or item.get("culprit", "")
        ),
        level=str(item.get("level", "error")),
        last_seen=str(item.get("lastSeen", "")),
        permalink=str(item.get("permalink", "")),
        event_count=int(item.get("count", 0) or 0),
        user_count=int(item.get("userCount", 0) or 0),
    )
