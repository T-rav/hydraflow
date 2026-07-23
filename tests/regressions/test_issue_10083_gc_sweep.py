"""Regression: issue-scoped GC sweep gaps beyond #9723 (#10083).

Follow-up from #9723 / PR #10082 (Fix J). That sweep covered
``issue_attempts``, review attempts inside ``convergence_ledgers``, and
``hitl_summary_failures`` — but a full audit of every StateTracker field
keyed by ``str(issue_number)`` (see ``discover_key_indexed_fields`` below)
turned up two more gaps of the exact same shape: a closed issue's state
survives close, so a reopened or re-filed issue inherits it.

1. ``route_back_counts`` / ``review_orphan_strikes`` /
   ``review_orphan_requeues`` — burned route-back and review-orphan penalty
   budget, same "attempt cap" risk class as ``issue_attempts``.
2. ``hitl_origins`` / ``hitl_causes`` / ``hitl_visual_evidence`` — siblings
   of ``hitl_summaries``/``hitl_summary_failures`` inside
   ``HITLStateMixin.clear_hitl_state``; only two of the five fields that
   method clears together had made it into the #9723 sweep.
3. ``diagnostic_attempts`` / ``diagnosis_severities`` — siblings of
   ``escalation_contexts`` inside
   ``DiagnosticStateMixin.clear_diagnostic_state``; only one of the three
   fields that method clears together had made it into the #9723 sweep.

Pins below hold the close-to-clear contract for all eight fields (mirroring
``tests/regressions/test_issue_9723_hitl_reset_residual.py::
TestAttemptCounterCloseToClear``), plus a STRUCTURAL completeness guard:
every StateData field a ``src/state/*.py`` mixin indexes by
``self._key(...)``/``str(...)`` must be either in ``_ISSUE_SCOPED_FIELDS``
(swept) or in this file's ``_GRANDFATHERED_EXCLUSIONS`` (deliberately not
swept, with a reason) — so a NEW issue-keyed counter can't be added without
an explicit sweep decision. See the field-by-field classification in
``_GRANDFATHERED_EXCLUSIONS`` below for why each excluded field is safe to
leave out.
"""

from __future__ import annotations

import ast
from pathlib import Path

from models import AttemptRecord, Severity, VisualEvidence
from state import StateTracker
from state._gc import _ISSUE_SCOPED_FIELDS

_STATE_DIR = Path(__file__).parent.parent.parent / "src" / "state"


# ---------------------------------------------------------------------------
# Structural discovery
# ---------------------------------------------------------------------------
#
# Two conventions are in use across src/state/*.py for indexing a StateData
# dict by issue/PR/epic number: ``self._key(n)`` (the shared helper, whose
# own docstring is "Convert an issue/PR/epic number to the string key used
# in state dicts") and a bare ``str(n)`` call (older mixins that predate
# ``_key``). Both are tracked per-function, including through a local
# ``key = str(n)`` / ``key = self._key(n)`` assignment reused across
# several statements (the dominant style in this codebase) — a purely
# call-site scan would miss those.


def _call_kind(node: ast.AST) -> str | None:
    """Classify *node* as a ``self._key(...)`` or ``str(...)`` call, else None."""
    if not isinstance(node, ast.Call):
        return None
    fname = None
    if isinstance(node.func, ast.Attribute):
        fname = node.func.attr
    elif isinstance(node.func, ast.Name):
        fname = node.func.id
    if fname == "_key":
        return "self._key(...)"
    if fname == "str":
        return "str(...)"
    return None


