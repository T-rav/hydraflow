"""Regression: SentryLoop must surface credit-exhaustion (M-1).

The per-issue loop inside ``SentryLoop._do_work`` wraps the
``await self._process_issue(...)`` call in a broad ``except Exception`` that
logs "Sentry issue processing failed — skipping" and continues. The inner
LLM spawn re-raises ``CreditExhaustedError`` (a ``RuntimeError`` subclass),
but it was re-swallowed here — so the supervised loop never paused on a
billing signal and kept burning attempt budget against an exhausted account.

Expected behaviour after the fix:
  - ``_do_work`` re-raises a per-issue ``CreditExhaustedError`` (via
    ``reraise_on_credit_or_bug``) instead of folding it into
    ``issues_skipped`` and returning a normal dict, so the outer loop can pause.

Mirrors ``tests/test_term_proposer_loop.py::TestTermProposerLoopCreditPropagation``
and the sibling ``test_pr_unsticker_credit_exhaustion.py`` boundary test.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from subprocess_util import CreditExhaustedError
from tests.test_sentry_loop import _make_deps, _make_loop, _make_sentry_issue


@pytest.mark.asyncio
async def test_credit_exhausted_propagates_from_do_work(tmp_path: Path) -> None:
    """A CreditExhaustedError from _process_issue must propagate out of
    _do_work, not be swallowed by the per-issue except + counted as skipped."""
    from tests.helpers import ConfigFactory

    config = ConfigFactory.create(repo_root=tmp_path)
    deps = _make_deps()
    prs = MagicMock()

    loop = _make_loop(config, prs, deps)

    sentry_issue = _make_sentry_issue()
    with (
        patch.object(loop, "_list_projects", return_value=[{"slug": "myproject"}]),
        patch.object(loop, "_fetch_unresolved", return_value=[sentry_issue]),
        patch.object(
            loop,
            "_process_issue",
            new_callable=AsyncMock,
            side_effect=CreditExhaustedError("usage limit reached", resume_at=None),
        ),
        pytest.raises(CreditExhaustedError, match="usage limit reached"),
    ):
        await loop._do_work()
