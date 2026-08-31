"""Regression: one wiki-compile prompt never scales with total topic size.

`_compile_topic` put EVERY entry of a topic into a single prompt, and compile
is the ONLY path that compacts a topic. `docs/wiki/patterns.md` grew 28KB ->
83KB and the call stopped fitting in its 300s timeout — so the one mechanism
that could shrink the topic became impossible exactly when it was needed.

That is a one-way door, not a slow model: once a topic outgrows one call it can
never be compacted again, and it only grows. Measured 2026-08-30: 71
consecutive timeouts, roughly six hours of model calls producing nothing, while
the factory reported healthy because the failure was a swallowed WARNING.

Batching by CHARACTERS rather than entry count is the load-bearing part. Entries
range from one line to several paragraphs, so a fixed entry count still lets one
prompt grow without bound — which is the defect, not a symptom of it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from repo_wiki import WikiEntry
from wiki_compiler import WikiCompiler

BUDGET = 20_000


def _compiler(budget: int = BUDGET) -> WikiCompiler:
    config = MagicMock()
    config.wiki_compilation_batch_chars = budget
    config.wiki_compilation_breaker_failures = 3
    config.wiki_compilation_breaker_reset_seconds = 1800
    compiler = WikiCompiler.__new__(WikiCompiler)
    compiler._config = config
    return compiler


def _entries(count: int, size: int) -> list[WikiEntry]:
    return [
        WikiEntry(
            id=f"id{i}",
            title=f"title-{i}",
            content="x" * size,
            source_issue=1,
            source_type="pr",
            created_at="2026-01-01",
        )
        for i in range(count)
    ]


def test_the_real_patterns_topic_shape_fits_in_bounded_prompts() -> None:
    """50 entries at ~1.6KB is `patterns.md` as measured when it stopped."""
    compiler = _compiler()
    batches = compiler._batch_entries(_entries(50, 1600))

    sizes = [sum(len(compiler._entry_block(e)) for e in b) for b in batches]
    assert max(sizes) <= BUDGET, (
        f"largest prompt is {max(sizes)} chars against a {BUDGET} budget; "
        "the 83,000-char prompt that timed out is back"
    )
    assert len(batches) > 1, "a topic this size must actually be split"


def test_no_entry_is_lost_to_batching() -> None:
    """Silently dropping wiki content would be worse than not compiling."""
    compiler = _compiler()
    entries = _entries(50, 1600)

    batched = [e for batch in compiler._batch_entries(entries) for e in batch]

    assert [e.id for e in batched] == [e.id for e in entries]


def test_an_entry_larger_than_the_whole_budget_still_gets_through() -> None:
    """It gets a batch of its own rather than being dropped or truncated.

    If that single call times out the circuit breaker bounds the cost — but
    losing the entry would be a silent data loss no retry could repair.
    """
    compiler = _compiler()

    batches = compiler._batch_entries(_entries(1, BUDGET * 3))

    assert len(batches) == 1
    assert len(batches[0]) == 1


def test_batching_is_by_characters_not_entry_count() -> None:
    """The load-bearing distinction, asserted directly.

    Ten small entries fit one prompt; ten large ones must not. A count-based
    split would put both in the same number of batches and reintroduce the
    unbounded prompt.
    """
    compiler = _compiler()

    small = compiler._batch_entries(_entries(10, 100))
    large = compiler._batch_entries(_entries(10, 8_000))

    assert len(small) == 1
    assert len(large) > 1, (
        "ten large entries landed in one prompt — batching is counting "
        "entries, not measuring them"
    )


def test_a_small_topic_is_not_split() -> None:
    """Anti-vacuity: batching everything into singletons would satisfy every
    bound above while making compile useless — it could never dedupe two
    entries against each other."""
    compiler = _compiler()

    assert len(compiler._batch_entries(_entries(5, 100))) == 1