def _data_field(node: ast.AST) -> str | None:
    """If *node* is ``self._data.FIELD``, return ``FIELD``."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
        inner = node.value
        if (
            isinstance(inner.value, ast.Name)
            and inner.value.id == "self"
            and inner.attr == "_data"
        ):
            return node.attr
    return None


def discover_key_indexed_fields() -> dict[str, set[str]]:
    """Return ``{field_name: {conventions used}}`` for every StateData dict
    a ``src/state/*.py`` mixin indexes by ``self._key(...)`` or ``str(...)``,
    directly or via a local variable assigned from one of those calls.

    This is the structural source of truth the completeness guard below
    checks ``_ISSUE_SCOPED_FIELDS`` and ``_GRANDFATHERED_EXCLUSIONS``
    against — it does not know which fields are safe to prune, only which
    fields use the issue/PR/epic-number-keyed convention at all.
    """
    results: dict[str, set[str]] = {}
    for path in sorted(_STATE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            local_kind: dict[str, str] = {}
            for node in ast.walk(func):
                if (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                ):
                    kind = _call_kind(node.value)
                    if kind:
                        local_kind[node.targets[0].id] = kind
            for node in ast.walk(func):
                field = None
                key_expr: ast.AST | None = None
                if isinstance(node, ast.Subscript):
                    field = _data_field(node.value)
                    key_expr = node.slice
                elif isinstance(node, ast.Call) and isinstance(
                    node.func, ast.Attribute
                ):
                    if node.func.attr in ("get", "pop", "setdefault") and node.args:
                        field = _data_field(node.func.value)
                        key_expr = node.args[0]
                elif isinstance(node, ast.Compare):
                    for op, comparator in zip(node.ops, node.comparators, strict=True):
                        if isinstance(op, ast.In | ast.NotIn):
                            field = _data_field(comparator)
                            key_expr = node.left
                if field is None or key_expr is None:
                    continue
                kind = _call_kind(key_expr)
                if kind is None and isinstance(key_expr, ast.Name):
                    kind = local_kind.get(key_expr.id)
                if kind:
                    results.setdefault(field, set()).add(kind)
    return results


# ---------------------------------------------------------------------------
# Grandfathered exclusions
# ---------------------------------------------------------------------------
#
# Every field discover_key_indexed_fields() finds that is NOT in
# _ISSUE_SCOPED_FIELDS must be listed here with a reason. The guard fails on
# anything unclassified — a new issue/PR/epic-keyed field added to
# src/state/*.py must land in one bucket or the other, not silently in
# neither.

_GRANDFATHERED_EXCLUSIONS: dict[str, str] = {
    # --- own dedicated cleanup path (not this sweep's job) ---
    "active_branches": (
        "Cleared by IssueStateMixin.mark_issue() on the _WORKSPACE_CLEAR_STATUSES "
        "transition, AND is a load-bearing pointer into WorkspaceGCLoop's "
        "filesystem-level worktree/branch reclamation. Popping the state entry "
        "here (without WorkspaceGCLoop's is_safe_to_gc checks) would orphan a "
        "worktree with no tracking entry rather than actually reclaim it."
    ),
    "active_workspaces": (
        "Same as active_branches: cleared via mark_issue() on terminal-status "
        "transition, and a WorkspaceGCLoop-owned pointer, not GC-sweep-owned."
    ),
    "auto_agent_redrive": (
        "Own reconcile path — models.py: 'cleared on issue close (reconcile) or "
        "when the issue drops out of the human-required set.' Owned by "
        "AutoAgentPreflightLoop, not this sweep."
    ),
    "corpus_learning_validation_attempts": (
        "CorpusLearningStateMixin.reset_corpus_validation_attempts() is 'invoked "
        "when the escalation issue closes (spec §3.2 lifecycle)' — CorpusLearningLoop "
        "owns its own close-to-clear reconcile."
    ),
    "dependabot_arch_refresh_attempts": (
        "PR-numbered, not issue-numbered (models.py: 'Cleared when the PR is "
        "merged/closed', owned by DependabotMergeLoop). Sweeping via the issue "
        "keep-set would be wrong-keyspace: PR numbers essentially never coincide "
        "with open issue numbers, so this would be wiped almost every tick."
    ),
    "dependabot_update_branch_attempts": (
        "Same wrong-keyspace risk as dependabot_arch_refresh_attempts: PR-numbered, "
        "owned by DependabotMergeLoop's own PR-merge/close cleanup."
    ),
    "triage_retry_attempts": (
        "TriageRetryStateMixin docstring: 'Cleared when the issue closes "
        "(reconciled in the loop)' — TriageRetryLoop owns its own close-to-clear "
        "reconcile against live issue state."
    ),
    "triage_retry_last_attempt": (
        "Cleared alongside triage_retry_attempts by TriageRetryStateMixin."
        "clear_triage_retry_attempts(), same TriageRetryLoop-owned reconcile."
    ),
    "triage_infra_parked": (
        "#10290: cleared alongside triage_retry_attempts by "
        "TriageRetryStateMixin.clear_triage_retry_attempts() (which now also "
        "drops the infra marker) on the same TriageRetryLoop-owned close-to-clear "
        "reconcile. It's a transient per-park marker, not durable per-issue "
        "state, and is also re-classified on every re-triage."
    ),
    # --- wrong keyspace: PR-keyed, not issue-keyed ---
    "reviewed_prs": (
        "Keyed by pr_number (IssueStateMixin.mark_pr), not issue_number. PR "
        "numbers essentially never coincide with open issue numbers in the "
        "GitHub-truth keep-set this sweep uses, so sweeping this field via the "
        "issue keep-set would incorrectly wipe live PR review state almost "
        "every tick — needs its own PR-truth keep-set, out of scope here."
    ),
    # --- epic-keyed: distinct multi-issue rollup identity + destructive risk ---
    "epic_states": (
        "Keyed by epic_number and holds substantive multi-child rollup state "
        "(completed_children/failed_children/approved_children), not a "
        "resettable attempt counter. Clearing on close would destroy legitimate "
        "rollup history rather than fix a leak — a correctness regression, not "
        "a bug fix."
    ),
    "releases": (
        "Keyed by epic_number (Release.epic_number), same rollup-history risk "
        "as epic_states — deliberately not swept."
    ),
    # --- not a counter: audit trail / historical record, meant to outlive close ---
    "issue_outcomes": (
        "Terminal-outcome audit record (what happened + when), read by "
        "dashboards/reporting after close. Deleting it on close would erase the "
        "history the field exists to preserve — the opposite of a leak fix."
    ),
    "completed_timelines": (
        "Post-completion lifecycle timing record (used for cycle-time "
        "reporting), only ever written AT completion, already bounded "
        "(_MAX_COMPLETED_TIMELINES=500, oldest-evicted). Clearing it on close "
        "would destroy the record it exists to keep."
    ),
    "hook_failures": (
        "Bounded (_MAX_HOOK_FAILURES=500 per issue) historical debugging trail "
        "of git-hook failures, not a budget/penalty counter."
    ),
    "verification_issues": (
        "Reference mapping (original issue -> spawned verification-issue "
        "number) with its own resolve-triggered clear_verification_issue() "
        "call; not a counter."
    ),
    "digest_hashes": (
        "Provenance stamp (memory digest hash active when the issue started "
        "implementation), not a counter."
    ),
    "bead_mappings": (
        "Phase -> external bead-ID lookup, not an attempt/penalty counter. "
        "Reuse-on-reopen of stale bead IDs is a distinct correctness question "
        "from budget leakage, tracked separately."
    ),
    "processed_issues": (
        "Status ledger (idempotency marker — e.g. 'decomposed' — read by "
        "decompose-to-converge idempotency checks), not a counter/budget. "
        "Clearing it on close would let a reopened issue re-trigger "
        "already-completed idempotent side effects — a distinct product "
        "decision, out of scope for the attempt-cap sweep."
    ),
    "worker_result_meta": (
        "Per-issue worker execution metadata cache. Not identified as a "
        "budget/penalty risk by this audit — no evidence anything reads it as "
        "a re-open penalty. Candidate for a future audit pass, not required by "
        "this issue's counter-leak report."
    ),
    "baseline_audit": (
        "Bounded (_MAX_BASELINE_AUDIT_RECORDS=100) audit trail of baseline "
        "changes/rollbacks, not a counter."
    ),
    "shape_conversations": (
        "Multi-turn design-conversation cache, overwritten fresh whenever the "
        "shape phase re-runs on reopen (set_shape_conversation upserts) — not "
        "a monotonic counter, so a stale entry doesn't misapply budget. "
        "Disk-bloat-only risk, same class as the pre-#9905 adversarial_states "
        "leak but not named in this issue's report."
    ),
    "shape_responses": (
        "Pending human response for a shape conversation, same overwritten- "
        "fresh-on-reopen reasoning as shape_conversations."
    ),
    "last_reviewed_shas": (
        "Review-cycle cache (last SHA reviewed), overwritten each review pass "
        "— not a counter, so a stale value doesn't compound like an attempt "
        "counter does."
    ),
    "review_feedback": (
        "Review-cycle cache, same overwritten-fresh-on-reopen reasoning as "
        "last_reviewed_shas."
    ),
}


def test_every_issue_keyed_field_is_classified() -> None:
    """Ratchet: a NEW self._key()/str()-indexed StateData field must be
    either swept (_ISSUE_SCOPED_FIELDS) or excluded with a reason
    (_GRANDFATHERED_EXCLUSIONS) — never silently neither."""
    found = set(discover_key_indexed_fields())
    swept = set(_ISSUE_SCOPED_FIELDS)
    excluded = set(_GRANDFATHERED_EXCLUSIONS)

    unclassified = sorted(found - swept - excluded)
    assert not unclassified, (
        "New issue/PR/epic-keyed StateData field(s) with no sweep decision: "
        f"{unclassified}. A closed issue's entry in this field will survive "
        "the close-to-clear GC sweep and leak into a reopened/re-filed issue "
        "unless that's genuinely fine — add the field to _ISSUE_SCOPED_FIELDS "
        "in src/state/_gc.py (with a retained-while-open + cleared-on-close "
        "pin) or to _GRANDFATHERED_EXCLUSIONS here with a reason."
    )

    overlap = sorted(swept & excluded)
    assert not overlap, (
        f"Field(s) both swept and excluded — contradictory classification: {overlap}."
    )

    stale_exclusions = sorted(excluded - found)
    assert not stale_exclusions, (
        f"_GRANDFATHERED_EXCLUSIONS has entries the structural scan no longer "
        f"finds: {stale_exclusions}. Either the field was renamed/removed "
        "(update or drop the entry) or it no longer uses the "
        "self._key()/str() convention (re-verify by hand before dropping it)."
    )

    undiscovered_sweep_fields = sorted(swept - found)
    assert not undiscovered_sweep_fields, (
        f"_ISSUE_SCOPED_FIELDS lists field(s) the structural scan can't find "
        f"indexed by self._key()/str(): {undiscovered_sweep_fields}. Either "
        "the field was renamed or it never used the issue-number-keyed "
        "convention prune_issue_scoped_state relies on — verify by hand."
    )


# ---------------------------------------------------------------------------
# Close-to-clear pins
# ---------------------------------------------------------------------------


class TestRouteBackAndReviewOrphanCloseToClear:
    """route_back_counts / review_orphan_strikes / review_orphan_requeues."""

    def _tracker(self, tmp_path: Path) -> StateTracker:
        tracker = StateTracker(tmp_path / "state.json")
        for issue in (100, 999):
            tracker.increment_route_back_count(issue)
            tracker.increment_route_back_count(issue)
            tracker.increment_review_orphan_strike(issue)
            tracker.increment_review_orphan_requeue(issue)
        return tracker

    def test_closed_issue_counters_are_cleared(self, tmp_path: Path) -> None:
        tracker = self._tracker(tmp_path)

        removed = tracker.prune_issue_scoped_state({100})

        assert removed["route_back_counts"] == 1
        assert removed["review_orphan_strikes"] == 1
        assert removed["review_orphan_requeues"] == 1
        assert set(tracker._data.route_back_counts) == {"100"}
        assert set(tracker._data.review_orphan_strikes) == {"100"}
        assert set(tracker._data.review_orphan_requeues) == {"100"}

    def test_open_issue_counters_survive_sweep(self, tmp_path: Path) -> None:
        tracker = self._tracker(tmp_path)

        removed = tracker.prune_issue_scoped_state({100, 999})

        assert removed == {}
        assert set(tracker._data.route_back_counts) == {"100", "999"}
        assert set(tracker._data.review_orphan_strikes) == {"100", "999"}
        assert set(tracker._data.review_orphan_requeues) == {"100", "999"}

    def test_cleared_counters_persist_to_disk(self, tmp_path: Path) -> None:
        """A reopened issue must see fresh budget even across a restart."""
        tracker = self._tracker(tmp_path)
        tracker.save()

        tracker.prune_issue_scoped_state({100})

        reloaded = StateTracker(tmp_path / "state.json")
        assert set(reloaded._data.route_back_counts) == {"100"}
        assert set(reloaded._data.review_orphan_strikes) == {"100"}
        assert set(reloaded._data.review_orphan_requeues) == {"100"}
        assert reloaded.get_route_back_count(999) == 0
        assert reloaded.get_review_orphan_requeues(999) == 0


class TestHitlSiblingFieldsCloseToClear:
    """hitl_origins / hitl_causes / hitl_visual_evidence — the three
    clear_hitl_state() siblings the #9723 sweep left out."""

    def _tracker(self, tmp_path: Path) -> StateTracker:
        tracker = StateTracker(tmp_path / "state.json")
        for issue in (100, 999):
            tracker.set_hitl_origin(issue, "needs-review")
            tracker.set_hitl_cause(issue, "merge conflict")
            tracker.set_hitl_visual_evidence(issue, VisualEvidence(summary="diff"))
        return tracker

    def test_closed_issue_fields_are_cleared(self, tmp_path: Path) -> None:
        tracker = self._tracker(tmp_path)

        removed = tracker.prune_issue_scoped_state({100})

        assert removed["hitl_origins"] == 1
        assert removed["hitl_causes"] == 1
        assert removed["hitl_visual_evidence"] == 1
        assert set(tracker._data.hitl_origins) == {"100"}
        assert set(tracker._data.hitl_causes) == {"100"}
        assert set(tracker._data.hitl_visual_evidence) == {"100"}

    def test_open_issue_fields_survive_sweep(self, tmp_path: Path) -> None:
        tracker = self._tracker(tmp_path)

        removed = tracker.prune_issue_scoped_state({100, 999})

        assert removed == {}
        assert set(tracker._data.hitl_origins) == {"100", "999"}
        assert set(tracker._data.hitl_causes) == {"100", "999"}
        assert set(tracker._data.hitl_visual_evidence) == {"100", "999"}

    def test_cleared_fields_persist_to_disk(self, tmp_path: Path) -> None:
        tracker = self._tracker(tmp_path)
        tracker.save()

        tracker.prune_issue_scoped_state({100})

        reloaded = StateTracker(tmp_path / "state.json")
        assert set(reloaded._data.hitl_origins) == {"100"}
        assert set(reloaded._data.hitl_causes) == {"100"}
        assert set(reloaded._data.hitl_visual_evidence) == {"100"}
        assert reloaded.get_hitl_origin(999) is None
        assert reloaded.get_hitl_cause(999) is None
        assert reloaded.get_hitl_visual_evidence(999) is None


class TestDiagnosticSiblingFieldsCloseToClear:
    """diagnostic_attempts / diagnosis_severities — the two
    clear_diagnostic_state() siblings the #9723 sweep left out
    (escalation_contexts, the third, was already covered)."""

    def _tracker(self, tmp_path: Path) -> StateTracker:
        tracker = StateTracker(tmp_path / "state.json")
        for issue in (100, 999):
            tracker.add_diagnostic_attempt(
                issue,
                AttemptRecord(
                    attempt_number=1,
                    changes_made=True,
                    error_summary="fixed the flake",
                    timestamp="2026-07-20T00:00:00Z",
                ),
            )
            tracker.set_diagnosis_severity(issue, Severity.P2_FUNCTIONAL)
        return tracker

    def test_closed_issue_fields_are_cleared(self, tmp_path: Path) -> None:
        tracker = self._tracker(tmp_path)

        removed = tracker.prune_issue_scoped_state({100})

        assert removed["diagnostic_attempts"] == 1
        assert removed["diagnosis_severities"] == 1
        assert set(tracker._data.diagnostic_attempts) == {"100"}
        assert set(tracker._data.diagnosis_severities) == {"100"}

    def test_open_issue_fields_survive_sweep(self, tmp_path: Path) -> None:
        tracker = self._tracker(tmp_path)

        removed = tracker.prune_issue_scoped_state({100, 999})

        assert removed == {}
        assert set(tracker._data.diagnostic_attempts) == {"100", "999"}
        assert set(tracker._data.diagnosis_severities) == {"100", "999"}

    def test_cleared_fields_persist_to_disk(self, tmp_path: Path) -> None:
        tracker = self._tracker(tmp_path)
        tracker.save()

        tracker.prune_issue_scoped_state({100})

        reloaded = StateTracker(tmp_path / "state.json")
        assert set(reloaded._data.diagnostic_attempts) == {"100"}
        assert set(reloaded._data.diagnosis_severities) == {"100"}
        assert reloaded.get_diagnostic_attempts(999) == []
        assert reloaded.get_diagnosis_severity(999) is None
