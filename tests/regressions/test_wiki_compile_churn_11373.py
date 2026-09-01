"""Regression pin for #11373: unchanged wiki topics never re-pay synthesis.

Live measurement: wiki_compilation burned 1.66M tokens / 132 spawns in 12h
(23% of ALL factory tokens) re-compiling topics whose content had not
changed — topics pinned over the 5-entry threshold by uncompilable entries
respawned every tick. The fingerprint gate makes the second tick free.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repo_wiki import RepoWikiStore, WikiEntry
from repo_wiki_loop import RepoWikiLoop
from tests.helpers import wiki_compiler_mock, config_mock


def _config(tmp_path: Path) -> MagicMock:
    config = config_mock()
    config.repo_wiki_interval = 3600
    config.repo_wiki_git_backed = False
    config.wiki_anchor_prune_enabled = False
    # A real number, not a MagicMock: every numeric knob the loop compares
    # is a latent crash otherwise (a bare Mock RAISES on comparison).
    # 0 = 'every topic has work', which DISABLES the #11898 compaction
    # pre-check. Deliberate: these tests' subject is a different gate,
    # and a test for gate A must not be silently short-circuited by
    # gate B — that would leave it green while testing nothing.
    config.wiki_compaction_similarity_threshold = 0.0
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    config.data_path = data_dir.joinpath
    return config


def _deps() -> MagicMock:
    deps = MagicMock()
    deps.event_bus = None
    return deps


def _seed(store: RepoWikiStore) -> None:
    store.ingest(
        "org/repo",
        [
            WikiEntry(
                title=f"Module layer {i}",
                content=f"Architecture detail {i} about service layers.",
                source_type="plan",
                source_issue=i,
            )
            for i in range(5)
        ],
    )


@pytest.mark.asyncio
async def test_unchanged_topic_compiles_once_across_ticks(tmp_path: Path) -> None:
    store = RepoWikiStore(tmp_path / "wiki")
    _seed(store)
    # Same count back, so the topic stays at 5 entries (over threshold) — the
    # pre-gate behavior would recompile every tick.
    compiler = wiki_compiler_mock(compile_topic=5, accepted=5)
    loop = RepoWikiLoop(
        config=_config(tmp_path),
        wiki_store=store,
        deps=_deps(),
        wiki_compiler=compiler,
    )
    await loop._lint_and_compile_repos(["org/repo"], None, set(), store=store)
    await loop._lint_and_compile_repos(["org/repo"], None, set(), store=store)
    compiler.compile_topic.assert_called_once()


@pytest.mark.asyncio
async def test_changed_topic_recompiles(tmp_path: Path) -> None:
    store = RepoWikiStore(tmp_path / "wiki")
    _seed(store)
    compiler = wiki_compiler_mock(compile_topic=5, accepted=5)
    loop = RepoWikiLoop(
        config=_config(tmp_path),
        wiki_store=store,
        deps=_deps(),
        wiki_compiler=compiler,
    )
    await loop._lint_and_compile_repos(["org/repo"], None, set(), store=store)
    store.ingest(
        "org/repo",
        [
            WikiEntry(
                title="Fresh insight",
                content="A new architecture note about the event bus.",
                source_type="plan",
                source_issue=99,
            )
        ],
    )
    await loop._lint_and_compile_repos(["org/repo"], None, set(), store=store)
    assert compiler.compile_topic.call_count == 2
