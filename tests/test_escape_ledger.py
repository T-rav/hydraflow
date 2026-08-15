"""Unit tests for the escape-ledger pure core (#10367).

Covers the ledger record schema + time-to-detection math, the mechanical
attribution/detection helpers (revert / hotfix / regression-pin / bug-issue),
the append-only JSONL store, the rate / time-to-detection / encoding metrics,
and the Markdown render — all pure, over synthetic inputs, no git.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from escape import attribution, metrics
from escape.detect import detect_escapes
from escape.ledger import EscapeLedger
from escape.models import CommitInfo, EscapeCandidate, EscapeRecord
from escape.report import render_escape_ledger_markdown


def _commit(
    sha: str,
    subject: str = "",
    body: str = "",
    committed_at: str = "2026-01-02T00:00:00+00:00",
    added_paths: tuple[str, ...] = (),
    changed_paths: tuple[str, ...] = (),
) -> CommitInfo:
    return CommitInfo(
        sha=sha,
        subject=subject,
        body=body,
        committed_at=committed_at,
        added_paths=added_paths,
        changed_paths=changed_paths,
    )


def _record(
    rid: str,
    *,
    source: str = "revert",
    detected_at: str = "2026-01-02T00:00:00+00:00",
    ttd: float | None = 24.0,
    confidence: str = "high",
    encoded_as: str = "none-yet",
    notes: str = "",
) -> EscapeRecord:
    return EscapeRecord(
        id=rid,
        detected_at=detected_at,
        detection_source=source,
        detection_ref=rid.split(":", 1)[-1],
        originating_pr=None,
        originating_merge_sha="abc1234",
        merged_at="2026-01-01T00:00:00+00:00",
        time_to_detection_hours=ttd,
        attribution_method="revert-parse",
        attribution_confidence=confidence,
        encoded_as=encoded_as,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


class TestEscapeRecord:
    def test_from_candidate_computes_time_to_detection(self) -> None:
        cand = EscapeCandidate(
            detection_source="revert",
            detection_ref="deadbeef",
            detected_at="2026-01-02T00:00:00+00:00",
            attribution_method="revert-parse",
            attribution_confidence="high",
        )
        rec = EscapeRecord.from_candidate(
            cand,
            originating_merge_sha="abc1234",
            merged_at="2026-01-01T00:00:00+00:00",
        )
        assert rec.time_to_detection_hours == 24.0
        assert rec.id == "revert:deadbeef"
        assert rec.originating_merge_sha == "abc1234"
        assert rec.encoded_as == "none-yet"

    def test_from_candidate_ttd_none_without_merged_at(self) -> None:
        cand = EscapeCandidate(
            detection_source="bug-issue",
            detection_ref="c0ffee1",
            detected_at="2026-01-02T00:00:00+00:00",
            attribution_method="fixes-chain",
            attribution_confidence="low",
        )
        rec = EscapeRecord.from_candidate(cand)
        assert rec.time_to_detection_hours is None

    def test_json_roundtrip_preserves_all_fields(self) -> None:
        rec = _record("revert:deadbeef")
        parsed = EscapeRecord.from_json_dict(rec.to_json_dict())
        assert parsed == rec

    def test_id_is_source_prefixed(self) -> None:
        cand = EscapeCandidate(
            detection_source="hotfix",
            detection_ref="abc",
            detected_at="",
            attribution_method="fixes-chain",
            attribution_confidence="medium",
        )
        assert cand.id == "hotfix:abc"


# ---------------------------------------------------------------------------
# attribution
# ---------------------------------------------------------------------------


class TestAttribution:
    def test_parse_reverted_sha(self) -> None:
        body = "Revert reason\n\nThis reverts commit 1234abcd5678."
        assert attribution.parse_reverted_sha(body) == "1234abcd5678"

    def test_is_revert_by_subject(self) -> None:
        assert attribution.is_revert('Revert "feat: thing"', "")

    def test_is_hotfix(self) -> None:
        assert attribution.is_hotfix("hotfix: patch boot", "")
        assert attribution.is_hotfix("fix: x", "This is a hot-fix for prod")
        assert not attribution.is_hotfix("feat: add thing", "nothing here")

    def test_extract_fixes_refs(self) -> None:
        assert attribution.extract_fixes_refs("Fixes #12 and closes #34") == [12, 34]
        assert attribution.extract_fixes_refs("just #99 mentioned") == []

    def test_extract_referenced_shas_excludes_self(self) -> None:
        shas = attribution.extract_referenced_shas(
            "regression from 9f8e7d6c5b4a", exclude="deadbeef"
        )
        assert shas == ["9f8e7d6c5b4a"]

    def test_extract_referenced_shas_rejects_bogus_tokens(self) -> None:
        # A real git sha mixes digits AND a-f letters; a pure-digit number or an
        # all-letter hex-looking word must not be mistaken for an originating
        # merge sha (which would mis-attribute an escape).
        assert attribution.extract_referenced_shas("closes 12345678 today") == []
        assert attribution.extract_referenced_shas("the deadbeef word here") == []
        # …but a real mixed digit+letter sha is still extracted.
        assert attribution.extract_referenced_shas("from 9f8e7d6c5b4a") == [
            "9f8e7d6c5b4a"
        ]

    def test_adds_regression_pin(self) -> None:
        assert attribution.adds_regression_pin(("tests/regressions/test_x.py",))
        assert not attribution.adds_regression_pin(("tests/test_x.py",))

    def test_regression_pins_added_returns_matching_paths(self) -> None:
        # #11178: the caller needs the REAL pin paths (not just a bool) so it
        # can record them as encoding evidence instead of a placeholder.
        assert attribution.regression_pins_added(
            ("tests/regressions/test_x.py", "src/mod.py", "tests/test_y.py")
        ) == ("tests/regressions/test_x.py",)

    def test_regression_pins_added_empty_when_none_match(self) -> None:
        assert (
            attribution.regression_pins_added(("tests/test_x.py", "src/mod.py")) == ()
        )


# ---------------------------------------------------------------------------
# detect — one candidate per commit, precedence
# ---------------------------------------------------------------------------


class TestDetect:
    def test_revert_is_high_confidence(self) -> None:
        commit = _commit(
            "aaaa111",
            subject='Revert "feat: risky"',
            body="This reverts commit bbbb222cccc.",
        )
        (cand,) = detect_escapes([commit])
        assert cand.detection_source == "revert"
        assert cand.attribution_method == "revert-parse"
        assert cand.attribution_confidence == "high"
        assert cand.originating_ref == "bbbb222cccc"

    def test_regression_pin_with_body_sha(self) -> None:
        commit = _commit(
            "aaaa111",
            subject="fix: pin the boot regression",
            body="Regression test for failure introduced in 9f8e7d6c5b4a.",
            added_paths=("tests/regressions/test_boot.py",),
        )
        (cand,) = detect_escapes([commit])
        assert cand.detection_source == "regression-pin"
        assert cand.attribution_method == "regression-pin"
        assert cand.originating_ref == "9f8e7d6c5b4a"

    def test_hotfix_with_fixes_ref(self) -> None:
        commit = _commit(
            "aaaa111",
            subject="hotfix: revert bad migration",
            body="Fixes #4242 from a prior merge.",
        )
        (cand,) = detect_escapes([commit])
        assert cand.detection_source == "hotfix"
        assert cand.attribution_method == "fixes-chain"
        # `Fixes #N` is a closing keyword pointing at downstream work (the
        # issue this commit closes), never the merge that introduced the
        # defect — it must not be written to originating_pr (#10498).
        assert cand.originating_pr is None
        assert cand.originating_ref == "#4242"
        # originating_pr is gone, so the closing ref must survive somewhere
        # on the row or a human reading the HITL finding has no lead at all.
        assert "#4242" in cand.notes

    def test_bug_issue_fix_is_low_confidence(self) -> None:
        commit = _commit(
            "aaaa111",
            subject="fix(triage): stop the crash",
            body="Fixes #777.",
        )
        (cand,) = detect_escapes([commit])
        assert cand.detection_source == "bug-issue"
        assert cand.attribution_confidence == "low"
        assert cand.originating_pr is None
        assert cand.originating_ref == "#777"
        # same attribution-lead requirement as the hotfix case above — this
        # is the exact case issue #10498's HITL finding renders.
        assert "#777" in cand.notes

    def test_bug_issue_skip_regression_trailer_is_not_an_escape(self) -> None:
        # A `fix(...)` commit that declares itself behaviour-neutral via the
        # P10.6/P10.7 opt-out trailer AND carries no product-source delta
        # (e.g. a docs-only diagram refresh) is not a post-merge defect
        # (#10498). The gate is paths-scoped, not trailer-only — see the
        # next two tests for the discriminating cases.
        commit = _commit(
            "9196f74",
            subject="fix(erosion): refresh the arch diagram",
            body=(
                "No source or behavior change.\n\n"
                "Skip-Regression: no code change\n\nCloses #10449."
            ),
            changed_paths=("docs/arch/diagram.likec4",),
        )
        assert detect_escapes([commit]) == []

    def test_skip_regression_trailer_with_product_source_change_is_still_recorded(
        self,
    ) -> None:
        # The Skip-Regression trailer alone is NOT sufficient to suppress: it
        # also legitimately covers a flaky-test fix, a config-only fix, or a
        # fix already covered by an existing test — real escapes. Gating on
        # the trailer alone would silently under-count them, which is the one
        # failure mode a falsification instrument must never have (#10498
        # review). A product-source change (non-test, non-docs) alongside the
        # trailer must still produce a candidate.
        commit = _commit(
            "b0b0b0b",
            subject="fix(health): worker-stall sweep escalates in sandbox",
            body=(
                "Config-only change; no Python-unit-testable surface.\n\n"
                "Skip-Regression: sandbox e2e is the regression guard\n\n"
                "Closes #9001."
            ),
            changed_paths=("src/mockworld/sandbox_main.py",),
        )
        (cand,) = detect_escapes([commit])
        assert cand.detection_source == "bug-issue"

    def test_skip_regression_trailer_with_unknown_changed_paths_fails_open(
        self,
    ) -> None:
        # changed_paths is empty when unknown (a synthetic CommitInfo, or an
        # adapter that hasn't populated it) — the gate must fail OPEN (still
        # record) rather than guess, since guessing wrong in the suppress
        # direction is unrecoverable for this instrument (#10498 review).
        commit = _commit(
            "c0c0c0c",
            subject="fix(erosion): refresh the arch diagram",
            body="Skip-Regression: no code change\n\nCloses #10449.",
        )
        (cand,) = detect_escapes([commit])
        assert cand.detection_source == "bug-issue"

    def test_revert_with_skip_regression_trailer_still_recorded(self) -> None:
        # The Skip-Regression gate must be scoped to the bug-issue branch
        # only — a revert carrying the trailer in its body is still a real
        # escape and must still be recorded (pre-mortem risk: over-broad gate).
        commit = _commit(
            "aaaa111",
            subject='Revert "feat: risky"',
            body="This reverts commit bbbb222cccc.\n\nSkip-Regression: n/a",
        )
        (cand,) = detect_escapes([commit])
        assert cand.detection_source == "revert"

    def test_regression_pin_closing_ref_not_recorded_as_originating_pr(self) -> None:
        commit = _commit(
            "aaaa111",
            subject="fix: pin the boot regression",
            body="Fixes #55.",
            added_paths=("tests/regressions/test_boot.py",),
        )
        (cand,) = detect_escapes([commit])
        assert cand.detection_source == "regression-pin"
        assert cand.originating_pr is None
        assert cand.originating_ref == "#55"

    def test_plain_commit_is_not_an_escape(self) -> None:
        commit = _commit("aaaa111", subject="feat: add a feature", body="new thing")
        assert detect_escapes([commit]) == []

    def test_precedence_revert_over_regression_pin(self) -> None:
        commit = _commit(
            "aaaa111",
            subject='Revert "feat: x"',
            body="This reverts commit bbbb222.",
            added_paths=("tests/regressions/test_x.py",),
        )
        (cand,) = detect_escapes([commit])
        assert cand.detection_source == "revert"

    def test_one_candidate_per_commit_over_a_stream(self) -> None:
        commits = [
            _commit("r1", subject='Revert "x"', body="This reverts commit z9."),
            _commit("f1", subject="feat: y", body=""),
            _commit(
                "p1",
                subject="fix: pin",
                body="from 1111aaaa2222",
                added_paths=("tests/regressions/test_y.py",),
            ),
        ]
        cands = detect_escapes(commits)
        assert [c.detection_source for c in cands] == ["revert", "regression-pin"]


# ---------------------------------------------------------------------------
# ledger — append-only JSONL
# ---------------------------------------------------------------------------


class TestEscapeLedger:
    def test_append_and_read_roundtrip(self, tmp_path: Path) -> None:
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        rec = _record("revert:deadbeef")
        ledger.append(rec)
        assert ledger.read_all() == [rec]
        assert ledger.existing_ids() == {"revert:deadbeef"}

    def test_read_missing_file_is_empty(self, tmp_path: Path) -> None:
        ledger = EscapeLedger(tmp_path / "nope.jsonl")
        assert ledger.read_all() == []
        assert ledger.existing_ids() == set()

    def test_malformed_line_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "escape_ledger.jsonl"
        path.write_text('{"id": "a"}\nnot json\n{"id": "b"}\n', encoding="utf-8")
        ledger = EscapeLedger(path)
        assert {r.id for r in ledger.read_all()} == {"a", "b"}

    def test_read_latest_equals_read_all_when_no_resolutions(
        self, tmp_path: Path
    ) -> None:
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        rec = _record("revert:deadbeef")
        ledger.append(rec)
        assert ledger.read_latest() == ledger.read_all() == [rec]

    def test_append_resolution_preserves_provenance_by_default(
        self, tmp_path: Path
    ) -> None:
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        original = _record(
            "bug-issue:9196f74",
            source="bug-issue",
            confidence="low",
            encoded_as="none-yet",
            notes="pending human review",
        )
        ledger.append(original)

        resolution = ledger.append_resolution(
            "bug-issue:9196f74", encoded_as="detector"
        )

        assert resolution is not None
        assert resolution.id == original.id
        assert resolution.detection_source == original.detection_source
        assert resolution.detected_at == original.detected_at
        assert resolution.encoded_as == "detector"
        # notes/confidence carry forward untouched when not overridden
        assert resolution.notes == "pending human review"
        assert resolution.attribution_confidence == "low"

    def test_append_resolution_confidence_only_carries_encoded_as_forward(
        self, tmp_path: Path
    ) -> None:
        # A human may confirm attribution confidence without naming an
        # encoding — encoded_as must carry forward untouched (#10747).
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        ledger.append(_record("bug-issue:x", confidence="low", encoded_as="none-yet"))

        resolution = ledger.append_resolution(
            "bug-issue:x", attribution_confidence="medium"
        )

        assert resolution is not None
        assert resolution.attribution_confidence == "medium"
        assert resolution.encoded_as == "none-yet"

    def test_append_resolution_can_override_confidence_and_notes(
        self, tmp_path: Path
    ) -> None:
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        ledger.append(_record("bug-issue:x", confidence="low"))

        resolution = ledger.append_resolution(
            "bug-issue:x",
            encoded_as="detector",
            attribution_confidence="medium",
            notes="false positive; see #10498",
        )

        assert resolution is not None
        assert resolution.attribution_confidence == "medium"
        assert resolution.notes == "false positive; see #10498"

    def test_append_resolution_is_append_only(self, tmp_path: Path) -> None:
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        original = _record("bug-issue:9196f74", encoded_as="none-yet")
        ledger.append(original)

        resolution = ledger.append_resolution(
            "bug-issue:9196f74", encoded_as="detector"
        )

        # both lines survive on disk — the original is never rewritten
        assert ledger.read_all() == [original, resolution]
        # id-dedup still sees exactly one id despite two lines
        assert ledger.existing_ids() == {"bug-issue:9196f74"}
        # derived reads collapse to the resolution, not the original
        assert ledger.read_latest() == [resolution]

    def test_append_resolution_unknown_id_returns_none_and_appends_nothing(
        self, tmp_path: Path
    ) -> None:
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        assert ledger.append_resolution("nope:1", encoded_as="detector") is None
        assert ledger.read_all() == []

    def test_read_latest_collapses_a_three_row_chain_to_the_last(
        self, tmp_path: Path
    ) -> None:
        # detect -> resolve -> re-resolve: three lines sharing one id. A
        # detected_at-based collapse would tie (append_resolution carries
        # detected_at forward unchanged on every row); only file-position
        # ordering discriminates this case.
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        ledger.append(_record("bug-issue:9196f74", encoded_as="none-yet"))
        ledger.append_resolution("bug-issue:9196f74", encoded_as="detector")
        final = ledger.append_resolution(
            "bug-issue:9196f74", encoded_as="stored-lesson", notes="re-resolved"
        )

        assert len(ledger.read_all()) == 3
        assert ledger.read_latest() == [final]
        assert ledger.read_latest()[0].encoded_as == "stored-lesson"

    def test_read_latest_index_maps_every_appended_id_to_its_ref_winner(
        self, tmp_path: Path
    ) -> None:
        # Two sources for one commit: read_latest folds bug-issue away, but the
        # index still maps its id to the surviving regression-pin row (#10731).
        sha = "ee56677201303fa4de5b1dec341447d4a12076d4"
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        ledger.append(_record(f"bug-issue:{sha}", source="bug-issue", confidence="low"))
        ledger.append(
            _record(
                f"regression-pin:{sha}", source="regression-pin", confidence="medium"
            )
        )

        index = ledger.read_latest_index()

        assert set(index) == {f"bug-issue:{sha}", f"regression-pin:{sha}"}
        assert all(r.detection_source == "regression-pin" for r in index.values())

    def test_read_latest_index_absent_id_is_not_a_key(self, tmp_path: Path) -> None:
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        ledger.append(_record("bug-issue:aaaa111", source="bug-issue"))

        assert "bug-issue:never-appended" not in ledger.read_latest_index()


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_escapes_per_100_merges(self) -> None:
        assert metrics.escapes_per_100_merges(3, 150) == 2.0
        assert metrics.escapes_per_100_merges(5, 0) == 0.0

    def test_rolling_escape_count_window(self) -> None:
        now = datetime(2026, 2, 1, tzinfo=UTC)
        recs = [
            _record("revert:a", detected_at="2026-01-20T00:00:00+00:00"),
            _record("revert:b", detected_at="2025-12-01T00:00:00+00:00"),  # >30d
        ]
        assert metrics.rolling_escape_count(recs, now, days=30) == 1

    def test_confirmed_rolling_count_excludes_low_confidence(self) -> None:
        # In a fix-heavy repo every `fix: … fixes #N` is a low-confidence
        # bug-issue row; the CONFIRMED headline must not count them as escapes.
        now = datetime(2026, 2, 1, tzinfo=UTC)
        recs = [
            _record(
                "revert:a", confidence="high", detected_at="2026-01-20T00:00:00+00:00"
            ),
            _record(
                "hotfix:c", confidence="medium", detected_at="2026-01-22T00:00:00+00:00"
            ),
            _record(
                "bug-issue:b",
                source="bug-issue",
                confidence="low",
                detected_at="2026-01-21T00:00:00+00:00",
            ),
        ]
        assert metrics.rolling_escape_count(recs, now, days=30) == 3
        assert metrics.rolling_confirmed_escape_count(recs, now, days=30) == 2
        # …so the confirmed rate is strictly below the all-confidence rate.
        assert metrics.escapes_per_100_merges(
            metrics.rolling_confirmed_escape_count(recs, now, days=30), 100
        ) < metrics.escapes_per_100_merges(
            metrics.rolling_escape_count(recs, now, days=30), 100
        )

    def test_percentile_uses_nearest_rank_not_round(self) -> None:
        # p90 of ttd 1..5: nearest-rank ordinal ceil(0.9*5)=5 → the max (5.0),
        # not round(4.5)=4 → 4.0 which understates the tail by one rank.
        recs = [_record(f"revert:{i}", ttd=float(i)) for i in range(1, 6)]
        stats = metrics.time_to_detection_stats(recs)
        assert stats["overall"].n == 5
        assert stats["overall"].p90_hours == 5.0

    def test_time_to_detection_stats_by_source(self) -> None:
        recs = [
            _record("revert:a", source="revert", ttd=10.0),
            _record("revert:b", source="revert", ttd=20.0),
            _record("hotfix:c", source="hotfix", ttd=100.0),
        ]
        stats = metrics.time_to_detection_stats(recs)
        assert stats["revert"].n == 2
        assert stats["revert"].median_hours == 15.0
        assert stats["overall"].n == 3

    def test_encoded_summary(self) -> None:
        recs = [
            _record("a:1", encoded_as="none-yet"),
            _record("a:2", encoded_as="regression-test"),
            _record("a:3", encoded_as="detector"),
        ]
        summary = metrics.encoded_summary(recs)
        assert summary.total == 3
        assert summary.encoded == 2
        assert summary.unencoded == 1

    def test_monthly_series(self) -> None:
        recs = [
            _record("a:1", source="revert", detected_at="2026-01-05T00:00:00+00:00"),
            _record("a:2", source="hotfix", detected_at="2026-01-20T00:00:00+00:00"),
            _record("a:3", source="revert", detected_at="2026-02-02T00:00:00+00:00"),
        ]
        rows = metrics.monthly_series(recs)
        assert [r.month for r in rows] == ["2026-01", "2026-02"]
        assert rows[0].total == 2
        assert rows[0].by_source == {"revert": 1, "hotfix": 1}

    def test_unencoded_aging(self) -> None:
        now = datetime(2026, 2, 1, tzinfo=UTC)
        recs = [
            _record(
                "a:1", encoded_as="none-yet", detected_at="2026-01-01T00:00:00+00:00"
            ),
            _record(
                "a:2", encoded_as="none-yet", detected_at="2026-01-31T00:00:00+00:00"
            ),
            _record(
                "a:3", encoded_as="detector", detected_at="2026-01-01T00:00:00+00:00"
            ),
        ]
        aging = metrics.unencoded_aging(recs, now, threshold_hours=24 * 14)
        assert {r.id for r in aging} == {"a:1"}

    def test_low_confidence(self) -> None:
        recs = [
            _record("a:1", confidence="low"),
            _record("a:2", confidence="high"),
        ]
        assert {r.id for r in metrics.low_confidence(recs)} == {"a:1"}

    def test_latest_by_id_empty_list(self) -> None:
        assert metrics.latest_by_id([]) == []

    def test_latest_by_id_collapses_to_last_appended_row(self) -> None:
        original = _record("a:1", encoded_as="none-yet", confidence="low")
        other = _record("b:2", encoded_as="none-yet")
        resolution = _record("a:1", encoded_as="detector", confidence="medium")

        collapsed = metrics.latest_by_id([original, other, resolution])

        # order of first appearance is preserved; content is the latest row
        assert [r.id for r in collapsed] == ["a:1", "b:2"]
        assert collapsed[0].encoded_as == "detector"
        assert collapsed[0].attribution_confidence == "medium"

    def test_latest_by_id_identity_when_no_duplicate_ids(self) -> None:
        recs = [_record("a:1"), _record("b:2"), _record("c:3")]
        assert metrics.latest_by_id(recs) == recs

    def test_latest_by_escape_empty_list(self) -> None:
        assert metrics.latest_by_escape([]) == []

    def test_latest_by_escape_collapses_two_sources_for_one_commit(self) -> None:
        # The #10654 double-count: one commit sha detected under two sources
        # (bug-issue/low then regression-pin/medium) has two distinct ids that
        # latest_by_id can never merge — latest_by_escape groups by detection_ref
        # and keeps the stronger (medium) row, so the commit counts once.
        sha = "ee56677201303fa4de5b1dec341447d4a12076d4"
        rows = [
            _record(f"bug-issue:{sha}", source="bug-issue", confidence="low"),
            _record(
                f"regression-pin:{sha}", source="regression-pin", confidence="medium"
            ),
        ]

        collapsed = metrics.latest_by_escape(rows)

        assert len(collapsed) == 1
        assert collapsed[0].detection_source == "regression-pin"
        assert collapsed[0].attribution_confidence == "medium"

    def test_latest_by_escape_counts_the_collapsed_commit_once(self) -> None:
        # encoded_summary().total and rolling_escape_count must see one commit,
        # not two, once the two-source rows are collapsed.
        now = datetime(2026, 2, 1, tzinfo=UTC)
        sha = "055267e7b2b7900d615b0ff8553ef511dc3e8652"
        rows = [
            _record(
                f"bug-issue:{sha}",
                source="bug-issue",
                confidence="low",
                detected_at="2026-01-20T00:00:00+00:00",
            ),
            _record(
                f"regression-pin:{sha}",
                source="regression-pin",
                confidence="medium",
                detected_at="2026-01-20T00:00:00+00:00",
            ),
        ]

        collapsed = metrics.latest_by_escape(rows)

        assert metrics.encoded_summary(collapsed).total == 1
        assert metrics.rolling_escape_count(collapsed, now, days=30) == 1

    def test_latest_by_escape_never_discards_a_human_resolution(self) -> None:
        # A resolved row (encoded_as != "none-yet") must survive collapse
        # against a LATER unencoded row sharing its detection_ref — an appended
        # human resolution is never dropped for a mechanical sibling.
        sha = "9196f74abcd"
        resolved = _record(
            f"regression-pin:{sha}",
            source="regression-pin",
            confidence="medium",
            encoded_as="detector",
        )
        later_unencoded = _record(
            f"bug-issue:{sha}",
            source="bug-issue",
            confidence="low",
            encoded_as="none-yet",
        )

        collapsed = metrics.latest_by_escape([resolved, later_unencoded])

        assert len(collapsed) == 1
        assert collapsed[0].encoded_as == "detector"
        assert collapsed[0].detection_source == "regression-pin"

    def test_latest_by_escape_keeps_distinct_commits_separate(self) -> None:
        # Counter-pin: two genuinely different escaping commits (distinct
        # detection_refs) keep two separate rows — the collapse folds only
        # re-detections of the SAME commit, never merges unrelated escapes.
        rows = [
            _record("bug-issue:aaaa111", source="bug-issue", confidence="low"),
            _record("bug-issue:bbbb222", source="bug-issue", confidence="low"),
        ]

        collapsed = metrics.latest_by_escape(rows)

        assert {r.detection_ref for r in collapsed} == {"aaaa111", "bbbb222"}
        assert len(collapsed) == 2

    def test_latest_by_escape_preserves_first_appearance_order(self) -> None:
        rows = [
            _record("bug-issue:ref-c", source="bug-issue", confidence="low"),
            _record("bug-issue:ref-a", source="bug-issue", confidence="low"),
            _record(
                "regression-pin:ref-c", source="regression-pin", confidence="medium"
            ),
        ]

        collapsed = metrics.latest_by_escape(rows)

        # ref-c appeared first (row 0), ref-a second — order preserved despite
        # ref-c's surviving row being the later-appended regression-pin one.
        assert [r.detection_ref for r in collapsed] == ["ref-c", "ref-a"]

    def test_escape_by_id_empty_list(self) -> None:
        assert metrics.escape_by_id([]) == {}

    def test_escape_by_id_maps_both_sibling_ids_to_the_single_survivor(self) -> None:
        # The #10731 case: both ids of a two-source commit map to the one row
        # that won the detection_ref collapse (the stronger medium sibling).
        sha = "ee56677201303fa4de5b1dec341447d4a12076d4"
        rows = [
            _record(f"bug-issue:{sha}", source="bug-issue", confidence="low"),
            _record(
                f"regression-pin:{sha}", source="regression-pin", confidence="medium"
            ),
        ]

        index = metrics.escape_by_id(rows)

        assert set(index) == {f"bug-issue:{sha}", f"regression-pin:{sha}"}
        survivor = index[f"bug-issue:{sha}"]
        assert survivor.detection_source == "regression-pin"
        assert survivor is index[f"regression-pin:{sha}"]

    def test_escape_by_id_resolved_row_is_the_mapped_value_for_every_sibling(
        self,
    ) -> None:
        # An encoded resolution row wins the collapse; both sibling ids of the
        # commit map to it (never discard a human resolution, #10654).
        sha = "9196f74abcd"
        resolved = _record(
            f"bug-issue:{sha}",
            source="bug-issue",
            confidence="high",
            encoded_as="detector",
        )
        sibling = _record(
            f"regression-pin:{sha}", source="regression-pin", confidence="medium"
        )

        index = metrics.escape_by_id([resolved, sibling])

        assert index[f"bug-issue:{sha}"].encoded_as == "detector"
        assert index[f"regression-pin:{sha}"].encoded_as == "detector"

    def test_escape_by_id_no_ref_rows_each_map_to_themselves(self) -> None:
        # Rows with no detection_ref are each their own escape — not one shared
        # entry under an empty key (mirrors latest_by_escape's no-ref fallback).
        a = EscapeRecord(
            id="sentry:evt-a",
            detected_at="2026-01-02T00:00:00+00:00",
            detection_source="sentry",
            detection_ref="",
            originating_pr=None,
            originating_merge_sha="",
            merged_at="",
            time_to_detection_hours=None,
            attribution_method="agent-research",
            attribution_confidence="low",
            encoded_as="none-yet",
            notes="",
        )
        b = replace(a, id="sentry:evt-b")

        index = metrics.escape_by_id([a, b])

        assert index["sentry:evt-a"] is a
        assert index["sentry:evt-b"] is b


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def test_render_report_contains_headline_rate() -> None:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    recs = [_record("revert:a", detected_at="2026-01-20T00:00:00+00:00")]
    md = render_escape_ledger_markdown(recs, now=now, merge_count_30d=200)
    assert "# Escape ledger" in md
    assert "escapes per 100 merges" in md
    # 1 escape / 200 merges * 100 = 0.50
    assert "0.50" in md
    assert "revert" in md


def test_render_report_confirmed_rate_not_inflated_by_low_confidence() -> None:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    recs = [
        _record("revert:a", confidence="high", detected_at="2026-01-20T00:00:00+00:00"),
        _record(
            "bug-issue:b",
            source="bug-issue",
            confidence="low",
            detected_at="2026-01-21T00:00:00+00:00",
        ),
    ]
    md = render_escape_ledger_markdown(recs, now=now, merge_count_30d=100)
    assert "| confirmed escapes (rolling 30d) | 1 |" in md
    assert "| escapes (rolling 30d, all confidence) | 2 |" in md
    # Confirmed rate (1/100*100 = 1.00) < all-confidence rate (2/100*100 = 2.00):
    # the low-confidence bug-issue row does NOT inflate the confirmed headline.
    assert "**confirmed escapes per 100 merges** | **1.00**" in md
    assert "escapes per 100 merges (all confidence) | 2.00" in md


def _table_cells(line: str) -> list[str]:
    """Split a markdown table row into cells, treating ``\\|`` as literal."""
    body = line.strip()
    assert body.startswith("|") and body.endswith("|"), line
    body = body[1:-1]
    cells: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body) and body[i + 1] == "|":
            current.append("\\|")
            i += 2
            continue
        if ch == "|":
            cells.append("".join(current).strip())
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    cells.append("".join(current).strip())
    return cells


def _recent_escapes_table(md: str) -> tuple[str, str, list[str]]:
    lines = md.splitlines()
    idx = lines.index("## Recent escapes")
    header = lines[idx + 2]
    separator = lines[idx + 3]
    rows = []
    i = idx + 4
    while i < len(lines) and lines[i] != "":
        rows.append(lines[i])
        i += 1
    return header, separator, rows


def test_render_report_recent_escapes_header_and_separator_have_nine_cells() -> None:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    md = render_escape_ledger_markdown([], now=now, merge_count_30d=10)
    header, separator, _ = _recent_escapes_table(md)
    assert "evidence" in header
    assert len(_table_cells(header)) == 9
    assert len(_table_cells(separator)) == 9


def test_render_report_recent_escapes_placeholder_row_has_nine_cells() -> None:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    md = render_escape_ledger_markdown([], now=now, merge_count_30d=10)
    _, _, rows = _recent_escapes_table(md)
    assert len(rows) == 1
    assert len(_table_cells(rows[0])) == 9


def test_render_report_recent_escapes_evidence_is_the_last_cell() -> None:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    recs = [
        _record(
            "revert:a",
            detected_at="2026-01-20T00:00:00+00:00",
            notes="tests/regressions/test_issue_10367.py",
        )
    ]
    md = render_escape_ledger_markdown(recs, now=now, merge_count_30d=200)
    _, _, rows = _recent_escapes_table(md)
    cells = _table_cells(rows[0])
    assert len(cells) == 9
    assert cells[-1] == "tests/regressions/test_issue_10367.py"


def test_render_report_recent_escapes_evidence_dash_when_notes_empty() -> None:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    recs = [_record("revert:a", detected_at="2026-01-20T00:00:00+00:00", notes="")]
    md = render_escape_ledger_markdown(recs, now=now, merge_count_30d=200)
    _, _, rows = _recent_escapes_table(md)
    assert _table_cells(rows[0])[-1] == "—"


def test_render_report_recent_escapes_evidence_collapses_multiline_notes_to_one_row() -> (
    None
):
    now = datetime(2026, 2, 1, tzinfo=UTC)
    recs = [
        _record(
            "revert:a",
            detected_at="2026-01-20T00:00:00+00:00",
            notes="line one\nline two\n\nline three",
        )
    ]
    md = render_escape_ledger_markdown(recs, now=now, merge_count_30d=200)
    _, _, rows = _recent_escapes_table(md)
    assert len(rows) == 1
    cells = _table_cells(rows[0])
    assert len(cells) == 9
    assert cells[-1] == "line one line two line three"


def test_render_report_recent_escapes_evidence_escapes_pipe_characters() -> None:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    recs = [
        _record(
            "revert:a",
            detected_at="2026-01-20T00:00:00+00:00",
            notes="ADR-0367 | see also #10367",
        )
    ]
    md = render_escape_ledger_markdown(recs, now=now, merge_count_30d=200)
    _, _, rows = _recent_escapes_table(md)
    cells = _table_cells(rows[0])
    assert len(cells) == 9
    assert cells[-1] == "ADR-0367 \\| see also #10367"


def test_render_report_recent_escapes_evidence_truncates_and_preserves_leading_path() -> (
    None
):
    now = datetime(2026, 2, 1, tzinfo=UTC)
    long_note = "tests/regressions/test_issue_11185.py: " + ("detail " * 40)
    recs = [
        _record("revert:a", detected_at="2026-01-20T00:00:00+00:00", notes=long_note)
    ]
    md = render_escape_ledger_markdown(recs, now=now, merge_count_30d=200)
    _, _, rows = _recent_escapes_table(md)
    cells = _table_cells(rows[0])
    assert len(cells) == 9
    evidence = cells[-1]
    assert evidence.startswith("tests/regressions/test_issue_11185.py:")
    assert evidence.endswith("…")
    assert len(evidence) < len(long_note)


def test_render_report_recent_escapes_evidence_truncation_keeps_pipe_at_boundary_intact() -> (
    None
):
    from escape.notes import EVIDENCE_MAX_CHARS

    now = datetime(2026, 2, 1, tzinfo=UTC)
    prefix = "tests/regressions/test_issue_11185.py: "
    padding = "a" * (EVIDENCE_MAX_CHARS - len(prefix) - 1)
    # The pipe is the LAST character truncation keeps -- escape-then-truncate
    # could split its backslash from the pipe right here.
    long_note = f"{prefix}{padding}|" + "b" * 30
    recs = [
        _record("revert:a", detected_at="2026-01-20T00:00:00+00:00", notes=long_note)
    ]
    md = render_escape_ledger_markdown(recs, now=now, merge_count_30d=200)
    _, _, rows = _recent_escapes_table(md)
    cells = _table_cells(rows[0])
    assert len(cells) == 9, (
        "a pipe at the truncation boundary corrupted the row's cell count"
    )
    evidence = cells[-1]
    assert evidence.startswith(prefix)
    assert evidence.endswith("\\|…"), (
        "escaping before truncating leaves a dangling backslash with no "
        f"pipe (got {evidence[-15:]!r}) -- truncate the raw text first"
    )


def test_render_report_recent_escapes_evidence_truncation_drops_pipe_past_boundary() -> (
    None
):
    from escape.notes import EVIDENCE_MAX_CHARS

    now = datetime(2026, 2, 1, tzinfo=UTC)
    prefix = "tests/regressions/test_issue_11185.py: "
    padding = "a" * (EVIDENCE_MAX_CHARS - len(prefix))
    # The pipe is the FIRST character truncation drops entirely.
    long_note = f"{prefix}{padding}|" + "b" * 30
    recs = [
        _record("revert:a", detected_at="2026-01-20T00:00:00+00:00", notes=long_note)
    ]
    md = render_escape_ledger_markdown(recs, now=now, merge_count_30d=200)
    _, _, rows = _recent_escapes_table(md)
    cells = _table_cells(rows[0])
    assert len(cells) == 9
    evidence = cells[-1]
    assert evidence.startswith(prefix)
    assert evidence.endswith("…")
    assert "|" not in evidence.replace("\\|", ""), (
        "no bare unescaped pipe should leak into the cell"
    )
