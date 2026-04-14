"""SentryPort — observability surface for scenario tests."""

from __future__ import annotations

from typing import Any, runtime_checkable

from typing_extensions import Protocol


@runtime_checkable
class SentryPort(Protocol):
    def capture_exception(self, exc: BaseException, **kwargs: Any) -> None: ...
    def capture_message(self, message: str, **kwargs: Any) -> None: ...
    def add_breadcrumb(self, **kwargs: Any) -> None: ...
    def set_tag(self, key: str, value: str) -> None: ...
