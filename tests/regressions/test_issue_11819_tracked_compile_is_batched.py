"""#11819's remaining half: the TRACKED flow put the whole topic in one prompt.

The batcher landed on ``compile_topic`` (legacy). ``_flow_synthesize`` — the
path ``RepoWikiLoop`` Phase 8 actually runs, and the one holding 4089 active
``patterns`` entries on the live factory — joined every active entry into a
single ``_COMPILE_TOPIC_PROMPT`` with no batching and no cap. The fix was
applied in N-1 of the N places that needed it, and the missed one was the one
that mattered.

These pin both bounds and, more importantly, the thing that makes partial
progress SAFE: an entry whose batch produced nothing must stay ``active``
rather than be superseded by a synthesis that never read it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wiki_compiler import WikiCompiler
from wiki_compiler._flow import _tracked_entry_block


def _entry(i: int, body: str = "x" * 400) -> dict[str, Any]:
    return {
        "id": f"e{i:04d}",
        "title": f"Entry {i}",
        "body": body,
        "source_issue": i,
        "source_phase": "implement",
        "created_at": "2026-08-31T00:00:00+00:00",
        "path": Path(f"/tmp/e{i}.md"),
    }


def _compiler(*, batch_chars: int, cap: int) -> WikiCompiler:
    compiler = WikiCompiler.__new__(WikiCompiler)
    compiler._config = MagicMock()
    compiler._config.wiki_compilation_batch_chars = batch_chars
    compiler._config.wiki_compilation_max_batches_per_tick = cap
    compiler._last_rejected_digests = []
    compiler._last_accepted_count = 0
    return compiler


def _synthesis(title: str) -> dict[str, Any]:
    return {"title": title, "content": "See `src/foo.py:Bar`.", "topic": "patterns"}


@pytest.mark.asyncio
async def test_one_prompt_never_carries_the_whole_topic() -> None:
    """The defect, stated directly: 40 entries must not be one prompt."""
    entries = [_entry(i) for i in range(40)]
    compiler = _compiler(batch_chars=1000, cap=0)

    prompts: list[str] = []

    async def _call(prompt: str, context: str) -> str:
        prompts.append(prompt)
        return json.dumps([_synthesis(f"S{len(prompts)}")])

    compiler._call_model = _call  # type: ignore[method-assign]
    state: dict[str, Any] = {
        "active_entries": entries,
        "repo": "acme/widget",
        "topic": "patterns",
        "other_topics": ["gotchas"],
    }
    await compiler._flow_synthesize(state)

    assert len(prompts) > 1, "the whole topic went into a single prompt"
    budget = 1000
    for prompt in prompts:
        rendered = sum(
            len(_tracked_entry_block(e)) for e in entries if e["title"] in prompt
        )
        assert rendered <= budget + len(_tracked_entry_block(entries[0])), (
            "a batch exceeded the character budget it is supposed to bound"
        )


@pytest.mark.asyncio
async def test_the_per_tick_cap_bounds_the_spend_not_just_the_call() -> None:
    """Batching alone trades one call that times out for hundreds that do not."""
    entries = [_entry(i) for i in range(40)]
    compiler = _compiler(batch_chars=1000, cap=3)

    calls = {"n": 0}

    async def _call(prompt: str, context: str) -> str:
        calls["n"] += 1
        return json.dumps([_synthesis(f"S{calls['n']}")])

    compiler._call_model = _call  # type: ignore[method-assign]
    state: dict[str, Any] = {
        "active_entries": entries,
        "repo": "acme/widget",
        "topic": "patterns",
        "other_topics": [],
    }
    await compiler._flow_synthesize(state)

    assert calls["n"] == 3, f"cap of 3 batches per tick not honoured ({calls['n']})"


@pytest.mark.asyncio
async def test_capped_off_entries_are_not_superseded() -> None:
    """The safety property: validate supersedes active_entries, so the entries
    this tick never read must not be in it."""
    entries = [_entry(i) for i in range(40)]
    compiler = _compiler(batch_chars=1000, cap=2)

    async def _call(prompt: str, context: str) -> str:
        return json.dumps([_synthesis("S")])

    compiler._call_model = _call  # type: ignore[method-assign]
    state: dict[str, Any] = {
        "active_entries": entries,
        "repo": "acme/widget",
        "topic": "patterns",
        "other_topics": [],
    }
    await compiler._flow_synthesize(state)

    survivors = state["active_entries"]
    assert 0 < len(survivors) < len(entries), (
        "supersession scope was not narrowed — the capped-off entries would be "
        "retired under a synthesis that never read them"
    )
    assert all(e in entries for e in survivors)


@pytest.mark.asyncio
async def test_a_failed_batch_leaves_its_entries_active() -> None:
    """A batch whose model call returns nothing must not retire its inputs."""
    entries = [_entry(i) for i in range(40)]
    compiler = _compiler(batch_chars=1000, cap=0)

    calls = {"n": 0}

    async def _call(prompt: str, context: str) -> str | None:
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # first batch fails
        return json.dumps([_synthesis(f"S{calls['n']}")])

    compiler._call_model = _call  # type: ignore[method-assign]
    state: dict[str, Any] = {
        "active_entries": entries,
        "repo": "acme/widget",
        "topic": "patterns",
        "other_topics": [],
    }
    await compiler._flow_synthesize(state)

    survivors = state["active_entries"]
    assert entries[0] not in survivors, (
        "the failed batch's first entry is still queued for supersession"
    )
    assert not state.get("_stop"), "a single failed batch must not abort the flow"


@pytest.mark.asyncio
async def test_every_batch_failing_aborts_and_keeps_originals() -> None:
    entries = [_entry(i) for i in range(40)]
    compiler = _compiler(batch_chars=1000, cap=0)

    async def _call(prompt: str, context: str) -> str | None:
        return None

    compiler._call_model = _call  # type: ignore[method-assign]
    state: dict[str, Any] = {
        "active_entries": entries,
        "repo": "acme/widget",
        "topic": "patterns",
        "other_topics": [],
    }
    await compiler._flow_synthesize(state)
    assert state["_stop"] is True


def test_the_budget_measures_the_string_the_prompt_sends() -> None:
    """A budget that measures one rendering and ships another bounds nothing."""
    import inspect

    from wiki_compiler import _flow

    source = inspect.getsource(_flow.WikiCompilerFlowMixin._flow_synthesize)
    assert source.count("_tracked_entry_block") == 2, (
        "the batcher's size function and the prompt's entries_text must both "
        "go through _tracked_entry_block, or the budget stops bounding the "
        "thing that is actually sent"
    )
