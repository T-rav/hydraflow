"""HindsightPort — semantic-memory surface for scenario tests."""

from __future__ import annotations

from typing import Any, runtime_checkable

from typing_extensions import Protocol


@runtime_checkable
class HindsightPort(Protocol):
    async def retain(
        self, bank: str, content: str, metadata: dict[str, Any] | None = None
    ) -> None: ...
    async def recall(
        self, bank: str, query: str, *, top_k: int = 5
    ) -> list[dict[str, Any]]: ...
    async def reflect(self, bank: str, prompt: str) -> str: ...
