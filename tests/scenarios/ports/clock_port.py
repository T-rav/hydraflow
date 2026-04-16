"""ClockPort — deterministic time surface for scenario tests."""

from __future__ import annotations

from typing import runtime_checkable

from typing_extensions import Protocol


@runtime_checkable
class ClockPort(Protocol):
    def now(self) -> float: ...
    def monotonic(self) -> float: ...
    async def sleep(self, seconds: float) -> None: ...
    def advance(self, seconds: float) -> None: ...
