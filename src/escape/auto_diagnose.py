"""Machine auto-diagnose for LOW-CONFIDENCE escape-ledger surfaces (ADR-0115).

Before ``EscapeLedgerLoop`` files a ``SURFACE_REASON_LOW_CONFIDENCE`` finding for
a human, this module runs the move a human used to run by hand (the manual
resolution of #10748 / #10749): trace the escape's ``detection_ref`` commit back
to the bug it fixed, check whether that bug is ALREADY regression-encoded, and

* **real + regression-encoded** → auto-record the ledger resolution at ``high``
  confidence with ``encoded_as = regression-test`` (``escape.resolve``), so the
  low-confidence surface self-answers and no human is bothered;
* **clear false positive** (the referenced issue is plainly not a bug) →
  auto-dismiss with a recorded reason, so the surface is not filed;
* **inconclusive** → fall through to the human surface UNCHANGED.

The pass is deliberately **mechanical** — git reads plus issue-label reads
through the ``PRPort`` — with NO LLM spawn, so it is air-gap-safe and fully
deterministic under test. It is **fail-safe**: the default verdict is
``INCONCLUSIVE`` (→ human), a resolution is recorded only when a concrete
regression encoding is found, and a dismissal only when the referenced issue
carries a non-bug label and no bug label. A genuinely-unresolved real bug is
never auto-closed — it reaches a human exactly as before.

Terminal verdicts (resolved / dismissed) are recorded in an append-only sidecar
``<data_root>/diagnostics/escape_diagnoses.jsonl`` — both the "recorded reason"
audit trail the dismissal path requires and the idempotency guard that stops a
row being re-diagnosed every tick (a resolved row already leaves the
low-confidence set once its ledger confidence is bumped; a dismissed row does
not mutate the ledger, so the sidecar is what keeps it from re-firing).
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from escape import attribution
from escape.detect import commit_info_for_sha
from escape.models import EscapeRecord
from escape.resolve import EscapeResolveError, resolve_escape
from exception_classify import reraise_on_credit_or_bug
from git_timeouts import GIT_READONLY_TIMEOUT_S
from jsonl_ledger import IdentifiedJsonlLedger

if TYPE_CHECKING:
    from ports import PRPort

logger = logging.getLogger("hydraflow.escape_ledger")

__all__ = [
    "DiagnosisEvidence",
    "EscapeAutoDiagnoser",
    "EscapeDiagnosis",
    "EscapeDiagnosisLedger",
    "EscapeDiagnosisRecord",
    "classify_diagnosis",
    "regression_hits",
]

_DIAGNOSES_FILENAME = "escape_diagnoses.jsonl"

_REGRESSION_DIR = "tests/regressions/"
_TESTS_DIR = "tests/"

#: Labels that AFFIRM the referenced issue was a genuine defect — never dismiss
#: one of these (fail-safe: a bug-labelled escape stays a human decision unless
#: a regression encoding resolves it).
_BUG_LABELS: frozenset[str] = frozenset({"bug", "defect", "regression"})

#: Labels that mark the referenced issue as NOT a post-merge defect. A fix
#: commit that closed one of these matched the mechanical ``fix: … fixes #N``
#: signal without fixing an escaped bug — a false positive the diagnose pass may
#: dismiss (only when NO bug label is also present).
_NON_BUG_LABELS: frozenset[str] = frozenset(
    {
        "enhancement",
        "feature",
        "documentation",
        "docs",
        "chore",
        "question",
        "duplicate",
        "invalid",
        "wontfix",
        "wont-fix",
    }
)


class EscapeDiagnosis(StrEnum):
    """The verdict of a machine auto-diagnose pass over one low-confidence row."""

    # Real bug, already regression-encoded → ledger resolution auto-recorded
    # (high confidence, encoded-as regression-test). Surface self-answers.
    RESOLVED_ENCODED = "resolved-encoded"
    # Clear false positive (referenced issue is plainly not a bug) → dismissed
    # with a recorded reason. Surface not filed.
    DISMISSED = "dismissed"
    # Not enough evidence to resolve or dismiss → the human surface is filed,
    # exactly as before. The fail-safe default.
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class DiagnosisEvidence:
    """The mechanical evidence a diagnosis is decided from (pure input).

    ``regression_paths`` are ``tests/regressions/`` (or wider ``tests/``) files
    that reference this bug — a grep hit and/or a pin the detecting commit added
    itself. ``referenced_issue_labels`` / ``referenced_issue_open`` describe the
    bug issue the detecting commit closed (``None`` labels when unread). Kept a
    plain value object so ``classify_diagnosis`` is pure and unit-testable with
    synthetic evidence, no git or GitHub.
    """

    escape_id: str
    regression_paths: tuple[str, ...] = ()
    referenced_issue: int | None = None
    referenced_issue_labels: tuple[str, ...] | None = None
    referenced_issue_open: bool = True


def classify_diagnosis(evidence: DiagnosisEvidence) -> EscapeDiagnosis:
    """Pure rule: map gathered *evidence* to a diagnosis. Fail-safe by default.

    Precedence:

    1. A regression encoding referencing the bug (a ``tests/regressions/`` hit,
       or a pin the detecting commit added) → ``RESOLVED_ENCODED``. This both
       confirms the bug was real (someone wrote a regression test for it) and
       supplies the ``regression-test`` encoding the resolution records.
    2. Otherwise, a referenced issue that is plainly NOT a defect — it carries a
       non-bug label and NO bug label → ``DISMISSED`` (a false positive of the
       mechanical ``fix: … fixes #N`` signal).
    3. Otherwise → ``INCONCLUSIVE``: not enough signal to resolve or dismiss, so
       the finding reaches a human unchanged. A bug-labelled but unencoded
       escape lands here — never dismissed.
    """
    if evidence.regression_paths:
        return EscapeDiagnosis.RESOLVED_ENCODED
    labels = evidence.referenced_issue_labels
    if labels is not None:
        lowered = {label.strip().lower() for label in labels}
        if lowered & _BUG_LABELS:
            return EscapeDiagnosis.INCONCLUSIVE
        if lowered & _NON_BUG_LABELS:
            return EscapeDiagnosis.DISMISSED
    return EscapeDiagnosis.INCONCLUSIVE


def regression_hits(
    repo_root: Path, *, issue_ref: int | None, shas: tuple[str, ...]
) -> tuple[str, ...]:
    """``tests/regressions/`` (then ``tests/``) paths referencing the bug.

    Greps the committed tree for the referenced issue number (as a whole word,
    so ``#123`` / ``issue 123`` match but ``1234`` does not) and for any
    introducing sha. A hit under ``tests/regressions/`` is the strong "already
    regression-encoded" signal; a wider ``tests/`` hit still counts (a
    regression may live outside the canonical dir). Read-only ``git grep`` with
    the same failure-tolerant contract as the rest of the escape git adapters —
    any git failure returns ``()`` (→ no encoding found → not auto-resolved).
    """
    needles: list[tuple[str, bool]] = []
    if issue_ref is not None:
        needles.append((str(issue_ref), True))  # word-boundary match
    needles.extend((sha, False) for sha in shas if sha)
    if not needles:
        return ()
    for scope in (_REGRESSION_DIR, _TESTS_DIR):
        hits = _grep(repo_root, needles, scope)
        if hits:
            return hits
    return ()


def _grep(
    repo_root: Path, needles: list[tuple[str, bool]], pathspec: str
) -> tuple[str, ...]:
    """Return files under *pathspec* matching any needle; ``()`` on git failure.

    Each needle is ``(pattern, word_boundary)``. Fixed-string match (``-F``) so a
    sha or ``#N`` is never treated as a regex; ``-w`` is added per-needle for the
    numeric issue ref so an exact issue number matches but a superstring does
    not. Multiple needles are OR-combined via repeated ``-e``.
    """
    # A word-boundary needle and a plain needle can't share one -F invocation
    # (-w is global), so run word-boundary needles and plain needles separately.
    files: list[str] = []
    for word_boundary in (True, False):
        patterns = [p for p, wb in needles if wb is word_boundary]
        if not patterns:
            continue
        args = ["grep", "-l", "-F", "-I"]
        if word_boundary:
            args.append("-w")
        for pattern in patterns:
            args += ["-e", pattern]
        args += ["HEAD", "--", pathspec]
        out = _run_git(repo_root, args)
        if out:
            files.extend(line.strip() for line in out.split("\n") if line.strip())
    # Dedup, preserve order.
    seen: set[str] = set()
    ordered: list[str] = []
    for path in files:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return tuple(ordered)


def _run_git(repo_root: Path, args: list[str]) -> str | None:
    """Read-only ``git`` call → stdout, or ``None`` on any failure (fail-open).

    ``git grep`` exits 1 when nothing matched — that is NOT an error here, but
    the shared non-zero-is-None contract collapses "no match" and "grep failed"
    to the same ``None`` (both mean "no encoding found", the safe reading).
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_READONLY_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


@dataclass(frozen=True)
class EscapeDiagnosisRecord:
    """One append-only sidecar row: a terminal machine diagnosis for an escape.

    Only ``resolved-encoded`` / ``dismissed`` verdicts are recorded (an
    ``inconclusive`` row is NOT terminal — it may resolve on a later tick once a
    regression lands). ``id`` = the escape id (one terminal diagnosis per
    escape; last-row-wins on the shared ledger base).
    """

    escape_id: str
    diagnosis: str
    reason: str
    decided_at: str

    @property
    def id(self) -> str:
        return self.escape_id

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "escape_id": self.escape_id,
            "diagnosis": self.diagnosis,
            "reason": self.reason,
            "decided_at": self.decided_at,
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> EscapeDiagnosisRecord:
        return cls(
            escape_id=str(raw.get("escape_id", "")),
            diagnosis=str(raw.get("diagnosis", "")),
            reason=str(raw.get("reason", "")),
            decided_at=str(raw.get("decided_at", "")),
        )


class EscapeDiagnosisLedger(IdentifiedJsonlLedger[EscapeDiagnosisRecord]):
    """Append-only reader/writer over the escape auto-diagnose sidecar."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, EscapeDiagnosisRecord, logger=logger)

    def terminal_ids(self) -> set[str]:
        """Escape ids that already carry a terminal (resolved/dismissed) verdict."""
        return set(self.existing_ids())

    def append_diagnosis(
        self, escape_id: str, diagnosis: EscapeDiagnosis, reason: str
    ) -> EscapeDiagnosisRecord:
        row = EscapeDiagnosisRecord(
            escape_id=escape_id,
            diagnosis=diagnosis.value,
            reason=reason,
            decided_at=datetime.now(UTC).isoformat(),
        )
        self.append(row)
        return row


class EscapeAutoDiagnoser:
    """Runs the mechanical auto-diagnose pass for one low-confidence escape.

    Owns the git/GitHub reads and the resolve/dismiss actions; the pure verdict
    is delegated to :func:`classify_diagnosis`. Injected into ``EscapeLedgerLoop``
    only when ``escape_ledger_auto_diagnose_enabled`` is set, so the default
    build is byte-for-byte unchanged.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        prs: PRPort,
        ledger_path: Path,
        diagnoses_path: Path,
    ) -> None:
        self._repo_root = repo_root
        self._prs = prs
        self._ledger_path = ledger_path
        self._diagnoses = EscapeDiagnosisLedger(diagnoses_path)

    async def diagnose(self, record: EscapeRecord) -> EscapeDiagnosis:
        """Diagnose one low-confidence escape; act on a terminal verdict.

        Returns the verdict. ``RESOLVED_ENCODED`` records a ledger resolution
        (high confidence + regression-test encoding) and a sidecar row;
        ``DISMISSED`` records a sidecar row only (no ledger mutation, so a false
        positive never inflates the confirmed-escape count); ``INCONCLUSIVE``
        records nothing and the caller files the human surface. A row already
        carrying a terminal sidecar verdict is skipped (re-returned as its
        recorded verdict) so it is never re-acted on.
        """
        if record.id in self._diagnoses.terminal_ids():
            return EscapeDiagnosis.INCONCLUSIVE
        evidence = await self._gather(record)
        verdict = classify_diagnosis(evidence)
        if verdict is EscapeDiagnosis.RESOLVED_ENCODED:
            await self._record_resolution(record, evidence)
        elif verdict is EscapeDiagnosis.DISMISSED:
            self._record_dismissal(record, evidence)
        return verdict

    async def _gather(self, record: EscapeRecord) -> DiagnosisEvidence:
        """Trace the detecting commit → referenced bug → regression encoding."""
        issue_ref, shas, added_pin = self._trace_commit(record)
        paths: tuple[str, ...] = ()
        if added_pin:
            paths = ("<detecting-commit-regression-pin>",)
        else:
            paths = regression_hits(self._repo_root, issue_ref=issue_ref, shas=shas)
        labels = await self._issue_labels(issue_ref)
        return DiagnosisEvidence(
            escape_id=record.id,
            regression_paths=paths,
            referenced_issue=issue_ref,
            referenced_issue_labels=labels,
        )

    def _trace_commit(
        self, record: EscapeRecord
    ) -> tuple[int | None, tuple[str, ...], bool]:
        """Return (referenced_issue, introducing_shas, detecting_commit_added_pin).

        Re-reads the detecting ``detection_ref`` commit to recover the bug it
        closed (``Fixes #N``) and any introducing sha it named, plus whether the
        commit added its own ``tests/regressions/`` pin. Falls back to the
        already-recorded ``originating_merge_sha`` when the commit can't be read.
        """
        commit = commit_info_for_sha(self._repo_root, record.detection_ref)
        introducing: list[str] = []
        if record.originating_merge_sha:
            introducing.append(record.originating_merge_sha)
        if commit is None:
            return record.originating_pr, tuple(introducing), False
        text = f"{commit.subject}\n{commit.body}"
        fixes = attribution.extract_fixes_refs(text)
        issue_ref = fixes[0] if fixes else record.originating_pr
        for sha in attribution.extract_referenced_shas(commit.body, exclude=commit.sha):
            if sha not in introducing:
                introducing.append(sha)
        added_pin = attribution.adds_regression_pin(commit.added_paths)
        return issue_ref, tuple(introducing), added_pin

    async def _issue_labels(self, issue_ref: int | None) -> tuple[str, ...] | None:
        """Referenced-issue labels via the PRPort, or ``None`` on no ref/failure.

        ``None`` (never an empty tuple on failure) so ``classify_diagnosis``
        distinguishes "unread" from "read, no labels" — an unread issue stays
        INCONCLUSIVE, never dismissed on a guess.
        """
        if issue_ref is None or issue_ref <= 0:
            return None
        try:
            labels = await self._prs.get_issue_labels(issue_ref)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "EscapeAutoDiagnose: could not read labels for issue #%d "
                "(staying inconclusive): %s",
                issue_ref,
                exc,
            )
            return None
        return tuple(labels)

    async def _record_resolution(
        self, record: EscapeRecord, evidence: DiagnosisEvidence
    ) -> None:
        """Auto-record the high-confidence + regression-test ledger resolution."""
        where = ", ".join(evidence.regression_paths) or "regression test"
        reason = (
            f"auto-diagnose (ADR-0115): {record.detection_source} escape "
            f"`{record.detection_ref[:12]}` is a real bug, already "
            f"regression-encoded ({where}); recorded at high confidence, "
            "encoded-as regression-test so the low-confidence surface "
            "self-answers (no human)."
        )
        try:
            resolve_escape(
                record.id,
                "regression-test",
                ledger_path=self._ledger_path,
                attribution_confidence="high",
                notes=reason,
            )
        except EscapeResolveError as exc:
            logger.warning(
                "EscapeAutoDiagnose: resolution write failed for %s "
                "(leaving for human): %s",
                record.id,
                exc,
            )
            return
        self._diagnoses.append_diagnosis(
            record.id, EscapeDiagnosis.RESOLVED_ENCODED, reason
        )
        logger.info("EscapeAutoDiagnose: auto-resolved %s (%s)", record.id, where)

    def _record_dismissal(
        self, record: EscapeRecord, evidence: DiagnosisEvidence
    ) -> None:
        """Record a false-positive dismissal (sidecar only, no ledger mutation)."""
        labels = ", ".join(evidence.referenced_issue_labels or ()) or "none"
        reason = (
            f"auto-diagnose (ADR-0115): {record.detection_source} escape "
            f"`{record.detection_ref[:12]}` closed issue "
            f"#{evidence.referenced_issue}, which is not a defect "
            f"(labels: {labels}); dismissed as a mechanical false positive — "
            "no human surface filed."
        )
        self._diagnoses.append_diagnosis(record.id, EscapeDiagnosis.DISMISSED, reason)
        logger.info(
            "EscapeAutoDiagnose: dismissed %s (referenced #%s not a bug)",
            record.id,
            evidence.referenced_issue,
        )
