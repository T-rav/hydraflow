"""Policy-as-code merge gates (CH-3, #9731).

``docs/standards/factory_autonomy/policy.yaml`` is the normative,
machine-readable encoding of the act-vs-ask table in
``docs/standards/factory_autonomy/README.md`` (the prose is commentary;
drift CI binds the two). This module loads and validates that policy and
enforces it at the factory's *own* autonomous merge seams — the places
HydraFlow itself calls ``PRPort.merge_pr`` (post-review Monitor merges, the
PR unsticker, the dependabot/bot-PR loop, epic bundle releases). Human and
terminal merges are NOT intercepted; evidence of those comes from the CH-2
approval-record reconciler.

The one table binding enforced at the merge seam: *"Merge a PR that the
human operator hasn't approved AND the orchestrator's reviewer hasn't
approved"* is high blast radius — an autonomous merge must present at least
one qualifying approval (:class:`MergeApproval`) or the merge is denied and
escalated. Each lane passes the approval evidence it actually has (the
review pipeline's APPROVE verdict, GitHub review approvals, or a standing
operator config grant), so v1 encodes current behavior 1:1 with no new
restrictions; tightening is a policy.yaml edit, not a code change.

Fail-closed contract
--------------------
``load_merge_policy`` raises :class:`MergePolicyError` on a missing or
unparseable policy. Only :func:`enforce_merge_policy` — which is
feature-gated by ``HydraFlowConfig.merge_policy_enabled`` (kill-switch,
default True) — converts that into a deny verdict, so pure consumers can
handle load errors themselves while the enforcement seam fails closed.

Break-glass
-----------
An operator attaches a ``policy-override:<reason-slug>`` label to the PR
(free-form prefix label — intentionally NOT a registered state-machine
label). The gate then allows the merge and appends a ``break_glass`` record
to the CH-2 approval-records audit chain (same hash-chained stream as
``approval`` / ``capture_gap`` records — no forked stream). Break-glass
works even when the policy file itself is corrupt: the override is the
documented recovery path for a broken policy.

Named follow-ups (out of scope here):

* generating GitHub branch-protection rulesets from policy.yaml so the
  platform-side rules and this file cannot drift (see
  docs/standards/branch_protection/);
* gating ``auto_pr``'s best-effort ``gh pr merge --auto`` enablement — that
  lane delegates the merge to GitHub's auto-merge queue (platform-side,
  disabled on this repo), so it belongs with the ruleset follow-up rather
  than an in-process gate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import yaml

import subprocess_util
from approval_records import (
    APPROVAL_RECORD_SCHEMA_VERSION,
    RECORD_TYPE_BREAK_GLASS,
)
from audit_chain import AuditChain
from baseline_policy import glob_match

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from config import HydraFlowConfig
    from ports import PRPort

logger = logging.getLogger("hydraflow.merge_policy")

AUTONOMY_ACT = "act"
AUTONOMY_ASK = "ask"

#: Approval roles the policy schema accepts — mirrors the README table's
#: consent clause ("the human operator" / "the orchestrator's reviewer").
ROLE_OPERATOR = "operator"
ROLE_ORCHESTRATOR_REVIEWER = "orchestrator-reviewer"
_VALID_ROLES = frozenset({ROLE_OPERATOR, ROLE_ORCHESTRATOR_REVIEWER})

#: The action id (in policy.yaml) an approval-less autonomous merge maps to.
UNAPPROVED_MERGE_ACTION = "merge-unapproved-pr"

#: Fallback break-glass prefix used when the policy file is unloadable —
#: the override must keep working precisely when the policy is broken.
DEFAULT_BREAK_GLASS_PREFIX = "policy-override:"

MERGE_POLICY_SCHEMA_VERSION = 1

_VALID_ESCALATIONS = frozenset({"hitl"})
_TOP_LEVEL_KEYS = frozenset({"schema_version", "merge_gate", "classes"})
_MERGE_GATE_KEYS = frozenset(
    {"unapproved_merge_class", "break_glass_label_prefix", "escalation"}
)
_ENTRY_KEYS = frozenset(
    {
        "id",
        "readme_row",
        "autonomy",
        "default",
        "description",
        "actions",
        "paths",
        "labels",
        "required_approvals",
        "forbidden_actors",
        "escalation",
    }
)

# gh timeout tier (see docs/wiki: subprocess timeout tiers — gh=30s).
_GH_TIMEOUT_SECONDS = 30.0


class MergePolicyError(ValueError):
    """The policy file is missing, unparseable, or fails schema validation."""


@dataclass(frozen=True)
class RequiredApprovals:
    """How many approvals an ``ask`` entry needs, and from which roles."""

    count: int
    roles: tuple[str, ...]


@dataclass(frozen=True)
class PolicyEntry:
    """One change class from policy.yaml (one README table row)."""

    id: str
    readme_row: str
    autonomy: str
    default: bool
    description: str
    actions: tuple[str, ...]
    paths: tuple[str, ...]
    labels: tuple[str, ...]
    required_approvals: RequiredApprovals | None
    forbidden_actors: tuple[str, ...]
    escalation: str


@dataclass(frozen=True)
class PolicyDecision:
    """The outcome of classifying one change against the policy."""

    entry_id: str
    autonomy: str
    required_approvals: RequiredApprovals | None
    forbidden_actors: tuple[str, ...]
    escalation: str
    matched: tuple[str, ...]


@dataclass(frozen=True)
class MergeApproval:
    """One piece of approval evidence presented at a merge seam."""

    actor: str
    role: str
    source: str
    basis: str = ""


@dataclass(frozen=True)
class PolicyVerdict:
    """Allow/deny outcome for one autonomous merge attempt."""

    allowed: bool
    reason: str
    decision: PolicyDecision | None = None
    break_glass: bool = False
    break_glass_label: str = ""


def _require_str(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise MergePolicyError(f"{context}: expected a non-empty string, got {value!r}")
    return value


def _str_tuple(value: Any, *, context: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise MergePolicyError(f"{context}: expected a list of strings, got {value!r}")
    return tuple(value)


def _parse_required_approvals(value: Any, *, context: str) -> RequiredApprovals:
    if not isinstance(value, dict) or set(value) != {"count", "roles"}:
        raise MergePolicyError(
            f"{context}: required_approvals needs exactly 'count' and 'roles'"
        )
    count = value["count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise MergePolicyError(f"{context}: count must be an integer >= 1")
    roles = _str_tuple(value["roles"], context=f"{context}.roles")
    unknown_roles = set(roles) - _VALID_ROLES
    if not roles or unknown_roles:
        raise MergePolicyError(
            f"{context}: roles must be a non-empty subset of "
            f"{sorted(_VALID_ROLES)}; got unknown role(s) {sorted(unknown_roles)}"
        )
    return RequiredApprovals(count=count, roles=roles)


def _parse_entry(raw: Any, *, index: int) -> PolicyEntry:
    context = f"classes[{index}]"
    if not isinstance(raw, dict):
        raise MergePolicyError(f"{context}: expected a mapping, got {raw!r}")
    unknown = set(raw) - _ENTRY_KEYS
    if unknown:
        raise MergePolicyError(f"{context}: unknown key(s) {sorted(unknown)}")
    entry_id = _require_str(raw.get("id"), context=f"{context}.id")
    autonomy = _require_str(raw.get("autonomy"), context=f"{context}.autonomy")
    if autonomy not in (AUTONOMY_ACT, AUTONOMY_ASK):
        raise MergePolicyError(
            f"{context}.autonomy: must be '{AUTONOMY_ACT}' or '{AUTONOMY_ASK}', "
            f"got {autonomy!r}"
        )
    required: RequiredApprovals | None = None
    if "required_approvals" in raw:
        required = _parse_required_approvals(raw["required_approvals"], context=context)
    escalation = raw.get("escalation", "")
    if autonomy == AUTONOMY_ASK:
        if required is None:
            raise MergePolicyError(
                f"{context}: an '{AUTONOMY_ASK}' entry must declare required_approvals"
            )
        if escalation not in _VALID_ESCALATIONS:
            raise MergePolicyError(
                f"{context}.escalation: an '{AUTONOMY_ASK}' entry must declare "
                f"an escalation route in {sorted(_VALID_ESCALATIONS)}"
            )
    return PolicyEntry(
        id=entry_id,
        readme_row=_require_str(raw.get("readme_row"), context=f"{context}.readme_row"),
        autonomy=autonomy,
        default=bool(raw.get("default", False)),
        description=str(raw.get("description", "")),
        actions=_str_tuple(raw.get("actions"), context=f"{context}.actions"),
        paths=_str_tuple(raw.get("paths"), context=f"{context}.paths"),
        labels=_str_tuple(raw.get("labels"), context=f"{context}.labels"),
        required_approvals=required,
        forbidden_actors=_str_tuple(
            raw.get("forbidden_actors"), context=f"{context}.forbidden_actors"
        ),
        escalation=str(escalation),
    )


def _decision_from(entry: PolicyEntry, matched: tuple[str, ...]) -> PolicyDecision:
    return PolicyDecision(
        entry_id=entry.id,
        autonomy=entry.autonomy,
        required_approvals=entry.required_approvals,
        forbidden_actors=entry.forbidden_actors,
        escalation=entry.escalation,
        matched=matched,
    )


class MergePolicy:
    """A loaded, schema-valid factory-autonomy policy."""

    def __init__(
        self,
        *,
        entries: tuple[PolicyEntry, ...],
        unapproved_merge_class: str,
        break_glass_label_prefix: str,
        escalation: str,
    ) -> None:
        self.entries = entries
        self.unapproved_merge_class = unapproved_merge_class
        self.break_glass_label_prefix = break_glass_label_prefix
        self.escalation = escalation
        self._by_id = {entry.id: entry for entry in entries}
        self._default = next(entry for entry in entries if entry.default)

    def entry(self, entry_id: str) -> PolicyEntry:
        """Return the entry with *entry_id* (KeyError if absent)."""
        return self._by_id[entry_id]

    @property
    def has_change_matchers(self) -> bool:
        """Whether any entry classifies by path globs or labels.

        When False (the v1 packaged policy), the merge gate can skip
        fetching PR paths/labels entirely on the allow path.
        """
        return any(entry.paths or entry.labels for entry in self.entries)

    def classify_change(
        self, paths: Sequence[str], labels: Sequence[str]
    ) -> PolicyDecision:
        """Classify a change by its file *paths* and PR *labels*.

        Most-restrictive-wins across multiple matches: ``ask`` beats
        ``act``; between ``ask`` entries the higher approval count wins;
        remaining ties keep policy-file order. No match → the ``default``
        entry.
        """
        matches: list[tuple[PolicyEntry, tuple[str, ...]]] = []
        for entry in self.entries:
            matched: list[str] = []
            matched.extend(
                f"path:{path}~{pattern}"
                for pattern in entry.paths
                for path in paths
                if glob_match(path, pattern)
            )
            matched.extend(
                f"label:{label}" for label in entry.labels if label in labels
            )
            if matched:
                matches.append((entry, tuple(matched)))
        if not matches:
            return _decision_from(self._default, ())

        def _strictness(item: tuple[PolicyEntry, tuple[str, ...]]) -> tuple[int, int]:
            entry, _ = item
            required = entry.required_approvals
            return (
                1 if entry.autonomy == AUTONOMY_ASK else 0,
                required.count if required is not None else 0,
            )

        winner, matched_terms = max(matches, key=_strictness)
        return _decision_from(winner, matched_terms)

    def check_merge_allowed(
        self,
        decision: PolicyDecision,
        *,
        actor: str,
        approvals: Sequence[MergeApproval],
    ) -> PolicyVerdict:
        """Check one autonomous merge against the policy.

        Two requirements compose:

        * the classified entry's own ``required_approvals`` when it is an
          ``ask`` entry, and
        * the table's merge binding — presenting NO approval qualifying for
          the ``unapproved_merge_class`` entry makes the merge the
          ``merge-unapproved-pr`` action, which that (``ask``) entry governs.
        """
        if actor and actor in decision.forbidden_actors:
            return PolicyVerdict(
                allowed=False,
                reason=(
                    f"actor {actor!r} is forbidden by policy entry "
                    f"'{decision.entry_id}'"
                ),
                decision=decision,
            )

        requirements: list[PolicyDecision] = []
        if decision.autonomy == AUTONOMY_ASK:
            requirements.append(decision)

        unapproved_entry = self.entry(self.unapproved_merge_class)
        unapproved_required = unapproved_entry.required_approvals
        if unapproved_required is not None and not self._qualifying(
            approvals, unapproved_required
        ):
            requirements.append(
                _decision_from(unapproved_entry, (f"action:{UNAPPROVED_MERGE_ACTION}",))
            )

        for requirement in requirements:
            required = requirement.required_approvals
            if required is None:
                continue
            qualifying = self._qualifying(approvals, required)
            if len(qualifying) < required.count:
                what = (
                    f"action:{UNAPPROVED_MERGE_ACTION}"
                    if requirement.matched
                    and requirement.matched[0].startswith("action:")
                    else f"change class '{requirement.entry_id}'"
                )
                return PolicyVerdict(
                    allowed=False,
                    reason=(
                        f"{what} requires {required.count} approval(s) from "
                        f"role(s) {list(required.roles)}; "
                        f"{len(qualifying)} qualifying approval(s) presented "
                        f"(policy entry '{requirement.entry_id}')"
                    ),
                    decision=requirement,
                )

        return PolicyVerdict(
            allowed=True,
            reason=(
                f"policy entry '{decision.entry_id}' permits the merge with "
                f"{len(approvals)} approval(s) on record"
            ),
            decision=decision,
        )

    @staticmethod
    def _qualifying(
        approvals: Sequence[MergeApproval], required: RequiredApprovals
    ) -> list[MergeApproval]:
        return [a for a in approvals if a.role in required.roles]


def load_merge_policy(path: Path) -> MergePolicy:
    """Load and strictly validate the policy file at *path*.

    Raises :class:`MergePolicyError` on a missing file, unparseable YAML, or
    any schema violation — callers at feature-gated enforcement sites treat
    that as a deny (fail closed).
    """
    if not path.exists():
        raise MergePolicyError(f"policy file missing: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MergePolicyError(f"policy file unreadable/unparseable: {exc}") from exc
    if not isinstance(raw, dict):
        raise MergePolicyError(f"policy root must be a mapping, got {type(raw)}")
    unknown = set(raw) - _TOP_LEVEL_KEYS
    if unknown:
        raise MergePolicyError(f"unknown top-level key(s) {sorted(unknown)}")
    if raw.get("schema_version") != MERGE_POLICY_SCHEMA_VERSION:
        raise MergePolicyError(
            f"unsupported schema_version {raw.get('schema_version')!r} "
            f"(expected {MERGE_POLICY_SCHEMA_VERSION})"
        )

    gate = raw.get("merge_gate")
    if not isinstance(gate, dict):
        raise MergePolicyError("merge_gate: expected a mapping")
    unknown = set(gate) - _MERGE_GATE_KEYS
    if unknown:
        raise MergePolicyError(f"merge_gate: unknown key(s) {sorted(unknown)}")
    unapproved_class = _require_str(
        gate.get("unapproved_merge_class"), context="merge_gate.unapproved_merge_class"
    )
    prefix = _require_str(
        gate.get("break_glass_label_prefix"),
        context="merge_gate.break_glass_label_prefix",
    )
    gate_escalation = _require_str(
        gate.get("escalation"), context="merge_gate.escalation"
    )
    if gate_escalation not in _VALID_ESCALATIONS:
        raise MergePolicyError(
            f"merge_gate.escalation: must be one of {sorted(_VALID_ESCALATIONS)}"
        )

    raw_classes = raw.get("classes")
    if not isinstance(raw_classes, list) or not raw_classes:
        raise MergePolicyError("classes: expected a non-empty list")
    entries = tuple(
        _parse_entry(entry, index=index) for index, entry in enumerate(raw_classes)
    )

    seen_ids: set[str] = set()
    seen_rows: set[str] = set()
    for entry in entries:
        if entry.id in seen_ids:
            raise MergePolicyError(f"duplicate entry id {entry.id!r}")
        if entry.readme_row in seen_rows:
            raise MergePolicyError(f"duplicate readme_row {entry.readme_row!r}")
        seen_ids.add(entry.id)
        seen_rows.add(entry.readme_row)

    defaults = [entry for entry in entries if entry.default]
    if len(defaults) != 1:
        raise MergePolicyError(
            f"exactly one entry must set default: true (found {len(defaults)})"
        )

    unapproved = next((e for e in entries if e.id == unapproved_class), None)
    if unapproved is None or unapproved.autonomy != AUTONOMY_ASK:
        raise MergePolicyError(
            "merge_gate.unapproved_merge_class must reference an "
            f"'{AUTONOMY_ASK}' entry; got {unapproved_class!r}"
        )
    if UNAPPROVED_MERGE_ACTION not in unapproved.actions:
        raise MergePolicyError(
            f"merge_gate.unapproved_merge_class entry {unapproved_class!r} must "
            f"list the {UNAPPROVED_MERGE_ACTION!r} action"
        )

    return MergePolicy(
        entries=entries,
        unapproved_merge_class=unapproved_class,
        break_glass_label_prefix=prefix,
        escalation=gate_escalation,
    )


def find_break_glass_label(labels: Sequence[str], prefix: str) -> str:
    """Return the first ``<prefix><reason-slug>`` label, or "" when absent.

    A bare prefix with no reason slug does not count — the slug is the
    operator's recorded justification.
    """
    for label in labels:
        if label.startswith(prefix) and len(label) > len(prefix):
            return label
    return ""


async def fetch_pr_labels(config: HydraFlowConfig, pr_number: int) -> list[str]:
    """Fresh PR-label read at the gh subprocess boundary.

    Raw gh rather than a new PRPort method (same call and rationale as the
    CH-2 reconciler): break-glass labels are attached by the operator AFTER
    a deny, so the read must not come from a stale snapshot, and the atomic
    Protocol+fake+cassette triplet is not warranted for one read shape.
    """
    raw = await subprocess_util.run_subprocess(
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--repo",
        config.repo,
        "--json",
        "labels",
        timeout=_GH_TIMEOUT_SECONDS,
    )
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise ValueError(f"gh pr view #{pr_number} returned {data!r}")
    return [
        label["name"]
        for label in data.get("labels") or []
        if isinstance(label, dict) and isinstance(label.get("name"), str)
    ]


def _break_glass_record(
    *,
    config: HydraFlowConfig,
    pr_number: int,
    lane: str,
    actor: str,
    label: str,
    prefix: str,
    denied: PolicyVerdict,
) -> dict[str, Any]:
    """Build the ``break_glass`` payload for the CH-2 approval chain."""
    return {
        "schema": APPROVAL_RECORD_SCHEMA_VERSION,
        "record_type": RECORD_TYPE_BREAK_GLASS,
        "repo": config.repo,
        "pr_number": pr_number,
        "timestamp": datetime.now(UTC).isoformat(),
        "lane": lane,
        "actor": actor,
        "override_label": label,
        "reason_slug": label[len(prefix) :],
        "denied_reason": denied.reason,
        "policy_entry": denied.decision.entry_id if denied.decision else "",
    }


async def enforce_merge_policy(
    *,
    config: HydraFlowConfig,
    prs: PRPort,
    pr_number: int,
    actor: str,
    approvals: Sequence[MergeApproval],
    lane: str,
) -> PolicyVerdict:
    """Consult the policy before one autonomous merge (feature-gated).

    Returns an allow/deny :class:`PolicyVerdict`; the calling seam blocks
    the merge and escalates on deny. Fails CLOSED when the policy file is
    missing or invalid — the ``merge_policy_enabled`` kill-switch (and the
    break-glass label) are the escape hatches. Transient gh/port errors
    propagate to the hosting loop's cycle handler (retried next tick).
    """
    if not config.merge_policy_enabled:
        return PolicyVerdict(allowed=True, reason="merge_policy_disabled")

    prefix = DEFAULT_BREAK_GLASS_PREFIX
    labels: list[str] | None = None
    try:
        policy = load_merge_policy(config.merge_policy_path)
    except MergePolicyError as exc:
        verdict = PolicyVerdict(
            allowed=False,
            reason=f"merge policy unloadable — failing closed: {exc}",
        )
    else:
        prefix = policy.break_glass_label_prefix
        paths: list[str] = []
        if policy.has_change_matchers:
            paths = await prs.get_pr_diff_names(pr_number)
            labels = await fetch_pr_labels(config, pr_number)
        decision = policy.classify_change(paths, labels or [])
        verdict = policy.check_merge_allowed(decision, actor=actor, approvals=approvals)

    if verdict.allowed:
        return verdict

    if labels is None:
        labels = await fetch_pr_labels(config, pr_number)
    label = find_break_glass_label(labels, prefix)
    if label:
        record = _break_glass_record(
            config=config,
            pr_number=pr_number,
            lane=lane,
            actor=actor,
            label=label,
            prefix=prefix,
            denied=verdict,
        )
        AuditChain(config.approval_records_path).append(record)
        logger.warning(
            "Merge policy BREAK-GLASS on PR #%d (%s): %r overrides deny "
            "(%s) — recorded on the approval chain.",
            pr_number,
            lane,
            label,
            verdict.reason,
        )
        return PolicyVerdict(
            allowed=True,
            reason=f"break-glass override {label!r} — recorded on the approval chain",
            decision=verdict.decision,
            break_glass=True,
            break_glass_label=label,
        )

    logger.warning(
        "Merge policy DENY on PR #%d (%s, actor %s): %s",
        pr_number,
        lane,
        actor,
        verdict.reason,
    )
    return verdict
