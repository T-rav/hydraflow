"""Regression test for issue #6814.

Bug: ``transcript_summarizer.py`` and ``metrics_manager.py`` both use
``except Exception:`` without calling ``reraise_on_credit_or_bug()``.
This silently swallows ``AuthenticationError`` and
``CreditExhaustedError``, preventing the orchestrator's credit-pause
mechanism from learning about exhaustion from these paths.

Affected sites:
- ``src/transcript_summarizer.py:198`` — ``summarize_and_comment()``
- ``src/metrics_manager.py:211`` — ``_build_snapshot()``

Expected behaviour after fix:
  - ``AuthenticationError`` and ``CreditExhaustedError`` propagate up
    from both sites so the orchestrator's credit-pause / auth-retry
    logic can handle them.

These tests assert the *correct* behaviour and are RED against the
current (buggy) code.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from metrics_manager import MetricsManager
from subprocess_util import AuthenticationError, CreditExhaustedError
from tests.helpers import ConfigFactory
from transcript_summarizer import TranscriptSummarizer

SRC = Path(__file__).resolve().parent.parent.parent / "src"

REQUIRED_GUARD = "reraise_on_credit_or_bug"

#: (file, approx_line, short description) from the issue findings.
KNOWN_UNGUARDED_SITES: list[tuple[str, int, str]] = [
    ("transcript_summarizer.py", 198, "summarize_and_comment except Exception handler"),
    (
        "metrics_manager.py",
        211,
        "_build_snapshot get_label_counts except Exception handler",
    ),
]


# ---------------------------------------------------------------------------
# AST helpers (shared with sibling regression tests)
# ---------------------------------------------------------------------------


def _except_exception_handlers(tree: ast.Module) -> list[ast.ExceptHandler]:
    """Return all ``except Exception`` handler nodes in *tree*."""
    handlers: list[ast.ExceptHandler] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if isinstance(node.type, ast.Name) and node.type.id == "Exception":
            handlers.append(node)
    return handlers


def _handler_calls_reraise_guard(handler: ast.ExceptHandler) -> bool:
    """Return True if the handler body calls ``reraise_on_credit_or_bug``."""
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == REQUIRED_GUARD:
            return True
        if isinstance(func, ast.Attribute) and func.attr == REQUIRED_GUARD:
            return True
    return False


def _unguarded_handlers(filepath: Path) -> list[tuple[int, ast.ExceptHandler]]:
    """Return ``(lineno, handler)`` pairs for every ``except Exception``
    that does **not** call ``reraise_on_credit_or_bug``.
    """
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))
    return [
        (h.lineno, h)
        for h in _except_exception_handlers(tree)
        if not _handler_calls_reraise_guard(h)
    ]


# ---------------------------------------------------------------------------
# AST-based: verify source has the guard
# ---------------------------------------------------------------------------


class TestTranscriptSummarizerExceptBlocksHaveReraise:
    """AST check — every ``except Exception`` in transcript_summarizer.py
    must call ``reraise_on_credit_or_bug``.
    """

    @pytest.mark.xfail(reason="Regression for issue #6814 — fix not yet landed", strict=False)
    def test_all_except_exception_blocks_have_reraise_guard(self) -> None:
        filepath = SRC / "transcript_summarizer.py"
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = _unguarded_handlers(filepath)

        assert not unguarded, (
            f"transcript_summarizer.py has {len(unguarded)} ``except Exception`` "
            f"block(s) that do not call reraise_on_credit_or_bug().\n"
            f"Lines: {[lineno for lineno, _ in unguarded]}\n"
            f"Auth/credit failures are silently swallowed — see issue #6814."
        )


class TestMetricsManagerExceptBlocksHaveReraise:
    """AST check — every ``except Exception`` in metrics_manager.py
    must call ``reraise_on_credit_or_bug``.
    """

    @pytest.mark.xfail(reason="Regression for issue #6814 — fix not yet landed", strict=False)
    def test_all_except_exception_blocks_have_reraise_guard(self) -> None:
        filepath = SRC / "metrics_manager.py"
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = _unguarded_handlers(filepath)

        assert not unguarded, (
            f"metrics_manager.py has {len(unguarded)} ``except Exception`` "
            f"block(s) that do not call reraise_on_credit_or_bug().\n"
            f"Lines: {[lineno for lineno, _ in unguarded]}\n"
            f"Auth/credit failures are silently swallowed — see issue #6814."
        )


class TestKnownSitesHaveReraiseGuard:
    """Parametrised check for each specific site from the issue findings."""

    @pytest.mark.parametrize(
        ("filename", "approx_line", "desc"),
        KNOWN_UNGUARDED_SITES,
        ids=[f"{f}:{ln}" for f, ln, _ in KNOWN_UNGUARDED_SITES],
    )
    @pytest.mark.xfail(reason="Regression for issue #6814 — fix not yet landed", strict=False)
    def test_known_site_has_reraise_guard(
        self, filename: str, approx_line: int, desc: str
    ) -> None:
        filepath = SRC / filename
        assert filepath.exists()

        unguarded = _unguarded_handlers(filepath)
        nearby = [ln for ln, _ in unguarded if abs(ln - approx_line) <= 15]

        assert not nearby, (
            f"{filename}:{approx_line} ({desc}) — ``except Exception`` "
            f"near line {nearby[0]} does not call reraise_on_credit_or_bug(). "
            f"Auth/credit failures are silently swallowed (issue #6814)."
        )


# ---------------------------------------------------------------------------
# Helpers for behavioural tests
# ---------------------------------------------------------------------------


def _make_mock_runner(
    *, stdout: str = "", stderr: str = "", returncode: int = 0
) -> AsyncMock:
    """Build a mock SubprocessRunner whose run_simple returns a SimpleResult."""
    from execution import SimpleResult

    runner = AsyncMock()
    runner.run_simple = AsyncMock(
        return_value=SimpleResult(stdout=stdout, stderr=stderr, returncode=returncode)
    )
    return runner


def _make_summarizer(tmp_path: Path) -> tuple[TranscriptSummarizer, MagicMock]:
    """Build a TranscriptSummarizer with a runner that returns a valid summary.

    Returns ``(summarizer, prs_mock)``.
    """
    config = ConfigFactory.create(repo_root=tmp_path)
    prs = MagicMock()
    prs.post_comment = AsyncMock()
    bus = MagicMock()
    bus.publish = AsyncMock()
    state = MagicMock()
    runner = _make_mock_runner(stdout="### Key Decisions\n- Used factory pattern")

    summarizer = TranscriptSummarizer(config, prs, bus, state, runner=runner)
    return summarizer, prs


def _make_metrics_manager(
    tmp_path: Path,
) -> tuple[MetricsManager, MagicMock]:
    """Build a MetricsManager with mocked collaborators.

    Returns ``(mgr, prs_mock)``.
    """
    from events import EventBus
    from state import StateTracker

    config = ConfigFactory.create(repo="test-owner/test-repo", repo_root=tmp_path)
    state = StateTracker(tmp_path / "state.json")
    prs = MagicMock()
    prs.get_label_counts = AsyncMock(
        return_value={
            "open_by_label": {"hydraflow-plan": 3},
            "total_closed": 10,
            "total_merged": 8,
        }
    )
    bus = EventBus()
    mgr = MetricsManager(config, state, prs, bus)
    return mgr, prs


# ---------------------------------------------------------------------------
# Behavioural: TranscriptSummarizer.summarize_and_comment
# ---------------------------------------------------------------------------


class TestSummarizeAndCommentAuthErrorPropagates:
    """Issue #6814, finding 1 — ``_summarize_and_comment_inner`` raising
    ``AuthenticationError`` or ``CreditExhaustedError`` must propagate
    through ``summarize_and_comment``, not be swallowed by
    ``except Exception``.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6814 — fix not yet landed", strict=False)
    async def test_authentication_error_propagates(self, tmp_path: Path) -> None:
        """AuthenticationError from inner summarize must not be silently caught."""
        summarizer, prs = _make_summarizer(tmp_path)
        prs.post_comment.side_effect = AuthenticationError("bad token")

        with pytest.raises(AuthenticationError):
            await summarizer.summarize_and_comment(
                transcript="x" * 1000,
                issue_number=42,
                phase="implement",
            )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6814 — fix not yet landed", strict=False)
    async def test_credit_exhausted_error_propagates(self, tmp_path: Path) -> None:
        """CreditExhaustedError from inner summarize must not be silently caught."""
        summarizer, prs = _make_summarizer(tmp_path)
        prs.post_comment.side_effect = CreditExhaustedError("credits gone")

        with pytest.raises(CreditExhaustedError):
            await summarizer.summarize_and_comment(
                transcript="x" * 1000,
                issue_number=42,
                phase="implement",
            )


# ---------------------------------------------------------------------------
# Behavioural: MetricsManager._build_snapshot
# ---------------------------------------------------------------------------


class TestBuildSnapshotAuthErrorPropagates:
    """Issue #6814, finding 2 — ``get_label_counts`` raising
    ``AuthenticationError`` or ``CreditExhaustedError`` must propagate
    through ``_build_snapshot``, not be swallowed by
    ``except Exception``.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6814 — fix not yet landed", strict=False)
    async def test_authentication_error_propagates(self, tmp_path: Path) -> None:
        """AuthenticationError from get_label_counts must not be silently caught."""
        mgr, prs = _make_metrics_manager(tmp_path)
        prs.get_label_counts.side_effect = AuthenticationError("bad token")

        with pytest.raises(AuthenticationError):
            await mgr._build_snapshot()

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6814 — fix not yet landed", strict=False)
    async def test_credit_exhausted_error_propagates(self, tmp_path: Path) -> None:
        """CreditExhaustedError from get_label_counts must not be silently caught."""
        mgr, prs = _make_metrics_manager(tmp_path)
        prs.get_label_counts.side_effect = CreditExhaustedError("credits gone")

        with pytest.raises(CreditExhaustedError):
            await mgr._build_snapshot()
