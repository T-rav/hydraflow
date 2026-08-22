"""Unit tests for the test-adequacy calibration runner — the I/O shell (#11593).

Runs against the committed, **sanitized** fixture corpus under
``tests/fixtures/adequacy_calibration/`` (hand-built to exercise each case; real
run manifests are never committed — they carry issue bodies and host paths).
No network and no ``gh``: the issue→PR lookup goes through the injected
:data:`calibrate_adequacy_gate.IssueQuery` seam.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from calibrate_adequacy_gate import (  # noqa: E402
    IssueFacts,
    build_issue_outcomes,
    filter_since,
    gated_and_accepted_issues,
    gh_issue_facts,
    load_escaped_prs,
    load_issue_facts_cache,
    load_run_records,
    main,
    parse_since,
    render_report,
    resolve_issue_facts,
)

from adequacy_calibration import GateOutcome, RecordShape  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "adequacy_calibration"
RUNS_ROOT = FIXTURES / "runs"
LEDGER = FIXTURES / "escape_ledger.jsonl"


# -- corpus loading -------------------------------------------------------------


def test_load_run_records_reads_every_parseable_manifest() -> None:
    records, _ = load_run_records(RUNS_ROOT)
    assert len(records) == 11


def test_load_run_records_counts_the_malformed_manifest_as_skipped() -> None:
    _, skipped = load_run_records(RUNS_ROOT)
    assert skipped == 1


def test_load_run_records_returns_empty_for_a_missing_root(tmp_path: Path) -> None:
    assert load_run_records(tmp_path / "absent") == ([], 0)


def test_load_run_records_skips_a_manifest_that_is_not_json(tmp_path: Path) -> None:
    manifest = tmp_path / "9001" / "20260801T000000Z" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{ broken")
    assert load_run_records(tmp_path) == ([], 1)


def test_load_run_records_recognises_the_structured_manifest() -> None:
    records, _ = load_run_records(RUNS_ROOT)
    structured = [r for r in records if r.shape is RecordShape.STRUCTURED]
    assert [r.issue_number for r in structured] == [9009]


def test_load_run_records_classifies_the_fixture_rejections() -> None:
    records, _ = load_run_records(RUNS_ROOT)
    rejected = [r for r in records if r.gate_outcome is GateOutcome.REJECTED]
    assert len(rejected) == 7


# -- escape ledger --------------------------------------------------------------


def test_load_escaped_prs_returns_none_when_the_ledger_is_absent(
    tmp_path: Path,
) -> None:
    assert load_escaped_prs(tmp_path / "absent.jsonl") is None


def test_load_escaped_prs_collects_attributed_pr_numbers() -> None:
    assert load_escaped_prs(LEDGER) == {9101, 9109}


def test_load_escaped_prs_returns_an_empty_set_for_an_empty_ledger(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "escape_ledger.jsonl"
    ledger.write_text("")
    assert load_escaped_prs(ledger) == set()


# -- outcome joining ------------------------------------------------------------


_FACTS = {
    9001: IssueFacts(closing_prs=(9101,), closed_at=datetime(2026, 8, 2, tzinfo=UTC))
}


def test_build_issue_outcomes_leaves_escape_unresolved_without_a_ledger() -> None:
    outcomes = build_issue_outcomes([9001], _FACTS, None)
    assert outcomes[0].escaped is None


def test_build_issue_outcomes_leaves_escape_unresolved_without_a_closing_pr() -> None:
    outcomes = build_issue_outcomes([9001], {}, {9101})
    assert outcomes[0].escaped is None


def test_build_issue_outcomes_marks_an_attributed_pr_as_escaped() -> None:
    outcomes = build_issue_outcomes([9001], _FACTS, {9101})
    assert outcomes[0].escaped is True


def test_build_issue_outcomes_reads_an_unattributed_pr_as_escape_free() -> None:
    outcomes = build_issue_outcomes([9001], _FACTS, {9999})
    assert outcomes[0].escaped is False


def test_build_issue_outcomes_carries_the_close_date_for_grace_ageing() -> None:
    outcomes = build_issue_outcomes([9001], _FACTS, {9999})
    assert outcomes[0].closed_at == datetime(2026, 8, 2, tzinfo=UTC)


# -- closing-PR resolution ------------------------------------------------------


def test_resolve_issue_facts_returns_the_cache_when_no_query_is_given() -> None:
    cached = {9001: IssueFacts(closing_prs=(1,))}
    assert resolve_issue_facts([9001, 9002], cached=cached, query=None) == cached


def test_resolve_issue_facts_queries_only_the_uncached_issues() -> None:
    asked: list[int] = []

    def query(issue: int) -> IssueFacts:
        asked.append(issue)
        return IssueFacts(closing_prs=(issue + 100,))

    resolve_issue_facts([9001, 9002], cached={9001: IssueFacts()}, query=query)
    assert asked == [9002]


def test_load_issue_facts_cache_reads_the_full_row_shape(tmp_path: Path) -> None:
    path = tmp_path / "outcomes.json"
    path.write_text(
        json.dumps({"9001": {"prs": [9101], "closed_at": "20260802T000000Z"}})
    )
    assert load_issue_facts_cache(path)[9001] == IssueFacts(
        closing_prs=(9101,), closed_at=datetime(2026, 8, 2, tzinfo=UTC)
    )


def test_load_issue_facts_cache_reads_a_bare_pr_list_without_a_close_date(
    tmp_path: Path,
) -> None:
    path = tmp_path / "outcomes.json"
    path.write_text(json.dumps({"9001": [9101]}))
    assert load_issue_facts_cache(path)[9001] == IssueFacts(closing_prs=(9101,))


@pytest.mark.parametrize(
    "body", ["", "{ broken", "[1, 2, 3]", '{"not-an-int": [1]}'], ids=range(4)
)
def test_load_issue_facts_cache_degrades_to_empty_on_bad_input(
    tmp_path: Path, body: str
) -> None:
    path = tmp_path / "outcomes.json"
    path.write_text(body)
    assert load_issue_facts_cache(path) == {}


@pytest.mark.parametrize(
    "prs",
    [
        pytest.param(["n/a"], id="non-numeric-string"),
        pytest.param([None], id="null"),
        pytest.param([{"number": 1}], id="nested-object"),
        pytest.param([True], id="bool"),
        pytest.param("9101", id="not-a-list"),
    ],
)
def test_load_issue_facts_cache_drops_a_junk_pr_entry(
    tmp_path: Path, prs: object
) -> None:
    path = tmp_path / "outcomes.json"
    path.write_text(json.dumps({"9001": {"prs": prs}}))
    assert load_issue_facts_cache(path)[9001].closing_prs == ()


def test_load_issue_facts_cache_keeps_the_good_entries_beside_a_junk_one(
    tmp_path: Path,
) -> None:
    path = tmp_path / "outcomes.json"
    path.write_text(json.dumps({"9001": ["n/a", 9101]}))
    assert load_issue_facts_cache(path)[9001].closing_prs == (9101,)


def test_load_issue_facts_cache_returns_empty_for_a_missing_file(
    tmp_path: Path,
) -> None:
    assert load_issue_facts_cache(tmp_path / "absent.json") == {}


def test_gated_and_accepted_issues_excludes_runs_that_never_reached_the_gate() -> None:
    records, _ = load_run_records(RUNS_ROOT)
    assert 9006 not in gated_and_accepted_issues(records)


def test_gh_issue_facts_returns_empty_when_the_cli_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "calibrate_adequacy_gate.subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("gh")),
    )
    assert gh_issue_facts(9001) == IssueFacts()


# -- window filtering -----------------------------------------------------------


def test_filter_since_keeps_everything_without_a_bound() -> None:
    records, _ = load_run_records(RUNS_ROOT)
    assert filter_since(records, None) == records


def test_filter_since_drops_records_before_the_bound() -> None:
    records, _ = load_run_records(RUNS_ROOT)
    kept = filter_since(records, datetime(2026, 8, 3, tzinfo=UTC))
    assert {r.issue_number for r in kept} == {9008, 9009}


@pytest.mark.parametrize("text", ["2026-08-01", "20260801"])
def test_parse_since_accepts_both_date_forms(text: str) -> None:
    assert parse_since(text) == datetime(2026, 8, 1, tzinfo=UTC)


def test_parse_since_rejects_an_unparseable_date() -> None:
    with pytest.raises(Exception, match="unparseable"):
        parse_since("last tuesday")


# -- rendering + entrypoint -----------------------------------------------------


def _report_text() -> str:
    from adequacy_calibration import calibrate

    records, skipped = load_run_records(RUNS_ROOT)
    outcomes = build_issue_outcomes(
        gated_and_accepted_issues(records),
        {
            9001: IssueFacts((9101,), datetime(2026, 8, 2, tzinfo=UTC)),
            9008: IssueFacts((9108,), datetime(2026, 8, 3, tzinfo=UTC)),
        },
        load_escaped_prs(LEDGER),
    )
    report = calibrate(records, outcomes, now=datetime(2026, 9, 1, tzinfo=UTC))
    return render_report(report, skipped=skipped)


@pytest.mark.parametrize(
    "expected",
    [
        pytest.param("IDENTIFIABILITY: UNDER-DETERMINED", id="identifiability-verdict"),
        pytest.param("outcome-censored", id="reject-arm-censoring"),
        pytest.param("demanded something entirely new", id="demand-stationarity"),
        pytest.param("WEAK-JUSTIFICATION REJECTIONS (4)", id="weak-justification-list"),
    ],
)
def test_render_report_shows_the_calibration_sections(expected: str) -> None:
    assert expected in _report_text()


def test_main_writes_a_json_report(tmp_path: Path) -> None:
    out = tmp_path / "calibration.json"
    main(
        [
            "--runs-root",
            str(RUNS_ROOT),
            "--escape-ledger",
            str(LEDGER),
            "--json",
            "--out",
            str(out),
        ]
    )
    assert json.loads(out.read_text())["n_rejected"] == 7


def test_main_honours_a_cached_issue_outcome_map(tmp_path: Path) -> None:
    cache = tmp_path / "outcomes.json"
    cache.write_text(
        json.dumps(
            {
                "9001": {"prs": [9101], "closed_at": "20260802T000000Z"},
                "9008": {"prs": [9108], "closed_at": "20260803T000000Z"},
            }
        )
    )
    out = tmp_path / "calibration.json"
    main(
        [
            "--runs-root",
            str(RUNS_ROOT),
            "--escape-ledger",
            str(LEDGER),
            "--issue-outcomes",
            str(cache),
            "--json",
            "--out",
            str(out),
        ]
    )
    payload = json.loads(out.read_text())
    assert payload["identifiability"]["n_acceptances_resolved"] == 2


def test_main_returns_zero_on_an_empty_corpus(tmp_path: Path) -> None:
    assert main(["--runs-root", str(tmp_path), "--escape-ledger", str(tmp_path)]) == 0
