"""Unit tests for the escape-ledger pure core (#10367).

Covers the ledger record schema + time-to-detection math, the mechanical
attribution/detection helpers (revert / hotfix / regression-pin / bug-issue),
the append-only JSONL store, the rate / time-to-detection / encoding metrics,
and the Markdown render — all pure, over synthetic inputs, no git.
"""

from __future__ import annotations

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
) -> CommitInfo:
    return CommitInfo(
        sha=sha,
        subject=subject,
        body=body,
        committed_at=committed_at,
        added_paths=added_paths,
    )


def _record(
    rid: str,
    *,
    source: str = "revert",
    detected_at: str = "2026-01-02T00:00:00+00:00",
    ttd: float | None = 24.0,
    confidence: str = "high",
    encoded_as: str = "none-yet",
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
        notes="",
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
        assert cand.originating_pr == 4242

    def test_bug_issue_fix_is_low_confidence(self) -> None:
        commit = _commit(
            "aaaa111",
            subject="fix(triage): stop the crash",
            body="Fixes #777.",
        )
        (cand,) = detect_escapes([commit])
        assert cand.detection_source == "bug-issue"
        assert cand.attribution_confidence == "low"
        assert cand.originating_pr == 777

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
