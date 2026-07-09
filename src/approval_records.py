"""Merge approval records — structured, role-separated sign-off evidence (CH-2, #9730).

Regulated change control (SOX ITGC segregation of duties, 21 CFR Part 11,
EU AI Act human oversight) wants durable evidence of WHO approved WHAT, in
WHICH role, against WHICH artifact state. Merges already happen through
three lanes — an operator's terminal ``gh pr merge``, Monitor-driven merges,
and ``StagingPromotionLoop`` RC cuts — none of which can be intercepted
without adding friction. So capture is a **reconciler**: a post-hoc caretaker
tick (hosted by ``MergeStateWatcherLoop``, the source-agnostic PR-state
caretaker) that polls recently merged PRs and appends one approval record
per merge to a hash-chained JSONL stream (CH-1 ``AuditChain``; the stream is
registered in :func:`audit_chain.audit_streams`, so ``RunsGCLoop``'s existing
verify/retention tick covers it automatically).

Capture-point choice
--------------------
``MergeStateWatcherLoop`` over ``StagingPromotionLoop`` because:

* ``StagingPromotionLoop`` is gated by ``staging_enabled`` and only tends the
  staging→main promotion lane — with staging off (or for direct merges to
  staging) it would record nothing.
* ``MergeStateWatcherLoop`` is already the source-agnostic merge-state
  caretaker (RC, dependabot, agent, and manual PRs alike) on a 10-minute
  tick — prompt capture across every lane, including RC promotion PRs.

Identity source
---------------
The **merge event's actor** — ``mergedBy.login`` from GitHub's PR API — is
the approver identity. It is populated by GitHub for every merge regardless
of lane, so it works for human merges AND bot-lane merges. ``gh api user``
only identifies the *reconciler's own token*, so it is used solely to learn
the factory's login for role classification, never as the approver.

Role classification
-------------------
* ``orchestrator`` — an RC promotion (head ``rc/*`` onto the main branch)
  merged by the factory itself (ADR-0042). A human force-merging an RC PR
  records ``operator`` — branch shape alone never grants the role.
* ``delegated-bot`` — merged by the factory's own token identity or by a
  GitHub App actor (``mergedBy.is_bot``): the bot lane operating under the
  delegated authority of :data:`FACTORY_AUTONOMY_CLAUSE`.
* ``operator`` — any other (named human) login. A missing ``mergedBy``
  (deleted account) records ``approver_identity=""`` with
  ``role_separated=False`` — visibly unattributed rather than guessed.

``role_separated`` (``author_identity != approver_identity``) is recorded as
**evidence, not enforcement** — CH-3 owns gating on it.

Follow-up (out of v1 scope)
---------------------------
*Signature-grade records* — signing each approval record with the SSH/GPG
key already present for commit signing (21 CFR Part 11 e-signature targets)
is the named CH-2 follow-up; v1 relies on the CH-1 hash chain's tamper
evidence only.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import subprocess_util
from audit_chain import AuditChain
from exception_classify import exc_detail
from subprocess_util import AuthenticationError, CreditExhaustedError

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.approval_records")

#: Bump when the record shape changes incompatibly.
APPROVAL_RECORD_SCHEMA_VERSION = 1

#: Authorizing standard clause recorded on delegated-bot merges: the operator
#: delegated merge authority for factory lanes under the autonomy directive.
FACTORY_AUTONOMY_CLAUSE = (
    "docs/standards/factory_autonomy/README.md#the-directive — "
    "tractable + reversible: act first and report (operator grant 2026-05-07)"
)

ROLE_OPERATOR = "operator"
ROLE_ORCHESTRATOR = "orchestrator"
ROLE_DELEGATED_BOT = "delegated-bot"

# gh timeout tier (see docs/wiki: subprocess timeout tiers — gh=30s).
_GH_TIMEOUT_SECONDS = 30.0

# How many recently-merged PRs one tick scans (updated-desc). Bounds the
# backlog the reconciler can self-heal after downtime; merges older than the
# newest N are not backfilled (same adoption-baseline principle as CH-1).
# Continuity is checked per tick: zero overlap between the window and the
# recorded stream chains a ``capture_gap`` marker (see :meth:`reconcile`).
# Residual risk: ``sort:updated-desc`` can displace a fresh merge out of the
# window when old recorded PRs get updated — a cursor-based scan keyed on
# the last recorded ``merged_at`` is the named v2 follow-up.
_MERGED_PR_SCAN_LIMIT = 50

#: ``record_type`` discriminators on the chained stream: normal approval
#: evidence, the capture-gap marker (continuity unprovable this tick), and
#: CH-3 (#9731) break-glass overrides (a ``policy-override:<reason-slug>``
#: label authorizing a merge the policy would deny — written by
#: :func:`merge_policy.enforce_merge_policy`, same stream, no fork).
RECORD_TYPE_APPROVAL = "approval"
RECORD_TYPE_CAPTURE_GAP = "capture_gap"
RECORD_TYPE_BREAK_GLASS = "break_glass"

# Cap on CI check refs stored per record — evidence refs, not a CI mirror.
_MAX_CI_CHECK_REFS = 50

_DETAIL_JSON_FIELDS = (
    "number,title,author,baseRefName,headRefName,headRefOid,mergeCommit,"
    "mergedAt,mergedBy,reviews,reviewDecision,statusCheckRollup,url"
)


def _login(actor: Any) -> str:
    """Extract a login from a gh actor object (``{"login": ...}`` or None)."""
    if isinstance(actor, dict):
        login = actor.get("login")
        if isinstance(login, str):
            return login
    return ""


def _parse_merged_at(value: Any) -> datetime | None:
    """Parse gh's ISO-8601 ``mergedAt`` (``...Z``); ``None`` if unparseable."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


