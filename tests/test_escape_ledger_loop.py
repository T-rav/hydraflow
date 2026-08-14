"""Unit tests for EscapeLedgerLoop (#10367).

Covers the kill-switch, the cursor (baseline priming + dedup by SHA), an
end-to-end escape recording over a real git revert range (populated
time-to-detection), the erosion trend datapoint + generated reports, the
finding-rate budget (pure cap), and reraise_on_credit_or_bug in the
issue-surfacing except.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from escape.auto_diagnose import EscapeAutoDiagnoser, EscapeDiagnosis
from escape.ledger import EscapeLedger
from escape.models import EscapeRecord
from escape.surfaces import SurfacedIssue, SurfacedIssueLedger
from escape_ledger_loop import (
    _SURFACE_REASON_REMEDIATION,
    _SURFACE_REASON_TEXT,
    SURFACE_REASON_AGING,
    SURFACE_REASON_LOW_CONFIDENCE,
    EscapeLedgerLoop,
    _current_head_sha,
    _render_finding,
    answered_surfacings,
    apply_ask_budget,
    eligible_findings,
    surfacing_fingerprint,
)
from mockworld.fakes.fake_github import FakeGitHub
from subprocess_util import CreditExhaustedError
from tests.helpers import make_bg_loop_deps


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    _git(repo, "init", "-q")
    # Per-repo identity — CI carries no global git config (see
    # feedback-ci-no-global-git-config).
    _git(repo, "config", "user.email", "t@e.dev")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "-m", "init", "--allow-empty")
    return repo


def _head(repo: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _seed_revert_range(repo: Path) -> tuple[str, str]:
    """Base commit + a bad commit + a `git revert` of it. Returns (base, head)."""
    base_sha = _head(repo)
    (repo / "src" / "mod.py").write_text("def risky():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: risky change")
    bad_sha = _head(repo)
    _git(repo, "revert", "--no-edit", bad_sha)
    return base_sha, _head(repo)


def _make_state(initial_sha: str = "") -> MagicMock:
    state = MagicMock()
    cursor: dict[str, str] = {"sha": initial_sha}
    state.get_escape_ledger_last_processed_sha.side_effect = lambda: cursor["sha"]

    def _set(sha: str) -> None:
        cursor["sha"] = sha

    state.set_escape_ledger_last_processed_sha.side_effect = _set
    state._cursor = cursor
    return state


def _make_dedup(seen: set[str] | None = None) -> MagicMock:
    dedup = MagicMock()
    store: set[str] = set(seen or set())
    dedup.get.side_effect = lambda: set(store)

    def _set_all(values: set[str]) -> None:
        store.clear()
        store.update(values)

    dedup.set_all.side_effect = _set_all
    dedup._store = store
    return dedup


def _make_loop(
    tmp_path: Path,
    repo: Path,
    *,
    state: MagicMock | None = None,
    dedup: MagicMock | None = None,
    pr_manager: Any = None,
    **config_overrides: Any,
) -> EscapeLedgerLoop:
    max_issues = config_overrides.pop("escape_ledger_max_issues_per_tick", None)
    bg = make_bg_loop_deps(tmp_path, **config_overrides)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "escape_ledger_loop_enabled", True)
    if max_issues is not None:
        object.__setattr__(bg.config, "escape_ledger_max_issues_per_tick", max_issues)
    prs = pr_manager if pr_manager is not None else MagicMock()
    if not isinstance(prs.create_issue, AsyncMock):
        prs.create_issue = AsyncMock(return_value=1)
    return EscapeLedgerLoop(
        config=bg.config,
        pr_manager=prs,
        state=state if state is not None else _make_state(),
        dedup=dedup if dedup is not None else _make_dedup(),
        deps=bg.loop_deps,
    )


def _record(
    rid: str, *, confidence: str = "low", encoded_as: str = "none-yet", notes: str = ""
) -> EscapeRecord:
    return EscapeRecord(
        id=rid,
        detected_at="2026-01-01T00:00:00+00:00",
        detection_source="bug-issue",
        detection_ref=rid.split(":", 1)[-1],
        originating_pr=None,
        originating_merge_sha="",
        merged_at="",
        time_to_detection_hours=None,
        attribution_method="fixes-chain",
        attribution_confidence=confidence,
        encoded_as=encoded_as,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# _current_head_sha
# ---------------------------------------------------------------------------


def test_current_head_sha_reads_real_head(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    assert _current_head_sha(repo) == _head(repo)


def test_current_head_sha_none_outside_repo(tmp_path: Path) -> None:
    assert _current_head_sha(tmp_path) is None


# ---------------------------------------------------------------------------
# Kill-switch
# ---------------------------------------------------------------------------


class TestKillSwitch:
    async def test_disabled_via_enabled_cb(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        bg = make_bg_loop_deps(tmp_path, enabled=False)
        object.__setattr__(bg.config, "repo_root", repo)
        object.__setattr__(bg.config, "data_root", tmp_path / "data")
        loop = EscapeLedgerLoop(
            config=bg.config,
            pr_manager=MagicMock(),
            state=_make_state(),
            dedup=_make_dedup(),
            deps=bg.loop_deps,
        )
        assert await loop._do_work() == {"status": "disabled"}

    async def test_disabled_via_config_flag(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        bg = make_bg_loop_deps(tmp_path)
        object.__setattr__(bg.config, "repo_root", repo)
        object.__setattr__(bg.config, "data_root", tmp_path / "data")
        object.__setattr__(bg.config, "escape_ledger_loop_enabled", False)
        loop = EscapeLedgerLoop(
            config=bg.config,
            pr_manager=MagicMock(),
            state=_make_state(),
            dedup=_make_dedup(),
            deps=bg.loop_deps,
        )
        assert await loop._do_work() == {"status": "config_disabled"}

    async def test_dry_run_returns_none(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        loop = _make_loop(tmp_path, repo, dry_run=True)
        assert await loop._do_work() is None


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------


class TestCursor:
    async def test_first_tick_primes_baseline_without_analysis(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        state = _make_state(initial_sha="")
        loop = _make_loop(tmp_path, repo, state=state)
        result = await loop._do_work()
        assert result["status"] == "baseline_established"
        assert state._cursor["sha"] == _head(repo)

    async def test_no_new_commits_is_noop(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        head = _head(repo)
        state = _make_state(initial_sha=head)
        loop = _make_loop(tmp_path, repo, state=state)
        assert await loop._do_work() == {
            "status": "no_new_commits",
            "sha": head,
            "closed": 0,
        }


# ---------------------------------------------------------------------------
# End-to-end escape recording over a real revert range
# ---------------------------------------------------------------------------


class TestRecordEscapes:
    async def test_revert_range_records_one_row_with_populated_ttd(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base_sha, head_sha = _seed_revert_range(repo)
        state = _make_state(initial_sha=base_sha)
        loop = _make_loop(tmp_path, repo, state=state)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["escapes_recorded"] == 1
        assert result["escapes_detected"] == 1
        assert state._cursor["sha"] == head_sha

        from escape.ledger import EscapeLedger

        records = EscapeLedger(loop._ledger_path).read_all()
        assert len(records) == 1
        row = records[0]
        assert row.detection_source == "revert"
        assert row.attribution_method == "revert-parse"
        assert row.attribution_confidence == "high"
        assert row.time_to_detection_hours is not None  # merged_at resolved from sha

        # Generated reports written into the repo root (gitignored at runtime).
        assert (repo / "docs/arch/generated/escape-ledger.md").exists()
        assert (repo / "docs/arch/generated/erosion-trends.md").exists()

    async def test_second_tick_no_new_commits_does_not_refile(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base_sha, head_sha = _seed_revert_range(repo)
        state = _make_state(initial_sha=base_sha)
        dedup = _make_dedup()
        loop = _make_loop(tmp_path, repo, state=state, dedup=dedup)

        first = await loop._do_work()
        assert first["escapes_recorded"] == 1

        second = await loop._do_work()
        assert second == {"status": "no_new_commits", "sha": head_sha, "closed": 0}

        from escape.ledger import EscapeLedger

        assert len(EscapeLedger(loop._ledger_path).read_all()) == 1  # not doubled

    async def test_trend_datapoint_appended(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base_sha, _head_sha = _seed_revert_range(repo)
        state = _make_state(initial_sha=base_sha)
        loop = _make_loop(tmp_path, repo, state=state)

        result = await loop._do_work()

        assert result["trend_datapoint"] is True
        from erosion.trends import TrendStore

        assert len(TrendStore(loop._trends_path).read_all()) == 1


# ---------------------------------------------------------------------------
# Finding-rate budget (pure) + surfacing
# ---------------------------------------------------------------------------


class TestRenderFinding:
    def test_body_surfaces_closing_ref_via_notes_when_originating_pr_is_none(
        self,
    ) -> None:
        # originating_pr is never populated for a bug-issue row (#10498) — the
        # rendered HITL finding must still give a human an attribution lead
        # via notes, or the finding points at nothing.
        record = _record(
            "bug-issue:9196f74",
            notes="Fix commit closing #10449 — bug-issue escape pending a "
            "human bug-label confirmation (HITL).",
        )
        _title, body = _render_finding(record, SURFACE_REASON_LOW_CONFIDENCE)
        assert "| originating_pr | — |" in body
        assert "#10449" in body

    def test_body_renders_em_dash_for_empty_notes(self) -> None:
        record = _record("bug-issue:x", notes="")
        _title, body = _render_finding(record, SURFACE_REASON_LOW_CONFIDENCE)
        assert "| notes | — |" in body

    def test_title_reflects_aging_reason_even_for_low_confidence_row(self) -> None:
        # A low-confidence + none-yet row surfaced for the AGING criterion (#10503)
        # must read as aging, not infer "low-confidence" from the row's confidence.
        record = _record("bug-issue:y", confidence="low", encoded_as="none-yet")
        title, _body = _render_finding(record, SURFACE_REASON_AGING)
        assert "aged past the encoding threshold" in title

    def test_low_confidence_body_prescribes_confidence_not_encoding(self) -> None:
        # #10747: the low-confidence remediation must name --confidence — the
        # field that actually answers _surfacing_answered's low-confidence
        # predicate — not just the --encoded-as form the aging surface uses.
        record = _record("bug-issue:z", confidence="low", encoded_as="none-yet")
        _title, body = _render_finding(record, SURFACE_REASON_LOW_CONFIDENCE)
        assert "make escape-resolve" in body
        assert "--confidence" in body
        assert "bug-issue:z" in body
        assert "<regression-test|stored-lesson|detector|adr>" not in body
        # The placeholder must never offer "low" — a resolution that only
        # confirms confidence="low" can never satisfy this surface's own
        # answered predicate (attribution_confidence != "low") and would
        # silently strand the HITL issue. Scoped to the printed command
        # itself, not the surrounding prose, which legitimately says
        # "low-confidence surface" — a naive whole-section check on "low"
        # would false-positive on that prose.
        remediation_section = body.split("### Record the resolution")[1]
        assert "<high|medium>" in remediation_section
        command = remediation_section.split("```")[1]
        assert "low" not in command

    def test_aging_body_still_prescribes_encoded_as(self) -> None:
        # The aging surface's remediation is unchanged by the low-confidence
        # addition — it still needs an encoding to stop re-firing.
        record = _record("bug-issue:z", confidence="high", encoded_as="none-yet")
        _title, body = _render_finding(record, SURFACE_REASON_AGING)
        assert "--encoded-as" in body
        assert "<regression-test|stored-lesson|detector|adr>" in body

    def test_remediation_map_has_same_keys_as_reason_text_map(self) -> None:
        # Key-parity: every SURFACE_REASON_* covered by the title map must
        # also have a remediation block, or a new reason silently falls back
        # to the wrong (aging) instructions.
        assert set(_SURFACE_REASON_REMEDIATION) == set(_SURFACE_REASON_TEXT)


class TestFindingRateBudget:
    def test_flood_is_capped_at_max_per_tick(self) -> None:
        from datetime import UTC, datetime

        now = datetime(2026, 6, 1, tzinfo=UTC)
        flood = [_record(f"bug-issue:{i}", confidence="low") for i in range(20)]
        eligible = eligible_findings(
            flood,
            now=now,
            aging_threshold_hours=24 * 14,
            already_surfaced=set(),
        )
        to_file, capped = apply_ask_budget(eligible, max_per_tick=3)
        assert len(to_file) == 3
        assert capped is True

    def test_already_surfaced_are_skipped(self) -> None:
        from datetime import UTC, datetime

        now = datetime(2026, 6, 1, tzinfo=UTC)
        # Encoded rows are low-confidence but NOT aging, so only the
        # low-confidence reason is in play — a clean check that a row already
        # surfaced for a reason is skipped for that reason.
        recs = [
            _record("bug-issue:a", encoded_as="regression-test"),
            _record("bug-issue:b", encoded_as="regression-test"),
        ]
        eligible = eligible_findings(
            recs,
            now=now,
            aging_threshold_hours=24 * 14,
            already_surfaced={
                surfacing_fingerprint("bug-issue:a", SURFACE_REASON_LOW_CONFIDENCE)
            },
        )
        to_file, capped = apply_ask_budget(eligible, max_per_tick=5)
        assert {rec.id for rec, _reason in to_file} == {"bug-issue:b"}
        assert {reason for _rec, reason in to_file} == {SURFACE_REASON_LOW_CONFIDENCE}
        assert capped is False

    async def test_surface_stores_reason_scoped_key_and_refires_on_other_reason(
        self, tmp_path: Path
    ) -> None:
        # Issue #10503: a row already surfaced for low-confidence must STILL file
        # an aging finding once it ages, and the caller must store the
        # aging-scoped fingerprint.
        from escape.ledger import EscapeLedger

        repo = _init_repo(tmp_path)
        rid = "bug-issue:aged"
        dedup = _make_dedup({surfacing_fingerprint(rid, SURFACE_REASON_LOW_CONFIDENCE)})
        loop = _make_loop(tmp_path, repo, dedup=dedup)
        # detected long ago + none-yet => aging past the default 14-day threshold.
        EscapeLedger(loop._ledger_path).append(
            _record(rid, confidence="low", encoded_as="none-yet")
        )

        filed, capped = await loop._surface_findings()

        assert filed == 1
        assert capped is False
        loop._prs.create_issue.assert_awaited_once()
        assert surfacing_fingerprint(rid, SURFACE_REASON_AGING) in dedup._store
        # Both reason budgets now spent → next tick files nothing.
        filed_again, _capped = await loop._surface_findings()
        assert filed_again == 0

    async def test_surface_reraises_credit_exhausted(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        pr = MagicMock()
        pr.create_issue = AsyncMock(side_effect=CreditExhaustedError("out"))
        loop = _make_loop(tmp_path, repo, pr_manager=pr)
        from escape.ledger import EscapeLedger

        EscapeLedger(loop._ledger_path).append(_record("bug-issue:x", confidence="low"))

        with pytest.raises(CreditExhaustedError):
            await loop._surface_findings()


# ---------------------------------------------------------------------------
# Auto-diagnose (#11161): every surfacing reason is diagnosed, not just
# SURFACE_REASON_LOW_CONFIDENCE — a reason pre-filter stranded aging rows
# whose encoding was already on disk behind a false human ask.
# ---------------------------------------------------------------------------


class _FakeDiagnoser:
    """Records which records it was asked to diagnose; returns a fixed verdict.

    Per docs/wiki gotcha 1325/testing 2419: injected via the loop's
    ``auto_diagnoser`` constructor param so these tests never fall through to
    the lazily-built production diagnoser's real ``git grep``.
    """

    def __init__(self, verdict: EscapeDiagnosis) -> None:
        self.verdict = verdict
        self.calls: list[EscapeRecord] = []

    async def diagnose(self, record: EscapeRecord) -> EscapeDiagnosis:
        self.calls.append(record)
        return self.verdict


def _make_loop_with_diagnoser(
    tmp_path: Path, repo: Path, diagnoser: _FakeDiagnoser
) -> EscapeLedgerLoop:
    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "escape_ledger_loop_enabled", True)
    return EscapeLedgerLoop(
        config=bg.config,
        pr_manager=MagicMock(),
        state=_make_state(),
        dedup=_make_dedup(),
        deps=bg.loop_deps,
        auto_diagnoser=cast(EscapeAutoDiagnoser, diagnoser),
    )


class TestAutoDiagnoseReasonNeutral:
    async def test_aging_reason_is_diagnosed_not_skipped(self, tmp_path: Path) -> None:
        # AS-IS bug: `_auto_diagnose` skipped any reason other than
        # SURFACE_REASON_LOW_CONFIDENCE, so the diagnoser was never even
        # called for an aging finding.
        repo = _init_repo(tmp_path)
        diagnoser = _FakeDiagnoser(EscapeDiagnosis.INCONCLUSIVE)
        loop = _make_loop_with_diagnoser(tmp_path, repo, diagnoser)
        record = _record("bug-issue:aged", confidence="low", encoded_as="none-yet")

        await loop._auto_diagnose([(record, SURFACE_REASON_AGING)])

        assert diagnoser.calls == [record]

    async def test_resolved_encoded_verdict_drops_aging_finding(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        diagnoser = _FakeDiagnoser(EscapeDiagnosis.RESOLVED_ENCODED)
        loop = _make_loop_with_diagnoser(tmp_path, repo, diagnoser)
        record = _record("bug-issue:aged", confidence="low", encoded_as="none-yet")

        residue = await loop._auto_diagnose([(record, SURFACE_REASON_AGING)])

        assert residue == []

    async def test_dismissed_verdict_drops_aging_finding(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        diagnoser = _FakeDiagnoser(EscapeDiagnosis.DISMISSED)
        loop = _make_loop_with_diagnoser(tmp_path, repo, diagnoser)
        record = _record("bug-issue:aged", confidence="low", encoded_as="none-yet")

        residue = await loop._auto_diagnose([(record, SURFACE_REASON_AGING)])

        assert residue == []

    async def test_inconclusive_verdict_keeps_aging_finding_for_human(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        diagnoser = _FakeDiagnoser(EscapeDiagnosis.INCONCLUSIVE)
        loop = _make_loop_with_diagnoser(tmp_path, repo, diagnoser)
        record = _record("bug-issue:aged", confidence="low", encoded_as="none-yet")

        residue = await loop._auto_diagnose([(record, SURFACE_REASON_AGING)])

        assert residue == [(record, SURFACE_REASON_AGING)]

    async def test_record_eligible_under_both_reasons_is_diagnosed_once(
        self, tmp_path: Path
    ) -> None:
        # A row can be eligible under BOTH SURFACE_REASON_LOW_CONFIDENCE and
        # SURFACE_REASON_AGING in the same tick's `to_file` (#11161 widened
        # `_auto_diagnose` to run for both — previously only low-confidence
        # ever reached this loop, so a record could never appear twice here).
        # Drives the REAL `EscapeAutoDiagnoser` (not `_FakeDiagnoser`, which
        # doesn't persist anything) to prove the second pass short-circuits
        # via `verdict_for` rather than writing a second ledger resolution.
        from escape.auto_diagnose import EscapeDiagnosisLedger

        github = FakeGitHub()
        repo = _init_repo(tmp_path)
        reg = repo / "tests" / "regressions"
        reg.mkdir(parents=True)
        (reg / "test_bug_654.py").write_text(
            "# regression pin for #654\ndef test_bug(): pass\n"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "test: pin regression for #654")
        (repo / "src" / "crash3.py").write_text("def crash3():\n    return 1\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "fix: resolve crash (fixes #654)")
        fix_sha = _head(repo)

        loop = _build_loop_direct(tmp_path, repo, github)
        record = EscapeRecord(
            id=f"bug-issue:{fix_sha}",
            detected_at=datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
            detection_source="bug-issue",
            detection_ref=fix_sha,
            originating_pr=654,
            originating_merge_sha="",
            merged_at="",
            time_to_detection_hours=None,
            attribution_method="fixes-chain",
            attribution_confidence="low",
            encoded_as="none-yet",
            notes="",
        )
        EscapeLedger(loop._ledger_path).append(record)

        residue = await loop._auto_diagnose(
            [
                (record, SURFACE_REASON_LOW_CONFIDENCE),
                (record, SURFACE_REASON_AGING),
            ]
        )

        assert residue == [], (
            "a record resolved under one reason must not surface under the other"
        )
        diagnosis_rows = EscapeDiagnosisLedger(loop._diagnoses_path).read_all()
        assert len(diagnosis_rows) == 1, (
            "the second pass must short-circuit on the recorded verdict, "
            "not re-run the diagnoser and write a second sidecar row"
        )
        resolved = EscapeLedger(loop._ledger_path).read_latest_index()[record.id]
        assert resolved.attribution_confidence == "high"
        assert resolved.encoded_as == "regression-test"


# ---------------------------------------------------------------------------
# escape_ledger_max_diagnoses_per_tick (#11176): bounds the diagnose pass
# itself, separate from and wider than the human ask budget.
# ---------------------------------------------------------------------------


class TestMaxDiagnosesPerTick:
    async def test_diagnoser_is_bounded_by_the_diagnoses_cap(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        diagnoser = _FakeDiagnoser(EscapeDiagnosis.INCONCLUSIVE)
        loop = _make_loop_with_diagnoser(tmp_path, repo, diagnoser)
        object.__setattr__(loop._config, "escape_ledger_max_diagnoses_per_tick", 2)
        eligible = [
            (_record(f"bug-issue:{i}", confidence="low"), SURFACE_REASON_LOW_CONFIDENCE)
            for i in range(5)
        ]

        residue = await loop._auto_diagnose(eligible)

        assert len(diagnoser.calls) == 2, (
            "the diagnoser must only run for the first "
            "escape_ledger_max_diagnoses_per_tick eligible findings"
        )
        assert diagnoser.calls == [rec for rec, _reason in eligible[:2]]
        # Fail-safe: findings beyond the diagnoses cap fall through UNDIAGNOSED
        # (same as an INCONCLUSIVE verdict) rather than being silently dropped —
        # they may still reach a human via the ask-budget cap downstream.
        assert residue == eligible

    async def test_diagnoses_cap_does_not_apply_when_disabled(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        diagnoser = _FakeDiagnoser(EscapeDiagnosis.RESOLVED_ENCODED)
        loop = _make_loop_with_diagnoser(tmp_path, repo, diagnoser)
        object.__setattr__(loop._config, "escape_ledger_max_diagnoses_per_tick", 2)
        object.__setattr__(loop._config, "escape_ledger_auto_diagnose_enabled", False)
        eligible = [
            (_record(f"bug-issue:{i}", confidence="low"), SURFACE_REASON_LOW_CONFIDENCE)
            for i in range(5)
        ]

        residue = await loop._auto_diagnose(eligible)

        assert diagnoser.calls == []
        assert residue == eligible


# ---------------------------------------------------------------------------
# Surfaced-issue link store (#10577): record the filed issue number
# ---------------------------------------------------------------------------


def _build_loop_direct(
    tmp_path: Path,
    repo: Path,
    github: Any,
    *,
    state: MagicMock | None = None,
) -> EscapeLedgerLoop:
    """Build a loop WITHOUT ``_make_loop``'s create_issue AsyncMock override.

    ``_make_loop`` replaces a non-AsyncMock ``create_issue`` with a stub — which
    would clobber a real ``FakeGitHub``. This wires FakeGitHub through untouched.
    """
    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "escape_ledger_loop_enabled", True)
    return EscapeLedgerLoop(
        config=bg.config,
        pr_manager=github,
        state=state if state is not None else _make_state(),
        dedup=_make_dedup(),
        deps=bg.loop_deps,
    )


class TestRecordSurfacedLink:
    async def test_filing_stores_link_with_returned_number(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=9012)
        # encoded => NOT aging, so only the low-confidence reason is eligible.
        loop = _make_loop(tmp_path, repo, pr_manager=pr)
        EscapeLedger(loop._ledger_path).append(
            _record("bug-issue:a", confidence="low", encoded_as="regression-test")
        )

        filed, _capped = await loop._surface_findings()

        assert filed == 1
        (link,) = SurfacedIssueLedger(loop._surfaces_path).open_links()
        assert link.issue_number == 9012
        assert link.escape_id == "bug-issue:a"
        assert link.reason == SURFACE_REASON_LOW_CONFIDENCE

    async def test_row_eligible_under_both_reasons_stores_two_links(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        pr = MagicMock()
        pr.create_issue = AsyncMock(side_effect=[9012, 9013])
        loop = _make_loop(tmp_path, repo, pr_manager=pr)
        EscapeLedger(loop._ledger_path).append(
            _record("bug-issue:a", confidence="low", encoded_as="none-yet")
        )

        filed, _capped = await loop._surface_findings()

        assert filed == 2
        links = SurfacedIssueLedger(loop._surfaces_path).open_links()
        assert {link.issue_number for link in links} == {9012, 9013}
        assert {link.reason for link in links} == {
            SURFACE_REASON_LOW_CONFIDENCE,
            SURFACE_REASON_AGING,
        }

    async def test_zero_return_stores_no_link(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=0)
        loop = _make_loop(tmp_path, repo, pr_manager=pr)
        EscapeLedger(loop._ledger_path).append(
            _record("bug-issue:a", confidence="low", encoded_as="regression-test")
        )

        filed, _capped = await loop._surface_findings()

        assert filed == 0
        assert SurfacedIssueLedger(loop._surfaces_path).open_links() == []

    async def test_links_survive_a_second_loop_instance(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=9012)
        loop = _make_loop(tmp_path, repo, pr_manager=pr)
        EscapeLedger(loop._ledger_path).append(
            _record("bug-issue:a", confidence="low", encoded_as="regression-test")
        )
        await loop._surface_findings()

        # A brand-new loop over the SAME data_root sees the persisted link.
        loop2 = _make_loop(tmp_path, repo)
        links = SurfacedIssueLedger(loop2._surfaces_path).open_links()
        assert [link.issue_number for link in links] == [9012]


# ---------------------------------------------------------------------------
# answered_surfacings (pure reconcile policy)
# ---------------------------------------------------------------------------


class TestAnsweredSurfacings:
    @staticmethod
    def _link(reason: str) -> SurfacedIssue:
        return SurfacedIssue(
            fingerprint=surfacing_fingerprint("bug-issue:a", reason),
            escape_id="bug-issue:a",
            reason=reason,
            issue_number=1,
            filed_at="",
        )

    def test_low_confidence_answered_when_confidence_no_longer_low(self) -> None:
        link = self._link(SURFACE_REASON_LOW_CONFIDENCE)
        rec = _record("bug-issue:a", confidence="high")
        assert answered_surfacings([link], {rec.id: rec}) == [link]

    def test_low_confidence_unanswered_while_still_low(self) -> None:
        link = self._link(SURFACE_REASON_LOW_CONFIDENCE)
        rec = _record("bug-issue:a", confidence="low")
        assert answered_surfacings([link], {rec.id: rec}) == []

    def test_aging_answered_once_encoded(self) -> None:
        link = self._link(SURFACE_REASON_AGING)
        rec = _record("bug-issue:a", confidence="low", encoded_as="detector")
        assert answered_surfacings([link], {rec.id: rec}) == [link]

    def test_aging_unanswered_while_none_yet(self) -> None:
        link = self._link(SURFACE_REASON_AGING)
        rec = _record("bug-issue:a", encoded_as="none-yet")
        assert answered_surfacings([link], {rec.id: rec}) == []

    def test_missing_ledger_row_leaves_link_unanswered(self) -> None:
        link = self._link(SURFACE_REASON_LOW_CONFIDENCE)
        assert answered_surfacings([link], {}) == []


# ---------------------------------------------------------------------------
# _reconcile_surfaced_issues (close stranded HITL issues on resolution)
# ---------------------------------------------------------------------------


class TestReconcileSurfacedIssues:
    async def test_resolution_closes_and_comments_then_is_idempotent(
        self, tmp_path: Path
    ) -> None:
        github = FakeGitHub()
        repo = _init_repo(tmp_path)
        loop = _build_loop_direct(tmp_path, repo, github)
        ledger = EscapeLedger(loop._ledger_path)
        ledger.append(
            _record("bug-issue:a", confidence="low", encoded_as="regression-test")
        )
        await loop._surface_findings()
        (link,) = SurfacedIssueLedger(loop._surfaces_path).open_links()
        num = link.issue_number

        ledger.append_resolution(
            "bug-issue:a",
            encoded_as="regression-test",
            attribution_confidence="high",
        )

        closed = await loop._reconcile_surfaced_issues()
        assert closed == 1
        assert github._issues[num].state == "closed"
        assert any("high" in str(c) for c in github._issues[num].comments)
        comment_count = len(github._issues[num].comments)

        # Terminal: the next reconcile does nothing further for this link.
        assert await loop._reconcile_surfaced_issues() == 0
        assert len(github._issues[num].comments) == comment_count

    async def test_folded_away_low_confidence_surface_closes_on_stronger_sibling(
        self, tmp_path: Path
    ) -> None:
        # #10731: a low-confidence bug-issue is surfaced, then a stronger
        # regression-pin sibling for the SAME commit lands and folds the
        # surfaced id out of read_latest. The reconcile must STILL close the
        # HITL issue — the commit is now attributed off `low` — because it reads
        # through read_latest_index, not the id-projected read_latest view.
        from datetime import UTC, datetime

        github = FakeGitHub()
        repo = _init_repo(tmp_path)
        loop = _build_loop_direct(tmp_path, repo, github)
        ledger = EscapeLedger(loop._ledger_path)
        sha = "d15c0acef00dd15c0acef00dd15c0acef00dd15c"
        fresh = datetime.now(UTC).isoformat()  # not aged => only the LOW surface

        def _row(source: str, confidence: str, method: str) -> EscapeRecord:
            return EscapeRecord(
                id=f"{source}:{sha}",
                detected_at=fresh,
                detection_source=source,
                detection_ref=sha,
                originating_pr=None,
                originating_merge_sha="",
                merged_at="",
                time_to_detection_hours=None,
                attribution_method=method,
                attribution_confidence=confidence,
                encoded_as="none-yet",
                notes="",
            )

        ledger.append(_row("bug-issue", "low", "fixes-chain"))
        await loop._surface_findings()
        (link,) = SurfacedIssueLedger(loop._surfaces_path).open_links()
        assert link.reason == SURFACE_REASON_LOW_CONFIDENCE
        assert link.escape_id == f"bug-issue:{sha}"
        num = link.issue_number

        # Stronger sibling for the same commit (different id, same detection_ref)
        # — folds bug-issue:<sha> out of read_latest.
        ledger.append(_row("regression-pin", "medium", "regression-pin"))
        assert f"bug-issue:{sha}" not in {r.id for r in ledger.read_latest()}

        closed = await loop._reconcile_surfaced_issues()

        assert closed == 1
        assert github._issues[num].state == "closed"
        # The comment names the answering row (the surviving medium sibling).
        assert any("regression-pin" in str(c) for c in github._issues[num].comments)

    async def test_quiet_tick_still_closes_and_reports_closed_count(
        self, tmp_path: Path
    ) -> None:
        github = FakeGitHub()
        repo = _init_repo(tmp_path)
        head = _head(repo)
        loop = _build_loop_direct(tmp_path, repo, github, state=_make_state(head))
        ledger = EscapeLedger(loop._ledger_path)
        ledger.append(
            _record("bug-issue:a", confidence="low", encoded_as="regression-test")
        )
        await loop._surface_findings()
        ledger.append_resolution(
            "bug-issue:a",
            encoded_as="regression-test",
            attribution_confidence="high",
        )

        result = await loop._do_work()

        assert result == {"status": "no_new_commits", "sha": head, "closed": 1}

    async def test_unresolved_escape_issue_left_open(self, tmp_path: Path) -> None:
        github = FakeGitHub()
        repo = _init_repo(tmp_path)
        loop = _build_loop_direct(tmp_path, repo, github)
        ledger = EscapeLedger(loop._ledger_path)
        ledger.append(
            _record("bug-issue:a", confidence="low", encoded_as="regression-test")
        )
        await loop._surface_findings()
        (link,) = SurfacedIssueLedger(loop._surfaces_path).open_links()

        assert await loop._reconcile_surfaced_issues() == 0
        assert github._issues[link.issue_number].state == "open"

    async def test_failing_close_leaves_link_open_for_retry(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=9012)
        pr.post_comment = AsyncMock()
        pr.close_issue = AsyncMock(return_value=False)  # fail-soft, no raise
        loop = _make_loop(tmp_path, repo, pr_manager=pr)
        ledger = EscapeLedger(loop._ledger_path)
        ledger.append(
            _record("bug-issue:a", confidence="low", encoded_as="regression-test")
        )
        await loop._surface_findings()
        ledger.append_resolution(
            "bug-issue:a",
            encoded_as="regression-test",
            attribution_confidence="high",
        )

        closed = await loop._reconcile_surfaced_issues()

        assert closed == 0
        # Link stays OPEN so a later tick retries.
        assert len(SurfacedIssueLedger(loop._surfaces_path).open_links()) == 1

    async def test_credit_exhausted_from_close_propagates(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=9012)
        pr.post_comment = AsyncMock()
        pr.close_issue = AsyncMock(side_effect=CreditExhaustedError("out"))
        loop = _make_loop(tmp_path, repo, pr_manager=pr)
        ledger = EscapeLedger(loop._ledger_path)
        ledger.append(
            _record("bug-issue:a", confidence="low", encoded_as="regression-test")
        )
        await loop._surface_findings()
        ledger.append_resolution(
            "bug-issue:a",
            encoded_as="regression-test",
            attribution_confidence="high",
        )

        with pytest.raises(CreditExhaustedError):
            await loop._reconcile_surfaced_issues()


# ---------------------------------------------------------------------------
# _diagnose_open_links (#11161: retiring an ALREADY-open surfaced issue)
#
# `eligible_findings` drops a (record, reason) pair once its
# reason-scoped fingerprint is spent, so an escape already surfaced never
# reaches `_surface_findings`'s `_auto_diagnose` call again — widening that
# call's reason filter alone cannot retire it. `_reconcile_surfaced_issues`
# must diagnose the escape behind an open link directly.
# ---------------------------------------------------------------------------


class TestDiagnoseOpenLinks:
    async def test_reaches_the_diagnoser_for_an_already_open_link(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        diagnoser = _FakeDiagnoser(EscapeDiagnosis.INCONCLUSIVE)
        loop = _make_loop_with_diagnoser(tmp_path, repo, diagnoser)
        record = _record("bug-issue:aged", confidence="medium")
        EscapeLedger(loop._ledger_path).append(record)
        link = SurfacedIssue(
            fingerprint=surfacing_fingerprint(record.id, SURFACE_REASON_AGING),
            escape_id=record.id,
            reason=SURFACE_REASON_AGING,
            issue_number=1,
            filed_at="",
        )

        await loop._diagnose_open_links([link])

        assert diagnoser.calls == [record], (
            "the escape behind an already-open link must reach the "
            "diagnoser even though it is not in eligible_findings's "
            "eligible set"
        )

    async def test_disabled_by_config_skips_the_diagnoser(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        diagnoser = _FakeDiagnoser(EscapeDiagnosis.RESOLVED_ENCODED)
        loop = _make_loop_with_diagnoser(tmp_path, repo, diagnoser)
        object.__setattr__(loop._config, "escape_ledger_auto_diagnose_enabled", False)
        record = _record("bug-issue:aged", confidence="medium")
        EscapeLedger(loop._ledger_path).append(record)
        link = SurfacedIssue(
            fingerprint=surfacing_fingerprint(record.id, SURFACE_REASON_AGING),
            escape_id=record.id,
            reason=SURFACE_REASON_AGING,
            issue_number=1,
            filed_at="",
        )

        await loop._diagnose_open_links([link])

        assert diagnoser.calls == []

    async def test_terminal_verdict_is_not_re_diagnosed(self, tmp_path: Path) -> None:
        from escape.auto_diagnose import EscapeDiagnosisLedger

        repo = _init_repo(tmp_path)
        diagnoser = _FakeDiagnoser(EscapeDiagnosis.RESOLVED_ENCODED)
        loop = _make_loop_with_diagnoser(tmp_path, repo, diagnoser)
        record = _record("bug-issue:aged", confidence="medium")
        EscapeLedger(loop._ledger_path).append(record)
        EscapeDiagnosisLedger(loop._diagnoses_path).append_diagnosis(
            record.id, EscapeDiagnosis.DISMISSED, "already decided"
        )
        link = SurfacedIssue(
            fingerprint=surfacing_fingerprint(record.id, SURFACE_REASON_AGING),
            escape_id=record.id,
            reason=SURFACE_REASON_AGING,
            issue_number=1,
            filed_at="",
        )

        await loop._diagnose_open_links([link])

        assert diagnoser.calls == []

    async def test_resolved_verdict_from_reconcile_closes_the_open_issue(
        self, tmp_path: Path
    ) -> None:
        # End-to-end within the unit-test fixture: the diagnoser's verdict
        # alone does not close anything — `_record_resolution`'s ledger write
        # is what `answered_surfacings` reacts to. This drives the REAL
        # `EscapeAutoDiagnoser` (via a repo with a matching regression pin) to
        # prove `_reconcile_surfaced_issues` retires an already-open issue.
        github = FakeGitHub()
        repo = _init_repo(tmp_path)
        reg = repo / "tests" / "regressions"
        reg.mkdir(parents=True)
        (reg / "test_bug_321.py").write_text(
            "# regression pin for #321\ndef test_bug(): pass\n"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "test: pin regression for #321")
        (repo / "src" / "crash.py").write_text("def crash():\n    return 1\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "fix: resolve crash (fixes #321)")
        fix_sha = _head(repo)

        # First tick: auto-diagnose OFF — files the AGING surface
        # unconditionally, spending its fingerprint (mirrors the live escape
        # 9196f7403620, surfaced before this diagnoser covered its reason).
        # `_build_loop_direct` (not `_make_loop`) wires the real FakeGitHub
        # through untouched — `_make_loop` would clobber its `create_issue`.
        loop = _build_loop_direct(tmp_path, repo, github)
        object.__setattr__(loop._config, "escape_ledger_auto_diagnose_enabled", False)
        ledger = EscapeLedger(loop._ledger_path)
        old = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
        ledger.append(
            EscapeRecord(
                id=f"bug-issue:{fix_sha}",
                detected_at=old,
                detection_source="bug-issue",
                detection_ref=fix_sha,
                originating_pr=321,
                originating_merge_sha="",
                merged_at="",
                time_to_detection_hours=None,
                attribution_method="fixes-chain",
                attribution_confidence="medium",
                encoded_as="none-yet",
                notes="",
            )
        )
        filed, _capped = await loop._surface_findings()
        assert filed == 1
        (link,) = SurfacedIssueLedger(loop._surfaces_path).open_links()
        assert link.reason == SURFACE_REASON_AGING

        # Second tick: auto-diagnose ON (this fix deployed) — the config
        # default, so no override needed on this fresh loop instance.
        loop2 = _build_loop_direct(tmp_path, repo, github)

        closed = await loop2._reconcile_surfaced_issues()

        assert closed == 1, "widening the reason filter alone cannot retire this"
        assert github._issues[link.issue_number].state == "closed"

    async def test_resolved_verdict_closes_both_reason_links_for_the_same_escape(
        self, tmp_path: Path
    ) -> None:
        # The scenario docs/architecture/aging_auto_diagnose.likec4 documents as
        # this fix's payoff: an escape surfaced under BOTH reasons (a
        # low-confidence HITL issue AND a separate aging HITL issue — the live
        # #10724 / #11161 pair) is diagnosed once by `_diagnose_open_links`
        # (deduped by escape id) and BOTH stranded links close on the same
        # reconcile pass, not just the one that happened to trigger it.
        github = FakeGitHub()
        repo = _init_repo(tmp_path)
        reg = repo / "tests" / "regressions"
        reg.mkdir(parents=True)
        (reg / "test_bug_987.py").write_text(
            "# regression pin for #987\ndef test_bug(): pass\n"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "test: pin regression for #987")
        (repo / "src" / "crash4.py").write_text("def crash4():\n    return 1\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "fix: resolve crash (fixes #987)")
        fix_sha = _head(repo)

        # First tick: auto-diagnose OFF — the row is both low-confidence AND
        # aged past the threshold, so BOTH reasons file separately.
        loop = _build_loop_direct(tmp_path, repo, github)
        object.__setattr__(loop._config, "escape_ledger_auto_diagnose_enabled", False)
        ledger = EscapeLedger(loop._ledger_path)
        old = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
        ledger.append(
            EscapeRecord(
                id=f"bug-issue:{fix_sha}",
                detected_at=old,
                detection_source="bug-issue",
                detection_ref=fix_sha,
                originating_pr=987,
                originating_merge_sha="",
                merged_at="",
                time_to_detection_hours=None,
                attribution_method="fixes-chain",
                attribution_confidence="low",
                encoded_as="none-yet",
                notes="",
            )
        )
        filed, _capped = await loop._surface_findings()
        assert filed == 2
        links = SurfacedIssueLedger(loop._surfaces_path).open_links()
        assert {link.reason for link in links} == {
            SURFACE_REASON_LOW_CONFIDENCE,
            SURFACE_REASON_AGING,
        }

        # Second tick: auto-diagnose ON — one diagnose call resolves the
        # escape; both stranded links must close together.
        loop2 = _build_loop_direct(tmp_path, repo, github)

        closed = await loop2._reconcile_surfaced_issues()

        assert closed == 2, (
            "both reason-scoped links for the resolved escape must close together"
        )
        assert all(
            github._issues[link.issue_number].state == "closed" for link in links
        )


# ---------------------------------------------------------------------------
# loop_fitness
# ---------------------------------------------------------------------------


def test_loop_fitness_is_housekeeping(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from loop_fitness import FitnessContext, FitnessKind

    repo = _init_repo(tmp_path)
    loop = _make_loop(tmp_path, repo)
    now = datetime.now(UTC)
    fitness = loop.loop_fitness(FitnessContext(window_start=now, window_end=now))
    assert fitness.kind == FitnessKind.HOUSEKEEPING
    assert fitness.worker_name == "escape_ledger"


class TestTerminalVerdictQuiescence:
    """#11137/#11144/#11148: a terminal auto-diagnose verdict fully quiesces
    every surface — selection, budget, and stranded HITL links."""

    _NOW = datetime(2026, 8, 14, tzinfo=UTC)

    def test_terminal_ids_excluded_from_selection_all_reasons(self) -> None:
        # One dismissed row eligible under BOTH reasons + one genuine row.
        dismissed = _record("bug-issue:dead", confidence="low")
        genuine = _record("bug-issue:live", confidence="low")
        eligible = eligible_findings(
            [dismissed, genuine],
            now=self._NOW,
            aging_threshold_hours=0.0,  # everything aging-eligible too
            already_surfaced=set(),
            terminal_ids={"bug-issue:dead"},
        )
        to_file, capped = apply_ask_budget(eligible, max_per_tick=10)
        ids = {r.id for r, _ in to_file}
        assert ids == {"bug-issue:live"}
        assert capped is False

    def test_terminal_rows_do_not_occupy_cap_slots(self) -> None:
        # #11137 starvation: with cap=1, a dismissed row must not shadow the
        # genuine finding.
        dismissed = _record("bug-issue:dead", confidence="low")
        genuine = _record("bug-issue:live", confidence="low")
        eligible = eligible_findings(
            [dismissed, genuine],
            now=self._NOW,
            aging_threshold_hours=0.0,
            already_surfaced=set(),
            terminal_ids={"bug-issue:dead"},
        )
        to_file, _ = apply_ask_budget(eligible, max_per_tick=1)
        assert [(r.id, _reason) for r, _reason in to_file][0][0] == "bug-issue:live"

    def test_dismissal_answers_stranded_links(self) -> None:
        # #11148: BOTH surfacing reasons for a dismissed escape are answered,
        # even though the ledger row itself is untouched (low + none-yet).
        low = SurfacedIssue(
            fingerprint=surfacing_fingerprint(
                "bug-issue:a", SURFACE_REASON_LOW_CONFIDENCE
            ),
            escape_id="bug-issue:a",
            reason=SURFACE_REASON_LOW_CONFIDENCE,
            issue_number=1,
            filed_at="",
        )
        aging = SurfacedIssue(
            fingerprint=surfacing_fingerprint("bug-issue:a", SURFACE_REASON_AGING),
            escape_id="bug-issue:a",
            reason=SURFACE_REASON_AGING,
            issue_number=2,
            filed_at="",
        )
        rec = _record("bug-issue:a", confidence="low", encoded_as="none-yet")
        answered = answered_surfacings(
            [low, aging], {rec.id: rec}, {"bug-issue:a": "docs-only commit"}
        )
        assert answered == [low, aging]

    def test_no_dismissals_preserves_legacy_behavior(self) -> None:
        link = SurfacedIssue(
            fingerprint=surfacing_fingerprint("bug-issue:a", SURFACE_REASON_AGING),
            escape_id="bug-issue:a",
            reason=SURFACE_REASON_AGING,
            issue_number=1,
            filed_at="",
        )
        rec = _record("bug-issue:a", encoded_as="none-yet")
        assert answered_surfacings([link], {rec.id: rec}, {}) == []
        assert answered_surfacings([link], {rec.id: rec}) == []
