"""Hindsight semantic memory client.

Wraps the Hindsight REST API (vectorize-io/hindsight) for retain/recall/reflect
operations.  All public helpers are fire-and-forget or never-raise so that a
Hindsight outage cannot break the main orchestration loop.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger("hydraflow.hindsight")


# ---------------------------------------------------------------------------
# Bank IDs
# ---------------------------------------------------------------------------


class Bank(StrEnum):
    """Hindsight memory bank identifiers."""

    LEARNINGS = "hydraflow-learnings"
    RETROSPECTIVES = "hydraflow-retrospectives"
    REVIEW_INSIGHTS = "hydraflow-review-insights"
    HARNESS_INSIGHTS = "hydraflow-harness-insights"
    TROUBLESHOOTING = "hydraflow-troubleshooting"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class HindsightMemory(BaseModel):
    """A single memory item returned by Hindsight recall."""

    content: str
    context: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    relevance_score: float = 0.0
    timestamp: str = ""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class HindsightClient:
    """Async HTTP client for the Hindsight REST API."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        timeout: int = 30,
    ) -> None:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # -- Health ---------------------------------------------------------------

    async def health_check(self) -> bool:
        """Return ``True`` if the Hindsight server is reachable."""
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    # -- Retain ---------------------------------------------------------------

    async def retain(
        self,
        bank: Bank | str,
        content: str,
        *,
        context: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store a memory in *bank*."""
        payload: dict[str, Any] = {
            "bank": str(bank),
            "content": content,
            "context": context,
            "metadata": metadata or {},
            "timestamp": datetime.now(UTC).isoformat(),
        }
        resp = await self._client.post("/retain", json=payload)
        resp.raise_for_status()
        return resp.json()

    # -- Recall ---------------------------------------------------------------

    async def recall(
        self,
        bank: Bank | str,
        query: str,
        *,
        limit: int = 10,
    ) -> list[HindsightMemory]:
        """Retrieve relevant memories from *bank*."""
        payload: dict[str, Any] = {
            "bank": str(bank),
            "query": query,
            "limit": limit,
        }
        resp = await self._client.post("/recall", json=payload)
        resp.raise_for_status()
        data = resp.json()
        items: list[dict[str, Any]] = data.get("memories", data.get("results", []))
        return [HindsightMemory.model_validate(m) for m in items]

    # -- Reflect --------------------------------------------------------------

    async def reflect(
        self,
        bank: Bank | str,
        query: str,
    ) -> str:
        """Ask Hindsight for a synthesised reflection on *bank*."""
        payload: dict[str, Any] = {
            "bank": str(bank),
            "query": query,
        }
        resp = await self._client.post("/reflect", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("reflection", "")


# ---------------------------------------------------------------------------
# Safe wrappers (fire-and-forget / never-raise)
# ---------------------------------------------------------------------------


async def retain_safe(
    client: HindsightClient | None,
    bank: Bank | str,
    content: str,
    *,
    context: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget retain — logs and swallows all errors."""
    if client is None:
        return
    try:
        await client.retain(bank, content, context=context, metadata=metadata)
    except Exception:
        logger.warning("Hindsight retain failed for bank=%s", bank, exc_info=True)


async def recall_safe(
    client: HindsightClient | None,
    bank: Bank | str,
    query: str,
    *,
    limit: int = 10,
) -> list[HindsightMemory]:
    """Never-raise recall — returns ``[]`` on any failure."""
    if client is None:
        return []
    try:
        return await client.recall(bank, query, limit=limit)
    except Exception:
        logger.warning("Hindsight recall failed for bank=%s", bank, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_memories_as_markdown(memories: list[HindsightMemory]) -> str:
    """Format recalled memories as a markdown section for prompt injection."""
    if not memories:
        return ""
    lines: list[str] = []
    for mem in memories:
        lines.append(f"- {mem.content}")
        if mem.context:
            lines.append(f"  _Context: {mem.context}_")
    return "\n".join(lines)
