"""One ``run_subprocess`` mock across every ``workspace`` slice, and the guard
that keeps every ``workspace`` patch target honest.

``WorkspaceManager`` became a package in #11547 batch 6. Most tests patch the
single slice whose method they exercise, which is the right shape and fails
loudly when a method moves.

A few flows genuinely cross slices: ``reset_to_main`` and ``merge_main`` live in
``workspace._mainline`` but the fetch they retry happens in
``workspace._remote``. A test that invokes the first and counts calls made by
the second needs ONE mock visible to both — patching a single slice intercepts
half the calls and the assertion then measures the wrong half.

Deliberately not solved by re-exporting ``run_subprocess`` from the package:
each slice binds it at import, so ``patch("workspace.run_subprocess")`` would
replace an attribute nothing reads and pass while testing nothing.

Why the recorder below exists
-----------------------------
Batch 6 chose each test's patch target *empirically* — try a slice, keep the one
that makes the test pass. That method cannot tell a correct target from a wrong
one whenever the assertion is weak enough to be satisfied by the error-swallow
path: patch the wrong slice, the real ``run_subprocess`` runs, its failure is
caught by a broad ``except``, and ``assert result is None`` / ``assert not
any(...)`` is trivially true. Five such sites shipped (#11547 review).

``PatchConsultationRecorder`` makes that shape loud rather than silent: a mock
installed at a ``workspace`` target and then never consulted is a defect, and
``tests/conftest.py`` fails the test that leaves one behind. A test that
genuinely proves a call is NOT made declares it with ``expect_unconsulted``.
"""

from __future__ import annotations

import unittest.mock as mock_module
from contextlib import ExitStack, contextmanager
from types import TracebackType
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, NonCallableMock, patch

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator

#: Every slice that binds ``run_subprocess``. Kept explicit so that adding a
#: slice which binds it without listing it here fails loudly — the guard is
#: ``tests/architecture/test_workspace_patch_targets.py``, which reads the real
#: ``src/workspace/*.py`` imports and compares them against this tuple.
WORKSPACE_SLICES: tuple[str, ...] = (
    "_manager",
    "_heal",
    "_mainline",
    "_provision",
    "_remote",
)

#: Module prefixes whose patch targets must be consulted. Deliberately narrow:
#: this is the package the #11547 review found the class in. Widening it is a
#: ratchet, not a rewrite — add a prefix and fix what it reddens.
GUARDED_PATCH_ROOTS: tuple[str, ...] = ("workspace",)

#: Stamped into a mock's ``__dict__`` by :func:`expect_unconsulted`.
_EXPECT_UNCONSULTED = "_hf_expect_unconsulted"


def expect_unconsulted(target_mock: NonCallableMock, reason: str) -> None:
    """Declare that *target_mock* is deliberately never consulted.

    Asserts it really wasn't, then exempts it from the ambient
    :class:`PatchConsultationRecorder` check. Use this — never a bare
    ``assert_not_called()`` — when the point of the test is that a code path
    short-circuits before it would have called the patched symbol.
    """
    target_mock.assert_not_called()
    target_mock.__dict__[_EXPECT_UNCONSULTED] = reason


def _module_name(target: object) -> str:
    return getattr(target, "__name__", "") or ""


def _is_guarded(module_name: str, roots: tuple[str, ...]) -> bool:
    return any(module_name == r or module_name.startswith(f"{r}.") for r in roots)


class PatchConsultationRecorder:
    """Record ``unittest.mock`` patches aimed at *roots* and flag unused ones.

    Wraps ``_patch.__enter__`` for the duration of the context, so it sees the
    ``patch()``/``patch.object()``/``@patch`` forms alike (all three enter the
    same code path). Only ``Mock`` replacements are recorded — patching in a
    plain object (a stub dict, a lambda) leaves nothing to interrogate.
    """

    def __init__(self, roots: tuple[str, ...] = GUARDED_PATCH_ROOTS) -> None:
        self._roots = tuple(roots)
        self._installed: list[tuple[str, NonCallableMock]] = []
        self._outer: Any = None
        self.violations: list[str] = []

    def __enter__(self) -> PatchConsultationRecorder:
        outer = mock_module._patch.__enter__
        self._outer = outer
        recorder = self

        def _enter(patcher: Any) -> Any:
            new = outer(patcher)
            module_name = _module_name(getattr(patcher, "target", None))
            if _is_guarded(module_name, recorder._roots) and isinstance(
                new, NonCallableMock
            ):
                recorder._installed.append((f"{module_name}.{patcher.attribute}", new))
            return new

        mock_module._patch.__enter__ = _enter  # type: ignore[method-assign]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        mock_module._patch.__enter__ = self._outer  # type: ignore[method-assign]
        self.violations = [
            label
            for label, target_mock in self._installed
            if target_mock.call_count == 0
            and _EXPECT_UNCONSULTED not in target_mock.__dict__
        ]
        return False


@contextmanager
def patch_workspace_run_subprocess(**kwargs: Any) -> Iterator[AsyncMock]:
    """Patch ``run_subprocess`` in every slice with a single shared mock."""
    target_mock = AsyncMock(**kwargs)
    with ExitStack() as stack:
        for slice_name in WORKSPACE_SLICES:
            stack.enter_context(
                patch(f"workspace.{slice_name}.run_subprocess", target_mock)
            )
        yield target_mock
