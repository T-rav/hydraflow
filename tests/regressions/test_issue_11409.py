"""Regression test for #11409.

The sampled re-audit of #11375 (upheld) named a missing MockWorld scenario
layer for the #11373 wiki fingerprint gate as the escape — since fixed by
#11416 (wiring) and #11432 (the multi-tick scenario itself,
``tests/scenarios/test_repo_wiki_compile_scenario.py``).

Building that scenario surfaced a second, narrower defect this test pins:
``FakeWikiCompiler.compile_topic_tracked`` (src/mockworld/fakes/fake_wiki_compiler.py)
never declared the real ``WikiCompiler.compile_topic_tracked``'s
(src/wiki_compiler.py:658) ``other_topics`` parameter at all. Any caller
passing it — positionally or by keyword — gets a bare ``TypeError``, which
is in ``LIKELY_BUG_EXCEPTIONS`` and aborts the whole ``RepoWikiLoop`` tick
via ``reraise_on_credit_or_bug`` (src/repo_wiki_loop.py:441) rather than
degrading gracefully.

The real method keeps ``other_topics`` keyword-only (``*, other_topics=None``).
The Fake must not be *more* restrictive than that: declared
positional-or-keyword on the Fake stays a safe superset of every call shape
the real compiler accepts, matching the general Port/Fake conformance rule
in ``tests/test_mockworld_fakes_conformance.py``.
"""

from __future__ import annotations

import inspect

from mockworld.fakes.fake_wiki_compiler import FakeWikiCompiler
from wiki_compiler import WikiCompiler


def test_fake_compile_topic_tracked_declares_other_topics_param() -> None:
    real_sig = inspect.signature(WikiCompiler.compile_topic_tracked)
    fake_sig = inspect.signature(FakeWikiCompiler.compile_topic_tracked)

    assert "other_topics" in real_sig.parameters
    assert "other_topics" in fake_sig.parameters, (
        "FakeWikiCompiler.compile_topic_tracked is missing the real "
        "WikiCompiler's other_topics param — any caller passing it raises "
        "TypeError, which aborts the whole RepoWikiLoop tick"
    )


def test_fake_compile_topic_tracked_other_topics_not_more_restrictive_than_real() -> (
    None
):
    real_kind = (
        inspect.signature(WikiCompiler.compile_topic_tracked)
        .parameters["other_topics"]
        .kind
    )
    fake_kind = (
        inspect.signature(FakeWikiCompiler.compile_topic_tracked)
        .parameters["other_topics"]
        .kind
    )

    assert real_kind is inspect.Parameter.KEYWORD_ONLY
    assert fake_kind is inspect.Parameter.POSITIONAL_OR_KEYWORD, (
        "FakeWikiCompiler must not mark other_topics KEYWORD_ONLY like the "
        "real compiler does — the Fake should stay at least as permissive "
        "as the reference so no valid call shape crashes the tick"
    )


async def test_fake_compile_topic_tracked_accepts_other_topics_kwarg(
    tmp_path,
) -> None:
    fake = FakeWikiCompiler()

    count = await fake.compile_topic_tracked(
        tmp_path, "o/r", "patterns", other_topics=["gotchas"]
    )

    assert count == fake.compiled_entries_per_call
