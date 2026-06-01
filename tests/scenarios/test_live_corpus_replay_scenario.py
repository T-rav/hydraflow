"""MockWorld scenario for ``LiveCorpusReplayLoop`` (Phase 2 of #8786).

Pattern B per docs/standards/testing/README.md — drive the real loop with
a real ``ShadowCorpus`` and a mocked PRManager. Asserts the end-to-end
drift signal reaches the ``hydraflow-find`` queue without human routing.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from contracts.shadow import ShadowCorpus
from dedup_store import DedupStore
from events import EventBus
from live_corpus_replay_loop import LiveCorpusReplayLoop
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


class TestLiveCorpusReplayScenario:
    async def test_drift_reaches_hydraflow_find_queue(self, tmp_path: Path) -> None:
        """End-to-end: a shadow sample diverging from the fake fires a
        ``hydraflow-find`` + ``shadow-drift`` issue via PRManager.create_issue.
        No HITL label, no human in the loop."""
        world = MockWorld(tmp_path)
        config = HydraFlowConfig(
            data_root=tmp_path / "data",
            repo_root=tmp_path / "repo",
            repo="hydra/hydraflow",
        )
        (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
        corpus = ShadowCorpus(config.data_root / "contract_shadow")
        corpus.record(
            adapter="github",
            command="gh",
            args=["pr", "view", "42", "--json", "state,mergeable"],
            stdout=json.dumps({"state": "MERGED", "mergeable": "MERGEABLE"}) + "\n",
            stderr="",
            exit_code=0,
        )
        dedup = DedupStore(
            "live_corpus_replay",
            config.data_root / "dedup" / "live_corpus_replay.json",
        )
        stop = asyncio.Event()
        deps = LoopDeps(
            event_bus=EventBus(),
            stop_event=stop,
            status_cb=MagicMock(),
            enabled_cb=lambda _: True,
            sleep_fn=AsyncMock(),
        )
        loop = LiveCorpusReplayLoop(
            config=config,
            corpus=corpus,
            pr_manager=world.github,
            dedup=dedup,
            deps=deps,
        )

        # A stale fake — claims OPEN while the live sample shows MERGED.
        async def stale_fake_gh(_sample):  # noqa: ANN001
            return {"state": "OPEN", "mergeable": "MERGEABLE"}

        loop.register("github", "gh", stale_fake_gh)

        result = await loop._do_work()

        assert result["drifted"] == 1
        assert result["filed_issue"] == 9001
        issue = world.github.issue(9001)
        labels = issue.labels
        assert "hydraflow-find" in labels
        assert "shadow-drift" in labels
        # Critically: the issue must NOT carry hitl-escalation or
        # human-required labels — the v2 path is auto-agent routing only,
        # human escalation only on N-attempt exhaustion (Phase 3).
        assert "hitl-escalation" not in labels
        assert "human-required" not in labels
