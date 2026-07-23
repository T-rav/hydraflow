"""Regression: no-opinion shadow samples must not consume LRU budget (#9633).

``ShadowCorpus.record()`` used to persist every non-MUTATING sample, so
VOLATILE calls no registered dispatcher can ever form an opinion on
(``gh api search/issues --jq .total_count``, ``git ls-remote``) occupied
per-adapter LRU slots and evicted valuable DETERMINISTIC samples.

The fix wires a registry-derived coverage predicate
(``LiveCorpusReplayLoop.covers`` → ``gh_shape_covers`` →
``_select_shape``) onto the corpus at the composition root, gated by
``shadow_corpus_coverage_pruning_enabled`` (default True).

Pins:
- With pruning enabled, uncovered samples (no dispatcher key, ``--jq``
  transforms, unknown subcommands) are dropped at record time; covered
  shapes still persist.
- With the flag off, today's record-everything behaviour is restored.
- Coverage is derived from the loop's dispatcher registry, so chaining a
  second dispatcher under ``("github", "gh")`` must OR-compose its
  coverage into the key's single predicate (#9803 guard): a
  mutation-shaped sample survives when the composed predicate covers it.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import subprocess_util
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from contracts.shadow import ShadowCorpus
from contracts.shape_dispatchers import gh_shape_covers, gh_shape_validator
from dedup_store import DedupStore
from events import EventBus
from live_corpus_replay_loop import LiveCorpusReplayLoop

COVERED_ARGS = ["pr", "view", "42", "--json", "number,title,state"]
COVERED_STDOUT = '{"number":42,"title":"x","state":"OPEN"}\n'
UNCOVERED_JQ_ARGS = ["api", "search/issues", "--jq", ".total_count"]


@pytest.fixture(autouse=True)
def _reset_sampler() -> Generator[None, None, None]:
    """Each test starts/ends with no sampler installed."""
    subprocess_util.set_shadow_sampler(None)
    yield
    subprocess_util.set_shadow_sampler(None)


def _wire(
    tmp_path: Path, **config_overrides: object
) -> tuple[HydraFlowConfig, ShadowCorpus, LiveCorpusReplayLoop]:
    """Mirror the #9633 wiring fragment from service_registry.build_services:
    corpus + sampler install, dispatcher registration with ``covers=``, and
    the flag-gated ``set_coverage_predicate`` late binding."""
    config = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
        **config_overrides,
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)

    corpus = ShadowCorpus(
        config.data_root / "contract_shadow",
        max_per_adapter=config.shadow_corpus_max_per_adapter,
    )
    subprocess_util.set_shadow_sampler(corpus.record)

    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=4242)
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=lambda _: True,
        sleep_fn=AsyncMock(),
    )
    loop = LiveCorpusReplayLoop(
        config=config,
        corpus=corpus,
        pr_manager=pr,
        dedup=DedupStore(
            "live_corpus_replay",
            config.data_root / "dedup" / "live_corpus_replay.json",
        ),
        deps=deps,
    )
    loop.register("github", "gh", gh_shape_validator, covers=gh_shape_covers)
    if config.shadow_corpus_coverage_pruning_enabled:
        corpus.set_coverage_predicate(loop.covers)
    return config, corpus, loop


def _record(
    adapter: str, command: str, args: list[str], stdout: str = ""
) -> Path | None:
    """Drive the installed production sampler exactly as subprocess_util does."""
    sampler = subprocess_util._shadow_sampler
    assert sampler is not None
    return sampler(
        adapter=adapter,
        command=command,
        args=args,
        stdout=stdout,
        stderr="",
        exit_code=0,
    )


def test_pruning_enabled_by_default() -> None:
    """The flag defaults to True so production gets the budget win."""
    assert HydraFlowConfig().shadow_corpus_coverage_pruning_enabled is True


def test_uncovered_samples_dropped_covered_kept(tmp_path: Path) -> None:
    """With pruning on (default), no-opinion samples never hit disk."""
    config, corpus, _loop = _wire(tmp_path)

    assert _record("git", "git", ["ls-remote"], "abc123\trefs/heads/main\n") is None
    assert _record("github", "gh", UNCOVERED_JQ_ARGS, "7\n") is None
    covered_path = _record("github", "gh", COVERED_ARGS, COVERED_STDOUT)

    assert isinstance(covered_path, Path)
    assert covered_path.parent == config.data_root / "contract_shadow" / "github"
    assert corpus.list() == [covered_path]


def test_flag_off_restores_record_everything(tmp_path: Path) -> None:
    """Disabling the flag leaves the corpus without a coverage predicate."""
    _config, corpus, _loop = _wire(
        tmp_path, shadow_corpus_coverage_pruning_enabled=False
    )

    assert _record("git", "git", ["ls-remote"], "abc123\trefs/heads/main\n") is not None
    assert _record("github", "gh", UNCOVERED_JQ_ARGS, "7\n") is not None
    assert _record("github", "gh", COVERED_ARGS, COVERED_STDOUT) is not None
    assert len(corpus.list()) == 3


def test_chained_dispatcher_coverage_must_be_or_composed(tmp_path: Path) -> None:
    """#9803 guard: when a second validator is chained under
    ``("github", "gh")`` (e.g. the #8699 gh_mutation_validator), its
    args-coverage must be OR-composed into the key's single predicate —
    otherwise pruning drops the very samples the new validator needs."""
    _config, corpus, loop = _wire(tmp_path)

    def mutation_covers(args: list[str]) -> bool:
        return len(args) >= 2 and args[1] == "create"

    async def chained_validator(_sample: object) -> dict[str, object] | None:
        return None

    loop.register(
        "github",
        "gh",
        chained_validator,
        covers=lambda args: gh_shape_covers(args) or mutation_covers(args),
    )

    mutation_path = _record(
        "github",
        "gh",
        ["issue", "create", "--title", "x"],
        "https://github.com/x/y/issues/1\n",
    )
    assert mutation_path is not None
    assert _record("github", "gh", COVERED_ARGS, COVERED_STDOUT) is not None
    assert _record("github", "gh", UNCOVERED_JQ_ARGS, "7\n") is None
