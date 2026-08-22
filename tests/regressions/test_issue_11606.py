"""Regression #11606: corroboration candidates are ranked, not positional.

A wiki-ingest for issue #11518 (a GitHub Actions cache-poisoning fix) bumped
``corroborations: 2 → 3`` on ``testing/2609-issue-11176-escape-ledger-max-
diagnoses-per-tick-must-be-test-.md`` — an entry about per-tick I/O budgets in
``escape_ledger_loop.py`` that PR #11560 never touched. Two defects in the
candidate pipeline combined to produce it:

1. ``RepoWikiStore._load_tracked_topic_entries_with_paths`` coerced
   ``source_issue`` with a bare ``int()``. The compiler stamps the literal
   ``source_issue: synthesis`` on every entry it writes, so the coercion
   raised and dropped the entry entirely — 441 of 1,122 active entries (39%)
   on the live wiki, including every entry in ``dependencies`` and 146 of 160
   in ``patterns``.

2. Both ingest paths then sliced ``[:5]`` off what survived, in filename
   order. The candidate set was therefore a fixed positional window that had
   nothing to do with the entry being ingested: across the 681 loadable
   active entries in the live wiki, **every corroboration on record sat at
   index 0-4, and not one of the 661 entries beyond the window had ever been
   corroborated**. Entry 2609 sat at index 3 only because 179 dropped
   synthesis entries had shifted the window onto it, and it scored 0.011
   against the incoming entry — 241st of 325 — while the genuine match
   (``2770``, the sibling CodeQL cache-poisoning entry) scored 0.187 and was
   invisible to the window.

Pins: synthesis-provenance entries are loadable candidates, and ranking puts
topical similarity ahead of filename order with a floor that keeps unrelated
entries away from the LLM's same-principle judgement.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from repo_wiki import RepoWikiStore, WikiEntry
from wiki_corroboration_rank import (
    MIN_CANDIDATE_SIMILARITY,
    candidate_similarity,
    rank_corroboration_candidates,
)

# Verbatim titles + bodies from the escape, so the pin fails if the ranker
# ever regresses to putting 2609 in front of a cache-poisoning entry again.
_INGESTED_TITLE = "CodeQL cache-poisoning defense: literal-ref + in-job SHA assertion"
_INGESTED_BODY = (
    "In workflow jobs with expression-ref checkouts and output SHA pinning, use a "
    "literal ref for the cache-key source (e.g., `ref: staging`) and assert the SHA "
    "inside the job before using it in privileged operations. Document the boundary "
    "with TRUST comments.\n\nExample: `scripts/staging_rc_dryrun_pin.py` and "
    "`.github/workflows/staging-rc-dryrun.yml` checkout `ref: staging` for cache, "
    "assert SHA in-job before downstream use.\n\n**Why:** Expression-ref checkout "
    "with cache keys derived from the checked-out SHA enables cache-poisoning "
    "attacks; literal refs with in-job assertions prevent substitution."
)
_UNRELATED_TITLE = (
    "escape_ledger_max_diagnoses_per_tick must be test-pinned, not just configured"
)
_UNRELATED_BODY = (
    "Rule: Any per-tick budget in `escape_ledger_loop.py` that bounds expensive I/O "
    "(git reads + `PRPort.get_issue_labels`) must have a test asserting the cap "
    "holds, not merely a config field in `src/config.py`.\n\nExample: 117 eligible "
    "aging rows x git + API calls would blow the tick; "
    "`escape_ledger_max_diagnoses_per_tick` (default 25) prevents fan-out and the "
    "walk resumes next tick.\n\n**Why:** A configured but untested ceiling can "
    "silently regress under refactoring, causing tick timeouts."
)
_RELATED_TITLE = (
    "CodeQL cache-poisoning: checkout literal default branch, assert the SHA in-job"
)
_RELATED_BODY = (
    "Rule: A workflow job that restores a cache keyed on a checked-out SHA must "
    "check out a literal ref, never an expression ref, and assert the SHA inside "
    "the job.\n\nExample: `.github/workflows/staging-rc-dryrun.yml` uses "
    "`ref: staging` for the cache-key checkout.\n\n**Why:** An expression-ref "
    "checkout lets an attacker substitute a poisoned cache entry."
)


def _entry(title: str, content: str, *, entry_id: str = "x") -> WikiEntry:
    return WikiEntry(
        id=entry_id,
        title=title,
        content=content,
        topic="testing",
        source_type="review",
        created_at="2026-08-21T12:23:02.881220+00:00",
    )


def _write_tracked(
    topic_dir: Path, name: str, *, source_issue: str, title: str
) -> Path:
    """Write one tracked per-entry file with the real frontmatter shape."""
    path = topic_dir / name
    path.write_text(
        "---\n"
        f"id: {name.split('-', maxsplit=1)[0]}\n"
        "topic: testing\n"
        f"source_issue: {source_issue}\n"
        "source_phase: synthesis\n"
        "created_at: 2026-08-14T20:25:49.223556+00:00\n"
        "status: active\n"
        "corroborations: 1\n"
        "---\n\n"
        f"# {title}\n\n"
        "Rule: something specific about `src/config.py`.\n\n"
        "**Why:** it matters.\n",
        encoding="utf-8",
    )
    return path


class TestSynthesisProvenanceEntriesStayLoadable:
    """Defect 1: ``source_issue: synthesis`` must not drop the entry."""

    def test_synthesis_entry_is_a_loadable_candidate(self, tmp_path: Path) -> None:
        topic_dir = tmp_path / "T-rav" / "hydraflow" / "testing"
        topic_dir.mkdir(parents=True)
        _write_tracked(
            topic_dir, "2420-synthesis.md", source_issue="synthesis", title="Synth rule"
        )
        _write_tracked(
            topic_dir, "2421-numeric.md", source_issue="11176", title="Numeric rule"
        )
        store = RepoWikiStore(wiki_root=tmp_path, tracked_root=tmp_path)

        pairs = store._load_tracked_topic_entries_with_paths(topic_dir)

        # Both load; the synthesis entry carries no originating issue rather
        # than being discarded, exactly as lint_tracked_entries treats it.
        assert [(e.title, e.source_issue) for e, _ in pairs] == [
            ("Synth rule", None),
            ("Numeric rule", 11176),
        ]

    @pytest.mark.parametrize(
        "source_issue", ["synthesis", "", "unknown", "#11176", "n/a"]
    )
    def test_no_provenance_shape_is_ever_dropped(
        self, tmp_path: Path, source_issue: str
    ) -> None:
        topic_dir = tmp_path / "T-rav" / "hydraflow" / "testing"
        topic_dir.mkdir(parents=True)
        _write_tracked(
            topic_dir, "2420-entry.md", source_issue=source_issue, title="A rule"
        )
        store = RepoWikiStore(wiki_root=tmp_path, tracked_root=tmp_path)

        assert len(store._load_tracked_topic_entries_with_paths(topic_dir)) == 1


class TestCandidatesAreRankedByTopicalSimilarity:
    """Defect 2: the candidate window follows the entry, not the filename."""

    def test_the_escape_shape_no_longer_offers_the_unrelated_entry(self) -> None:
        """The exact #11606 pairing: the cache-poisoning entry being ingested
        must reach the escape-ledger entry only after the entries that are
        actually about its subject — and only if it clears the floor."""
        ingested = _entry(_INGESTED_TITLE, _INGESTED_BODY)
        unrelated = _entry(_UNRELATED_TITLE, _UNRELATED_BODY, entry_id="2609")
        related = _entry(_RELATED_TITLE, _RELATED_BODY, entry_id="2770")
        # Filename order puts the unrelated entry FIRST, as it was in the
        # live topic dir — a positional slice of 1 would pick exactly it.
        existing = [(unrelated, Path("2609.md")), (related, Path("2770.md"))]

        ranked = rank_corroboration_candidates(ingested, existing, limit=1)

        assert [path.name for _e, path in ranked] == ["2770.md"]
        assert candidate_similarity(ingested, related) > candidate_similarity(
            ingested, unrelated
        )

    def test_an_entry_below_the_floor_is_never_put_to_the_llm(self) -> None:
        """No candidate at all beats an unrelated one: a spurious
        corroboration silently inflates a trust signal, while a missed one
        only writes a sibling the topic compiler later merges."""
        ingested = _entry(_INGESTED_TITLE, _INGESTED_BODY)
        unrelated = _entry(_UNRELATED_TITLE, _UNRELATED_BODY, entry_id="2609")

        assert candidate_similarity(ingested, unrelated) < MIN_CANDIDATE_SIMILARITY
        assert (
            rank_corroboration_candidates(
                ingested, [(unrelated, Path("2609.md"))], limit=5
            )
            == []
        )

    def test_ranking_reaches_past_the_old_five_entry_window(self) -> None:
        """The genuine match at index 40 was unreachable before; position
        must no longer decide who is eligible."""
        ingested = _entry(_INGESTED_TITLE, _INGESTED_BODY)
        filler = [
            (_entry(f"Unrelated rule {i}", _UNRELATED_BODY), Path(f"{i:04d}.md"))
            for i in range(40)
        ]
        related = (_entry(_RELATED_TITLE, _RELATED_BODY), Path("9999.md"))

        ranked = rank_corroboration_candidates(ingested, [*filler, related], limit=5)

        assert [path.name for _e, path in ranked] == ["9999.md"]

    def test_ties_keep_incoming_order_so_the_result_is_deterministic(self) -> None:
        ingested = _entry(_INGESTED_TITLE, _INGESTED_BODY)
        twins = [
            (_entry(_RELATED_TITLE, _RELATED_BODY), Path("b.md")),
            (_entry(_RELATED_TITLE, _RELATED_BODY), Path("a.md")),
        ]

        ranked = rank_corroboration_candidates(ingested, twins, limit=2)

        assert [path.name for _e, path in ranked] == ["b.md", "a.md"]

    @pytest.mark.parametrize("limit", [0, -1])
    def test_a_non_positive_limit_asks_for_nothing(self, limit: int) -> None:
        ingested = _entry(_INGESTED_TITLE, _INGESTED_BODY)
        related = [(_entry(_RELATED_TITLE, _RELATED_BODY), Path("2770.md"))]

        assert rank_corroboration_candidates(ingested, related, limit=limit) == []

    def test_an_empty_entry_scores_zero_rather_than_dividing_by_zero(self) -> None:
        assert candidate_similarity(_entry("", ""), _entry("", "")) == 0.0
