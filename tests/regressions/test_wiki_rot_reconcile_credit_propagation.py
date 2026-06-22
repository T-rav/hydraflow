"""Regression #9442: _reconcile_closed_escalations must not swallow CreditExhaustedError.

Before this fix, wiki_rot_detector._reconcile_closed_escalations called
PRPort.list_closed_issues_by_label via a raw ``asyncio.create_subprocess_exec``
(bypassing PRPort entirely).  The refactor replaced the subprocess with a proper
PRPort call wrapped in ``except Exception: reraise_on_credit_or_bug(exc)``.

This test guards the re-raise contract: a billing signal from the port must
propagate out of reconcile so the supervised loop can pause — it must not be
folded into the generic "gh list failed" log-and-return path.

Pattern mirrors ``test_sentry_loop_credit_propagation.py`` and
``test_pr_unsticker_credit_exhaustion.py``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from subprocess_util import CreditExhaustedError
from wiki_rot_detector_loop import WikiRotDetectorLoop


def _make_loop(tmp_path: Path) -> WikiRotDetectorLoop:
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    pr_manager = AsyncMock()
    dedup = MagicMock()
    dedup.get.return_value = set()
    wiki_store = MagicMock()
    wiki_store.list_repos.return_value = []
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )
    return WikiRotDetectorLoop(
        config=cfg,
        state=state,
        pr_manager=pr_manager,
        dedup=dedup,
        wiki_store=wiki_store,
        deps=deps,
    )


@pytest.mark.asyncio
async def test_reconcile_reraises_credit_exhausted_not_swallowed(
    tmp_path: Path,
) -> None:
    """CreditExhaustedError from PRPort must escape _reconcile_closed_escalations.

    The broad ``except Exception`` in reconcile calls
    ``reraise_on_credit_or_bug`` before logging — so a billing signal must
    propagate, not be silently eaten.
    """
    loop = _make_loop(tmp_path)
    loop._pr.list_closed_issues_by_label = AsyncMock(  # type: ignore[attr-defined]
        side_effect=CreditExhaustedError("exhausted", resume_at=None)
    )

    with pytest.raises(CreditExhaustedError):
        await loop._reconcile_closed_escalations()
