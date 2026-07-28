"""Regression for issue #10768.

A scan of ``repo_wiki/**/*.md`` for backticked snake_case tokens found ~52
identifiers absent from the code surface (``src`` / ``scripts`` / ``tests``).
Triage showed the set is a MIX: some name config fields / functions from plans
that never merged, but roughly half are ordinary prose that merely *looks*
like an identifier — ``cancel_fn``, ``resume_fn``, ``abandoned_at``,
``bank_order``, ``setup_method``, ``teardown_method``, ``last_poll_ts``.

If Style-D (#10762) flagged every such token it would file dozens of
false-positive rot findings. Precision comes from the imperative-position
gate: a bare backticked snake_case token is only a runnable-tool cite when an
imperative verb (``run`` / ``invoke`` / ``execute``) directly governs it.
Against the live corpus that gate flags exactly one token — the genuine dead
tool ``wiki_lesson_coverage`` — and suppresses the prose look-alikes.

These tests pin that precision decision so a future widening of Style-D
cannot silently reintroduce the false-positive flood.
"""

from __future__ import annotations

from wiki_rot_citations import extract_cites

# Prose tokens surfaced by the raw scan that are NOT runnable-tool cites — they
# appear in ordinary sentences (callback names, field names, pytest hooks,
# illustrative pseudo-code), never after "run"/"invoke"/"execute".
_PROSE_LOOKALIKES = [
    "The `cancel_fn` and `resume_fn` callbacks decouple components.",
    "Record `abandoned_at` on the sidecar row when a run is dropped.",
    "Sort by `bank_order` to keep multi-location writes consistent.",
    "Reset module state in both `setup_method` and `teardown_method`.",
    "The `last_poll_ts` scalar is an immutable value in shared state.",
    "A `score_rule` weight drives the ranking heuristic.",
    "Fields `retain_safe` / `recall_safe` gate the never-raise contract.",
]


def _bare(text: str) -> set[str]:
    return {c.symbol for c in extract_cites(text) if c.style == "bare"}


def test_prose_lookalikes_are_not_flagged_as_bare_cites() -> None:
    for sentence in _PROSE_LOOKALIKES:
        assert _bare(sentence) == set(), sentence


def test_running_a_different_noun_does_not_capture_a_following_token() -> None:
    # The loose failure mode: "`StagingPromotionLoop` running concurrently
    # (e.g. `s82_post_merge_full_machine`)" — the verb governs a DIFFERENT
    # noun, and the scenario token is only an illustrative "e.g." mention.
    text = (
        "with `StagingPromotionLoop` running concurrently "
        "(e.g. `s82_post_merge_full_machine`)."
    )
    assert _bare(text) == set()


def test_genuine_imperative_tool_cite_is_still_flagged() -> None:
    # Precision must not become "flag nothing": the real dead-tool cite still
    # surfaces so #10754-shape rot is caught going forward.
    text = "Run `wiki_lesson_coverage` before assuming the merge preserved content."
    assert _bare(text) == {"wiki_lesson_coverage"}
