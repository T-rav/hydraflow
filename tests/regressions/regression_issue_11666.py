"""Regression: the transcript-summary chain must not swallow credit exhaustion.

Found by running the repaired credit-reraise audit (#11666) across ALL of
``src/`` rather than only the loop layer. Until then the audit resolved its
spawn-reachability call graph one FILE at a time and only ever looked at
``src/*_loop.py``, so this chain sat in a double blind spot: not a loop, and
split across six modules.

The chain, innermost first:

1. ``TranscriptSummarizer.summarize_and_comment`` wrapped its whole body in
   ``except Exception`` and returned ``False`` — its docstring promised "never
   raises". It summarizes by SPAWNING AN LLM, so ``CreditExhaustedError`` from
   that spawn was reported to callers as an ordinary "summary failed".
2. All five callers then re-swallowed on top:
   ``plan_phase_disposition`` (x2, via ``except (RuntimeError, OSError)`` —
   ``CreditExhaustedError`` subclasses ``RuntimeError``), ``review_phase`` and
   ``implement_phase`` (x2, via ``log_exception_with_bug_classification``,
   which logs and returns).

Fixing only site 1 would have been COSMETIC: the error would have escaped the
summarizer and died one frame up. The whole chain had to reraise for the signal
to reach ``BaseBackgroundLoop``'s pause handler, which is the point of the
house rule (``docs/wiki/dark-factory.md`` §2.2).

The structural gate lives in ``tests/test_loop_credit_reraise_completeness.py``
(``test_no_src_module_swallows_credit_in_a_broad_except``). These tests pin the
BEHAVIOUR at the innermost site, where it is observable end-to-end.

Refs #11664, Refs #11666, Refs #6855.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from subprocess_util import AuthenticationError, CreditExhaustedError
from tests.helpers import ConfigFactory
from transcript_summarizer import TranscriptSummarizer

if TYPE_CHECKING:
    from pathlib import Path


def _make_summarizer(tmp_path: Path) -> TranscriptSummarizer:
    """A TranscriptSummarizer with every collaborator stubbed."""
    config = ConfigFactory.create(repo_root=tmp_path)
    prs = MagicMock()
    prs.post_comment = AsyncMock()
    bus = MagicMock()
    bus.publish = AsyncMock()
    state = MagicMock()
    return TranscriptSummarizer(config, prs, bus, state, runner=MagicMock())


async def _call(summarizer: TranscriptSummarizer) -> bool:
    return await summarizer.summarize_and_comment(
        transcript="some transcript",
        issue_number=42,
        phase="review",
    )


class TestSummarizeAndCommentPropagatesFatalErrors:
    """Credit/auth exhaustion must escape, not become ``return False``."""

    @pytest.mark.asyncio()
    @pytest.mark.parametrize(
        "fatal_cls",
        [AuthenticationError, CreditExhaustedError],
        ids=["auth", "credit"],
    )
    async def test_fatal_error_propagates(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fatal_cls: type[Exception],
    ) -> None:
        summarizer = _make_summarizer(tmp_path)
        monkeypatch.setattr(
            summarizer,
            "_summarize_and_comment_inner",
            AsyncMock(side_effect=fatal_cls("spawn hit an exhausted account")),
        )

        with pytest.raises(fatal_cls):
            await _call(summarizer)

    @pytest.mark.asyncio()
    async def test_ordinary_failure_is_still_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Negative control — posting a summary stays best-effort.

        Without this, a handler that re-raised everything would satisfy the
        tests above while turning any transient comment-posting failure into a
        phase failure. ``ConnectionError`` is neither infra-fatal nor a
        likely-bug type, so it must still be absorbed as ``False``.
        """
        summarizer = _make_summarizer(tmp_path)
        monkeypatch.setattr(
            summarizer,
            "_summarize_and_comment_inner",
            AsyncMock(side_effect=ConnectionError("github flaked")),
        )

        assert await _call(summarizer) is False
