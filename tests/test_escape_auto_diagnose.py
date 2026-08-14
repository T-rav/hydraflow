"""Unit tests for the escape-ledger machine auto-diagnose (ADR-0115).

Three layers: the PURE ``classify_diagnosis`` rule over synthetic evidence, the
``regression_hits`` git-grep adapter + ``EscapeAutoDiagnoser`` over a real tiny
git repo with a fake ``PRPort``, and the ``EscapeDiagnosisLedger`` sidecar.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

from escape.auto_diagnose import (
    DiagnosisEvidence,
    EscapeAutoDiagnoser,
    EscapeDiagnosis,
    EscapeDiagnosisLedger,
    classify_diagnosis,
    regression_hits,
)
from escape.ledger import EscapeLedger
from escape.models import EscapeRecord

# --------------------------------------------------------------------------
# Pure classify rule
# --------------------------------------------------------------------------


class TestClassifyDiagnosis:
    def test_regression_encoding_resolves(self) -> None:
        ev = DiagnosisEvidence(
            escape_id="bug-issue:abc",
            regression_paths=("tests/regressions/test_bug.py",),
        )
        assert classify_diagnosis(ev) is EscapeDiagnosis.RESOLVED_ENCODED

    def test_non_bug_label_dismisses(self) -> None:
        ev = DiagnosisEvidence(
            escape_id="bug-issue:abc",
            referenced_issue=7,
            referenced_issue_labels=("documentation",),
        )
        assert classify_diagnosis(ev) is EscapeDiagnosis.DISMISSED

    def test_bug_label_stays_inconclusive_not_dismissed(self) -> None:
        # Fail-safe: a bug-labelled but unencoded escape is NEVER dismissed —
        # it reaches a human unless a regression encoding resolves it.
        ev = DiagnosisEvidence(
            escape_id="bug-issue:abc",
            referenced_issue=7,
            referenced_issue_labels=("bug", "documentation"),
        )
        assert classify_diagnosis(ev) is EscapeDiagnosis.INCONCLUSIVE

    def test_unread_labels_stay_inconclusive(self) -> None:
        # None labels (unread issue / no ref) must not be dismissed on a guess.
        ev = DiagnosisEvidence(escape_id="bug-issue:abc", referenced_issue_labels=None)
        assert classify_diagnosis(ev) is EscapeDiagnosis.INCONCLUSIVE

    def test_read_but_unclassified_labels_stay_inconclusive(self) -> None:
        # Read, but neither a bug nor a known non-bug label → inconclusive.
        ev = DiagnosisEvidence(
            escape_id="bug-issue:abc",
            referenced_issue=7,
            referenced_issue_labels=("needs-triage",),
        )
        assert classify_diagnosis(ev) is EscapeDiagnosis.INCONCLUSIVE

    def test_encoding_wins_over_non_bug_label(self) -> None:
        # A regression encoding is the strongest signal — resolve even if the
        # referenced issue also happens to carry a non-bug label.
        ev = DiagnosisEvidence(
            escape_id="bug-issue:abc",
            regression_paths=("tests/regressions/test_bug.py",),
            referenced_issue=7,
            referenced_issue_labels=("documentation",),
        )
        assert classify_diagnosis(ev) is EscapeDiagnosis.RESOLVED_ENCODED


# --------------------------------------------------------------------------
# git-grep adapter + diagnoser over a real repo
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _head(repo: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@e.dev")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "-m", "init", "--allow-empty")
    return repo


def _commit_regression(repo: Path, issue: int) -> None:
    reg = repo / "tests" / "regressions"
    reg.mkdir(parents=True, exist_ok=True)
    (reg / f"test_bug_{issue}.py").write_text(
        f"# regression pin for #{issue}\ndef test_bug(): pass\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"test: pin regression for #{issue}")


def _commit_bug_fix(repo: Path, issue: int) -> str:
    (repo / "src" / "crash.py").write_text("def crash():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"fix: resolve crash (fixes #{issue})")
    return _head(repo)


def _bug_row(detection_ref: str, issue: int) -> EscapeRecord:
    return EscapeRecord(
        id=f"bug-issue:{detection_ref}",
        detected_at="2026-01-01T00:00:00+00:00",
        detection_source="bug-issue",
        detection_ref=detection_ref,
        originating_pr=issue,
        originating_merge_sha="",
        merged_at="",
        time_to_detection_hours=None,
        attribution_method="fixes-chain",
        attribution_confidence="low",
        encoded_as="none-yet",
        notes=f"Fix commit closing #{issue}.",
    )


class TestRegressionHits:
    def test_finds_issue_reference_in_regressions_dir(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _commit_regression(repo, 123)
        hits = regression_hits(repo, issue_ref=123, shas=())
        assert any("test_bug_123.py" in h for h in hits)

    def test_hits_are_repo_relative_without_rev_prefix(self, tmp_path: Path) -> None:
        """#11138: `git grep -l ... HEAD` prefixes every path with `HEAD:`.
        The adapter strips it so ledger resolution notes and HITL close
        comments record openable repo-relative paths."""
        repo = _init_repo(tmp_path)
        _commit_regression(repo, 123)
        hits = regression_hits(repo, issue_ref=123, shas=())
        assert hits and all(not h.startswith("HEAD:") for h in hits)
        assert hits[0].startswith("tests/regressions/")

    def test_no_hit_returns_empty(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _commit_regression(repo, 123)
        # A different issue number the regression file does not reference.
        assert regression_hits(repo, issue_ref=999, shas=()) == ()

    def test_no_needles_returns_empty(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        assert regression_hits(repo, issue_ref=None, shas=()) == ()


class TestEscapeAutoDiagnoser:
    def _diagnoser(
        self, repo: Path, tmp_path: Path, prs: AsyncMock
    ) -> tuple[EscapeAutoDiagnoser, Path]:
        ledger_path = tmp_path / "escape_ledger.jsonl"
        diagnoses_path = tmp_path / "escape_diagnoses.jsonl"
        return (
            EscapeAutoDiagnoser(
                repo_root=repo,
                prs=prs,
                ledger_path=ledger_path,
                diagnoses_path=diagnoses_path,
            ),
            ledger_path,
        )

    async def test_real_and_encoded_auto_resolves_at_high_confidence(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _commit_regression(repo, 123)
        fix_sha = _commit_bug_fix(repo, 123)

        prs = AsyncMock()
        prs.get_issue_labels = AsyncMock(return_value=[])
        diagnoser, ledger_path = self._diagnoser(repo, tmp_path, prs)
        record = _bug_row(fix_sha, 123)
        EscapeLedger(ledger_path).append(record)

        verdict = await diagnoser.diagnose(record)

        assert verdict is EscapeDiagnosis.RESOLVED_ENCODED
        # The ledger now carries a resolution: high confidence + regression-test,
        # so the low-confidence surface self-answers.
        resolved = EscapeLedger(ledger_path).read_latest()[0]
        assert resolved.attribution_confidence == "high"
        assert resolved.encoded_as == "regression-test"
        assert "auto-diagnose" in resolved.notes.lower()

    async def test_false_positive_non_bug_label_dismisses_without_ledger_mutation(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        # No regression test; the referenced issue is documentation (a false
        # positive of the fix:-fixes-#N signal).
        fix_sha = _commit_bug_fix(repo, 200)

        prs = AsyncMock()
        prs.get_issue_labels = AsyncMock(return_value=["documentation"])
        diagnoser, ledger_path = self._diagnoser(repo, tmp_path, prs)
        record = _bug_row(fix_sha, 200)
        EscapeLedger(ledger_path).append(record)

        verdict = await diagnoser.diagnose(record)

        assert verdict is EscapeDiagnosis.DISMISSED
        # No ledger mutation — a false positive must NOT inflate the confirmed
        # count; the row stays low-confidence, unencoded.
        rows = EscapeLedger(ledger_path).read_all()
        assert len(rows) == 1
        assert rows[0].attribution_confidence == "low"
        # A recorded reason is kept in the sidecar.
        diag = EscapeDiagnosisLedger(tmp_path / "escape_diagnoses.jsonl").read_all()
        assert diag[0].diagnosis == "dismissed"
        assert "false positive" in diag[0].reason.lower()

    async def test_unencoded_bug_labelled_issue_stays_inconclusive(
        self, tmp_path: Path
    ) -> None:
        # Fail-safe: a real bug (bug label) that is NOT yet regression-encoded
        # must reach a human — never auto-resolved and never auto-dismissed.
        repo = _init_repo(tmp_path)
        fix_sha = _commit_bug_fix(repo, 300)

        prs = AsyncMock()
        prs.get_issue_labels = AsyncMock(return_value=["bug"])
        diagnoser, ledger_path = self._diagnoser(repo, tmp_path, prs)
        record = _bug_row(fix_sha, 300)
        EscapeLedger(ledger_path).append(record)

        verdict = await diagnoser.diagnose(record)

        assert verdict is EscapeDiagnosis.INCONCLUSIVE
        rows = EscapeLedger(ledger_path).read_all()
        assert len(rows) == 1 and rows[0].attribution_confidence == "low"

    async def test_terminal_verdict_is_not_re_acted(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        fix_sha = _commit_bug_fix(repo, 400)

        prs = AsyncMock()
        prs.get_issue_labels = AsyncMock(return_value=["documentation"])
        diagnoser, ledger_path = self._diagnoser(repo, tmp_path, prs)
        record = _bug_row(fix_sha, 400)
        EscapeLedger(ledger_path).append(record)

        first = await diagnoser.diagnose(record)
        assert first is EscapeDiagnosis.DISMISSED
        # Second pass: the sidecar terminal id short-circuits with the
        # RECORDED verdict (#11111) — returning INCONCLUSIVE here made the
        # caller re-file the row to a human, so a dismissal bought exactly
        # one tick of quiet. No second sidecar row either way.
        second = await diagnoser.diagnose(record)
        assert second is EscapeDiagnosis.DISMISSED
        diag = EscapeDiagnosisLedger(tmp_path / "escape_diagnoses.jsonl").read_all()
        assert len(diag) == 1


class TestEscapeDiagnosisLedger:
    def test_append_and_terminal_ids(self, tmp_path: Path) -> None:
        ledger = EscapeDiagnosisLedger(tmp_path / "d.jsonl")
        assert ledger.terminal_ids() == set()
        ledger.append_diagnosis("bug-issue:a", EscapeDiagnosis.DISMISSED, "why")
        assert ledger.terminal_ids() == {"bug-issue:a"}
        row = ledger.read_all()[0]
        assert row.diagnosis == "dismissed"
        assert row.reason == "why"
        assert row.decided_at


class TestSidecarVerdictLookup:
    """#11111/#11148: the sidecar answers 'what was decided' — verdict_for
    re-reports the recorded terminal verdict; dismissal_reasons feeds the
    stranded-HITL reconcile pass."""

    def test_verdict_for_returns_recorded_verdict(self, tmp_path: Path) -> None:
        ledger = EscapeDiagnosisLedger(tmp_path / "d.jsonl")
        assert ledger.verdict_for("bug-issue:a") is None
        ledger.append_diagnosis("bug-issue:a", EscapeDiagnosis.DISMISSED, "docs-only")
        verdict = ledger.verdict_for("bug-issue:a")
        assert verdict is not None
        assert verdict[0] is EscapeDiagnosis.DISMISSED
        assert verdict[1] == "docs-only"

    def test_verdict_for_last_row_wins(self, tmp_path: Path) -> None:
        ledger = EscapeDiagnosisLedger(tmp_path / "d.jsonl")
        ledger.append_diagnosis("bug-issue:a", EscapeDiagnosis.DISMISSED, "first")
        ledger.append_diagnosis(
            "bug-issue:a", EscapeDiagnosis.RESOLVED_ENCODED, "second"
        )
        verdict = ledger.verdict_for("bug-issue:a")
        assert verdict is not None
        assert verdict[0] is EscapeDiagnosis.RESOLVED_ENCODED

    def test_dismissal_reasons_maps_only_dismissed(self, tmp_path: Path) -> None:
        ledger = EscapeDiagnosisLedger(tmp_path / "d.jsonl")
        ledger.append_diagnosis("bug-issue:a", EscapeDiagnosis.DISMISSED, "fp")
        ledger.append_diagnosis(
            "bug-issue:b", EscapeDiagnosis.RESOLVED_ENCODED, "encoded"
        )
        assert ledger.dismissal_reasons() == {"bug-issue:a": "fp"}
