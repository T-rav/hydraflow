"""Regression test for issue #6814.

Bug: ``transcript_summarizer.py`` and ``metrics_manager.py`` both use
``except Exception:`` without calling ``reraise_on_credit_or_bug()``.
This silently swallows ``AuthenticationError`` and
``CreditExhaustedError``, preventing the orchestrator's credit-pause
mechanism from learning about exhaustion from these paths.

Affected sites:
- ``src/transcript_summarizer.py`` — ``summarize_and_comment()``
- ``src/metrics_manager.py`` — ``_build_snapshot()``

Expected behaviour after fix:
  - ``AuthenticationError`` and ``CreditExhaustedError`` propagate up
    from both sites so the orchestrator's credit-pause / auth-retry
    logic can handle them.

Anchored on the METHOD, not on a line number (#11664)
-----------------------------------------------------

The per-site assertion below used to filter whole-file handler line numbers to
a ±15-line window around ``transcript_summarizer.py:198`` /
``metrics_manager.py:211``. Both methods had long since drifted off those
windows (``summarize_and_comment`` now starts near line 189,
``_build_snapshot`` near 162), so the filter matched an EMPTY set and
``assert not []`` passed VACUOUSLY.

The anchors are now enclosing method names, resolved through
``tests.regressions._handler_anchors.unguarded_handlers``, which RAISES if the
method disappears — a rotted anchor fails loudly instead of passing for free.
See ``_handler_anchors`` for the full rationale.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from metrics_manager import MetricsManager
from subprocess_util import AuthenticationError, CreditExhaustedError
from tests.helpers import ConfigFactory
from tests.regressions._handler_anchors import (
    RERAISE_GUARD,
    SRC,
    _except_exception_handlers,
    _handler_calls_reraise_guard,
    unguarded_handlers,
)
from transcript_summarizer import TranscriptSummarizer

REQUIRED_GUARD = RERAISE_GUARD

#: (file, enclosing method, short description) from the issue findings.
KNOWN_UNGUARDED_SITES: list[tuple[str, str, str]] = [
    (
        "transcript_summarizer.py",
        "summarize_and_comment",
        "summarize_and_comment except Exception handler",
    ),
    (
        "metrics_manager.py",
        "_build_snapshot",
        "_build_snapshot get_label_counts except Exception handler",
    ),
]


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _unguarded_handlers_in_file(
    filepath: Path,
) -> list[tuple[int, ast.ExceptHandler]]:
    """Whole-file variant used by the two file-wide sweeps below.

    The per-site tests use the method-scoped
    :func:`~tests.regressions._handler_anchors.unguarded_handlers` instead.
    """
    tree = ast.parse(filepath.read_text(), filename=str(filepath))
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

    def test_all_except_exception_blocks_have_reraise_guard(self) -> None:
        filepath = SRC / "transcript_summarizer.py"
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = _unguarded_handlers_in_file(filepath)

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

    def test_all_except_exception_blocks_have_reraise_guard(self) -> None:
        filepath = SRC / "metrics_manager.py"
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = _unguarded_handlers_in_file(filepath)

        assert not unguarded, (
            f"metrics_manager.py has {len(unguarded)} ``except Exception`` "
            f"block(s) that do not call reraise_on_credit_or_bug().\n"
            f"Lines: {[lineno for lineno, _ in unguarded]}\n"
            f"Auth/credit failures are silently swallowed — see issue #6814."
        )


class TestKnownSitesHaveReraiseGuard:
    """Parametrised check for each specific site from the issue findings."""

    @pytest.mark.parametrize(
        ("filename", "method", "desc"),
        KNOWN_UNGUARDED_SITES,
        ids=[f"{f}:{m}" for f, m, _ in KNOWN_UNGUARDED_SITES],
    )
    def test_known_site_has_reraise_guard(
        self, filename: str, method: str, desc: str
    ) -> None:
        """``unguarded_handlers`` raises if *method* is gone, so this can never
        pass by matching nothing.
        """
        filepath = SRC / filename
        assert filepath.exists()

        unguarded = [ln for ln, _ in unguarded_handlers(filepath, method)]

        assert not unguarded, (
            f"{filename}:{method}() ({desc}) — ``except Exception`` at line "
            f"{unguarded[0]} does not call reraise_on_credit_or_bug(). "
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
    async def test_authentication_error_propagates(self, tmp_path: Path) -> None:
        """AuthenticationError from get_label_counts must not be silently caught."""
        mgr, prs = _make_metrics_manager(tmp_path)
        prs.get_label_counts.side_effect = AuthenticationError("bad token")

        with pytest.raises(AuthenticationError):
            await mgr._build_snapshot()

    @pytest.mark.asyncio
    async def test_credit_exhausted_error_propagates(self, tmp_path: Path) -> None:
        """CreditExhaustedError from get_label_counts must not be silently caught."""
        mgr, prs = _make_metrics_manager(tmp_path)
        prs.get_label_counts.side_effect = CreditExhaustedError("credits gone")

        with pytest.raises(CreditExhaustedError):
            await mgr._build_snapshot()
