"""Guards for ``workspace`` patch targets (#11547 review).

Two failure modes, both of which shipped silently in batch 6:

1. ``tests/workspace_patch.WORKSPACE_SLICES`` drifting from the slices that
   actually bind ``run_subprocess``. The tuple's own comment claimed a guard
   enforced it; none existed. :class:`TestWorkspaceSlicesTupleIsComplete` is
   that guard.
2. A patch aimed at a slice the code under test does not bind. The mock is
   never consulted, the real subprocess runs, its failure is swallowed by the
   production code's broad ``except``, and the test's weak assertion passes
   anyway. :class:`TestPatchConsultationRecorder` proves the detector behind
   ``tests/conftest.py::_workspace_patches_must_be_consulted`` reddens on
   exactly that shape.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.workspace_patch import (
    WORKSPACE_SLICES,
    PatchConsultationRecorder,
    expect_unconsulted,
)

_WORKSPACE_PKG = Path(__file__).resolve().parents[2] / "src" / "workspace"


def _slices_binding(symbol: str) -> set[str]:
    """Slice module names whose source imports *symbol* at module level."""
    bound: set[str] = set()
    for path in sorted(_WORKSPACE_PKG.glob("_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                alias.asname == symbol
                or (alias.asname is None and alias.name == symbol)
                for alias in node.names
            ):
                bound.add(path.stem)
    return bound


class TestWorkspaceSlicesTupleIsComplete:
    """WORKSPACE_SLICES must name every slice that binds ``run_subprocess``."""

    def test_tuple_matches_the_slices_that_bind_run_subprocess(self) -> None:
        assert _slices_binding("run_subprocess") == set(WORKSPACE_SLICES), (
            "tests/workspace_patch.WORKSPACE_SLICES has drifted from src/workspace/. "
            "patch_workspace_run_subprocess() would leave a slice unpatched, and a "
            "test counting cross-slice calls would silently measure the wrong half."
        )

    def test_every_named_slice_exists(self) -> None:
        missing = [
            name
            for name in WORKSPACE_SLICES
            if not (_WORKSPACE_PKG / f"{name}.py").exists()
        ]
        assert not missing, f"WORKSPACE_SLICES names non-existent slices: {missing}"


class TestPatchConsultationRecorder:
    """The detector must flag an installed-but-unused workspace mock."""

    def test_flags_a_patch_whose_mock_is_never_consulted(self) -> None:
        with (
            PatchConsultationRecorder() as recorder,
            patch(
                "workspace._manager.run_subprocess", new_callable=AsyncMock
            ) as never_used,
        ):
            pass

        assert recorder.violations == ["workspace._manager.run_subprocess"]
        expect_unconsulted(never_used, "the subject of this test")

    def test_accepts_a_patch_whose_mock_is_consulted(self) -> None:
        with (
            PatchConsultationRecorder() as recorder,
            patch("workspace._manager.run_subprocess", new_callable=AsyncMock) as used,
        ):
            asyncio.run(used("git", "status"))

        assert recorder.violations == []

    def test_expect_unconsulted_exempts_a_deliberate_non_call(self) -> None:
        with (
            PatchConsultationRecorder() as recorder,
            patch(
                "workspace._remote.run_subprocess", new_callable=AsyncMock
            ) as declared,
        ):
            expect_unconsulted(declared, "deliberate")

        assert recorder.violations == []

    def test_expect_unconsulted_rejects_a_mock_that_was_called(self) -> None:
        called = MagicMock()
        called()
        with pytest.raises(AssertionError):
            expect_unconsulted(called, "wrong claim")

    def test_ignores_patch_targets_outside_the_guarded_roots(self) -> None:
        with (
            PatchConsultationRecorder() as recorder,
            patch("subprocess_util.run_subprocess", new_callable=AsyncMock),
        ):
            pass

        assert recorder.violations == []

    def test_restores_the_original_patch_enter(self) -> None:
        import unittest.mock as mock_module

        before = mock_module._patch.__enter__
        with PatchConsultationRecorder():
            assert mock_module._patch.__enter__ is not before
        assert mock_module._patch.__enter__ is before