class ApprovalRecordReconciler:
    """Idempotent post-hoc reconciler: merged PR → chained approval record.

    Zero friction by design — it never touches the merge flows themselves.
    Dedup is a read-back of ``pr_number`` from the stream (single source of
    truth; no side store to drift). gh failures propagate to the hosting
    loop's cycle handler; partial progress is already appended and the next
    tick self-heals the remainder.
    """

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config
        self._chain = AuditChain(config.approval_records_path)

    async def reconcile(self) -> dict[str, Any]:
        """One tick: record every recently merged PR not yet in the stream."""
        if self._config.dry_run:
            return {"status": "dry_run"}
        if not self._config.approval_records_enabled:
            return {"status": "config_disabled"}

        merged = await self._list_recently_merged()
        recorded = self._recorded_pr_numbers()
        # Set-dedup guards against a duplicate number inside ONE list payload
        # (read-back only covers records appended on PREVIOUS ticks).
        scanned = {
            number
            for number in (entry.get("number") for entry in merged)
            if isinstance(number, int)
        }
        # Retention interplay (CH-1): pruning deletes old approval records,
        # but old PRs re-enter the sort:updated-desc window whenever they are
        # labeled/commented. Evidence the operator chose to expire must not
        # be re-minted with a fresh timestamp, so retention-expired merges
        # never enter todo. The continuity check below still uses the FULL
        # scanned set: an expired-but-not-yet-pruned recorded PR remains a
        # valid continuity anchor.
        fresh = self._filter_retention_expired(merged)
        todo = sorted(fresh - recorded)
        # Continuity check: with every scanned PR unrecorded and a non-empty
        # stream, merges may have passed the window horizon unrecorded. The
        # gap becomes chained evidence — silence would let ``verify()`` pass
        # on a materially incomplete record set. (An empty stream is the
        # documented adoption baseline, not a gap.)
        gap_risk = bool(todo) and bool(recorded) and not (scanned & recorded)
        if gap_risk:
            self._chain.append(self._gap_marker(len(scanned), len(todo)))
            logger.warning(
                "Approval records: scan window (limit %d) has no overlap with "
                "the recorded stream — merges may be unrecorded; capture_gap "
                "marker chained.",
                _MERGED_PR_SCAN_LIMIT,
            )
        if not todo:
            return {
                "merged_seen": len(merged),
                "recorded": 0,
                "capture_gap_risk": False,
                "record_failures": 0,
            }

        factory_login = await self._fetch_factory_login()
        count = 0
        failures = 0
        last_error: Exception | None = None
        for number in todo:
            # Per-PR isolation: one poisoned PR (deleted head repo 404,
            # malformed payload) sits first in the sorted todo forever and
            # would otherwise fail the whole cycle every tick — starving
            # every PR behind it of its evidence record (a silent gap the
            # zero-overlap heuristic cannot see, since overlap still exists).
            try:
                detail = await self._fetch_pr_detail(number)
                self._chain.append(self._build_record(detail, factory_login))
                count += 1
            except (AuthenticationError, CreditExhaustedError):
                # Fatal infrastructure signals (RuntimeError subclasses) must
                # never be burned as per-PR failures — propagate immediately
                # so the hosting loop's cycle handler sees them.
                raise
            except (RuntimeError, ValueError) as exc:
                failures += 1
                last_error = exc
                logger.warning(
                    "Approval records: recording PR #%d failed (%s) — "
                    "continuing with the remaining %d PR(s).",
                    number,
                    exc_detail(exc),
                    len(todo) - count - failures,
                )
        if failures and count == 0 and last_error is not None:
            # Every todo PR failed: this is a gh outage, not per-PR poison.
            # Propagate so the cycle handler applies its outage semantics.
            raise last_error
        if count:
            logger.info(
                "Approval records: recorded %d merged PR(s): %s", count, todo[:10]
            )
        return {
            "merged_seen": len(merged),
            "recorded": count,
            "capture_gap_risk": gap_risk,
            "record_failures": failures,
        }

    # -- gh boundary (raw gh via the shared subprocess helper; no new PRPort
    # method — nothing on PRPort/FakeGitHub exposes mergedBy, and the atomic
    # Protocol+fake+cassette triplet is not warranted for one read shape) ----

    async def _list_recently_merged(self) -> list[dict[str, Any]]:
        """Return ``[{number, mergedAt}, ...]`` for recently merged PRs."""
        raw = await subprocess_util.run_subprocess(
            "gh",
            "pr",
            "list",
            "--repo",
            self._config.repo,
            "--state",
            "merged",
            "--search",
            "sort:updated-desc",
            "--limit",
            str(_MERGED_PR_SCAN_LIMIT),
            "--json",
            "number,mergedAt",
            timeout=_GH_TIMEOUT_SECONDS,
        )
        data = json.loads(raw or "[]")
        if not isinstance(data, list):
            raise ValueError(f"gh pr list returned non-list payload: {data!r}")
        return [entry for entry in data if isinstance(entry, dict)]

    async def _fetch_pr_detail(self, pr_number: int) -> dict[str, Any]:
        """Fetch the merge event's actor, artifact state, and evidence refs."""
        raw = await subprocess_util.run_subprocess(
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            self._config.repo,
            "--json",
            _DETAIL_JSON_FIELDS,
            timeout=_GH_TIMEOUT_SECONDS,
        )
        detail = json.loads(raw)
        if not isinstance(detail, dict):
            raise ValueError(f"gh pr view #{pr_number} returned {detail!r}")
        return detail

    async def _fetch_factory_login(self) -> str:
        """The reconciler token's own login — role classification ONLY."""
        raw = await subprocess_util.run_subprocess(
            "gh", "api", "user", "--jq", ".login", timeout=_GH_TIMEOUT_SECONDS
        )
        return raw.strip()

    # -- record building -----------------------------------------------------

    def _filter_retention_expired(self, merged: list[dict[str, Any]]) -> set[int]:
        """Scanned PR numbers eligible for recording under the retention floor.

        When ``audit_retention_days_approval_records`` is configured, merges
        older than the floor are excluded — RunsGC would prune (or already
        pruned) their evidence, and re-recording would re-date sign-off
        evidence the operator chose to expire. Fail-safe: a merge whose age
        cannot be established is kept, never silently expired.
        """
        numbers = {
            number
            for number in (entry.get("number") for entry in merged)
            if isinstance(number, int)
        }
        retention_days = self._config.audit_retention_days_approval_records
        if retention_days is None:
            return numbers
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        expired: set[int] = set()
        for entry in merged:
            number = entry.get("number")
            if not isinstance(number, int):
                continue
            merged_at = _parse_merged_at(entry.get("mergedAt"))
            if merged_at is not None and merged_at < cutoff:
                expired.add(number)
        if expired:
            logger.info(
                "Approval records: %d scanned merge(s) older than the %d-day "
                "retention floor skipped (evidence expired, not re-minted): %s",
                len(expired),
                retention_days,
                sorted(expired)[:10],
            )
        return numbers - expired

    def _recorded_pr_numbers(self) -> set[int]:
        """Read back every approval ``pr_number`` already in the stream.

        Only ``record_type == "approval"`` rows count toward dedup (a missing
        ``record_type`` is tolerated as an approval for forward-compat): a
        CH-3 ``break_glass`` record carries the same ``pr_number`` as the
        merge it authorized and must not suppress that merge's later
        approval record.
        """
        path = self._config.approval_records_path
        if not path.exists():
            return set()
        numbers: set[int] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                # A corrupt line is a chain break — RunsGCLoop alerts on it;
                # dedup keeps working from the parseable records.
                continue
            if not isinstance(record, dict):
                continue
            if record.get("record_type", RECORD_TYPE_APPROVAL) != RECORD_TYPE_APPROVAL:
                continue
            if isinstance(record.get("pr_number"), int):
                numbers.add(record["pr_number"])
        return numbers

    def _classify_role(
        self,
        *,
        base_ref: str,
        head_ref: str,
        approver: str,
        approver_is_bot: bool,
        factory_login: str,
    ) -> tuple[str, str | None]:
        """Return ``(role, delegation_basis)`` for one merge event.

        Branch shape alone never grants ``orchestrator``: the promotion lane
        is only the orchestrator's when the merge actor IS the factory. A
        named human force-merging an rc/* PR is an operator intervention and
        must be recorded as one (``head_branch`` keeps the rc/* origin).
        """
        is_factory_actor = bool(approver) and (
            approver_is_bot or (factory_login and approver == factory_login)
        )
        if (
            head_ref.startswith(self._config.rc_branch_prefix)
            and base_ref == self._config.main_branch
            and is_factory_actor
        ):
            return ROLE_ORCHESTRATOR, None
        if is_factory_actor:
            return ROLE_DELEGATED_BOT, FACTORY_AUTONOMY_CLAUSE
        return ROLE_OPERATOR, None

    def _build_record(
        self, detail: dict[str, Any], factory_login: str
    ) -> dict[str, Any]:
        author = _login(detail.get("author"))
        merged_by = detail.get("mergedBy")
        approver = _login(merged_by)
        approver_is_bot = bool(isinstance(merged_by, dict) and merged_by.get("is_bot"))
        base_ref = detail.get("baseRefName") or ""
        head_ref = detail.get("headRefName") or ""
        role, delegation_basis = self._classify_role(
            base_ref=base_ref,
            head_ref=head_ref,
            approver=approver,
            approver_is_bot=approver_is_bot,
            factory_login=factory_login,
        )
        merge_commit = detail.get("mergeCommit")
        merge_commit_sha = (
            merge_commit.get("oid", "") if isinstance(merge_commit, dict) else ""
        )
        return {
            "schema": APPROVAL_RECORD_SCHEMA_VERSION,
            "record_type": RECORD_TYPE_APPROVAL,
            "repo": self._config.repo,
            "pr_number": detail["number"],
            "pr_url": detail.get("url") or "",
            "title": detail.get("title") or "",
            "base_branch": base_ref,
            "head_branch": head_ref,
            "head_sha": detail.get("headRefOid") or "",
            "merge_commit_sha": merge_commit_sha,
            "merged_at": detail.get("mergedAt") or "",
            "timestamp": datetime.now(UTC).isoformat(),
            "author_identity": author,
            "approver_identity": approver,
            "role": role,
            "role_separated": bool(author) and bool(approver) and author != approver,
            "delegation_basis": delegation_basis,
            "evidence": {
                "review_decision": detail.get("reviewDecision") or "",
                "reviews": self._review_refs(detail.get("reviews")),
                "ci_checks": self._ci_check_refs(detail.get("statusCheckRollup")),
            },
        }

    def _gap_marker(self, scanned: int, unrecorded: int) -> dict[str, Any]:
        """Chained evidence that capture continuity is unprovable this tick.

        Excluded from dedup by construction (no ``pr_number``); auditors and
        the evidence-pack compiler (CH-4) read it as an honest boundary
        rather than discovering an unexplained hole.
        """
        return {
            "schema": APPROVAL_RECORD_SCHEMA_VERSION,
            "record_type": RECORD_TYPE_CAPTURE_GAP,
            "repo": self._config.repo,
            "timestamp": datetime.now(UTC).isoformat(),
            "scanned": scanned,
            "new_unrecorded": unrecorded,
            "reason": (
                "scan window has no overlap with the recorded stream — "
                "merges older than the window horizon may be unrecorded "
                f"(scan limit {_MERGED_PR_SCAN_LIMIT}, sort:updated-desc)"
            ),
        }

    @staticmethod
    def _review_refs(reviews: Any) -> list[dict[str, str]]:
        """Compact review-state refs from the PR's review timeline."""
        if not isinstance(reviews, list):
            return []
        return [
            {
                "author": _login(review.get("author")),
                "state": review.get("state") or "",
                "submitted_at": review.get("submittedAt") or "",
            }
            for review in reviews
            if isinstance(review, dict)
        ]

    @staticmethod
    def _ci_check_refs(rollup: Any) -> list[dict[str, str]]:
        """Compact CI refs: CheckRun and legacy StatusContext shapes."""
        if not isinstance(rollup, list):
            return []
        refs: list[dict[str, str]] = []
        for check in rollup[:_MAX_CI_CHECK_REFS]:
            if not isinstance(check, dict):
                continue
            refs.append(
                {
                    "name": check.get("name") or check.get("context") or "",
                    "conclusion": check.get("conclusion") or check.get("state") or "",
                    "run_url": check.get("detailsUrl") or check.get("targetUrl") or "",
                }
            )
        return refs
