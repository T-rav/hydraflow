"""Module-level helpers shared by ``pr_manager`` and its extracted mixins.

Split out of ``pr_manager.py`` (god-class decomposition, ``Refs #11547``) so
the per-surface mixins (``pr_manager_branches``, ``pr_manager_comments``,
``pr_manager_issues``, ``pr_manager_dashboard``, …) can reach these free
functions without importing ``pr_manager`` itself — that would close an import
cycle, since ``pr_manager`` imports every mixin.

Everything here is re-exported from ``pr_manager`` for back-compat: existing
``from pr_manager import _normalise_issue_comment`` call sites are unchanged.
Same shape as ``review_phase/_common.py``.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, NamedTuple

from models import GitHubIssueSummary

if TYPE_CHECKING:
    from contracts.boundary import BoundaryParseResult
    from contracts.shapes import GhIssueListItem


# Cache TTL for label-count queries (seconds).
_LABEL_CACHE_TTL: int = 30
_GIT_OID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class _BranchPRRow(NamedTuple):
    """Validated projection of one historical PR list row."""

    head_sha: str
    state: str
    merged: bool


def _parse_branch_pr_row(
    payload: dict[str, Any], *, expected_branch: str, expected_base: str
) -> _BranchPRRow | None:
    """Validate one GitHub branch-history row, rejecting shape ambiguity."""
    number = payload.get("number")
    raw_state = payload.get("state")
    raw_head_sha = payload.get("head_sha")
    head_ref = payload.get("head_ref")
    base_ref = payload.get("base_ref")
    merged_at = payload.get("merged_at")
    state = raw_state.upper() if isinstance(raw_state, str) else ""
    head_sha = raw_head_sha.lower() if isinstance(raw_head_sha, str) else ""
    required_fields_valid = (
        type(number) is int
        and number > 0
        and state in {"OPEN", "CLOSED"}
        and _GIT_OID_RE.fullmatch(head_sha) is not None
        and head_ref == expected_branch
        and base_ref == expected_base
    )

    merged = False
    timestamp_valid = merged_at is None
    if isinstance(merged_at, str) and merged_at:
        try:
            timestamp = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
        except ValueError:
            timestamp_valid = False
        else:
            timestamp_valid = timestamp.tzinfo is not None and state == "CLOSED"
            merged = timestamp_valid
    if not required_fields_valid or not timestamp_valid:
        return None
    return _BranchPRRow(head_sha=head_sha, state=state, merged=merged)


def _gh_wire_labels(r: BoundaryParseResult[GhIssueListItem]) -> list[dict[str, str]]:
    """Project one lenient-parsed gh issue row's labels into gh wire shape.

    Shared by ``_project_issue_summaries`` (open listing, #9943) and
    ``list_closed_issues_by_label`` (#8996 — the closed listing needs labels
    too, since ``escalation_reconcile.is_bot_close`` reads them to distinguish
    a programmatic close from a human one).
    """
    if r.model_instance is not None:
        return [{"name": lbl.name} for lbl in r.model_instance.labels if lbl.name]
    entry = r.payload if isinstance(r.payload, dict) else {}
    return [
        {"name": str(lbl.get("name", ""))}
        for lbl in (entry.get("labels") or [])
        if isinstance(lbl, dict) and lbl.get("name")
    ]


def _project_issue_summaries(
    results: list[BoundaryParseResult[GhIssueListItem]],
) -> list[GitHubIssueSummary]:
    """Project lenient-parsed gh issue rows into ``GitHubIssueSummary`` dicts.

    Shared by ``list_issues_by_label`` / ``list_open_issues`` — previously two
    byte-identical copies (#10025). ``labels`` ride along in gh wire shape
    (``{"name": ...}``, #9943) so consumers like the preflight human-required
    filter see real data whether the row validated or fell back to the raw
    payload.
    """
    # Local import keeps the module-load contract identical when the
    # contracts subsystem isn't imported elsewhere yet.
    from contracts.boundary import field_or  # noqa: PLC0415

    summaries: list[GitHubIssueSummary] = []
    for r in results:
        summaries.append(
            {
                "number": field_or(r, "number", 0),
                "title": field_or(r, "title", ""),
                "body": field_or(r, "body", ""),
                "updated_at": field_or(r, "updated_at", "", dict_key="updatedAt"),
                "labels": _gh_wire_labels(r),
            }
        )
    return summaries


def _is_missing_label_404(exc: RuntimeError) -> bool:
    """Return True when gh reports a missing label during label removal."""
    msg = str(exc).lower()
    return "label does not exist" in msg and "http 404" in msg


def _normalise_issue_comment(comment: dict[str, Any]) -> dict[str, Any]:
    """Map a ``gh issue view --json comments`` object to the stable port shape.

    gh emits GraphQL-shaped ``author.login`` / ``createdAt``; the port contract
    (and the fake) expose REST-shaped ``user.login`` / ``created_at``. Accept
    either input so the contract holds across gh versions.
    """
    author = comment.get("author") or comment.get("user") or {}
    login = author.get("login", "") if isinstance(author, dict) else ""
    return {
        "user": {"login": login},
        "body": comment.get("body", ""),
        "created_at": comment.get("createdAt") or comment.get("created_at") or "",
    }
