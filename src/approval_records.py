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
* ``orchestrator`` — the PR is an RC promotion (head ``rc/*`` onto the main
  branch): the StagingPromotionLoop's own promotion merge (ADR-0042).
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
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import subprocess_util
from audit_chain import AuditChain

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
_MERGED_PR_SCAN_LIMIT = 50

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
        todo = sorted(
            number
            for number in (entry.get("number") for entry in merged)
            if isinstance(number, int) and number not in recorded
        )
        if not todo:
            return {"merged_seen": len(merged), "recorded": 0}

        factory_login = await self._fetch_factory_login()
        count = 0
        for number in todo:
            detail = await self._fetch_pr_detail(number)
            self._chain.append(self._build_record(detail, factory_login))
            count += 1
        logger.info("Approval records: recorded %d merged PR(s): %s", count, todo[:10])
        return {"merged_seen": len(merged), "recorded": count}

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

    def _recorded_pr_numbers(self) -> set[int]:
        """Read back every ``pr_number`` already in the stream (dedup set)."""
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
            if isinstance(record, dict) and isinstance(record.get("pr_number"), int):
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
        """Return ``(role, delegation_basis)`` for one merge event."""
        if head_ref.startswith(self._config.rc_branch_prefix) and (
            base_ref == self._config.main_branch
        ):
            return ROLE_ORCHESTRATOR, None
        if approver and (
            approver_is_bot or (factory_login and approver == factory_login)
        ):
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
