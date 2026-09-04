"""The per-change artifact chain (ADR-0149): model, digests, renderers.

Pure. Nothing here touches the filesystem — renderers return strings and
``digest`` hashes them. The single write path lives in
:mod:`change_chain_writer`; verification lives in :mod:`change_chain_gate`.

Byte stability is load-bearing. The gate re-derives a digest from the
*committed* file and compares it to the one the planner anchored, so a
renderer that interpolates a clock reading or an unordered mapping turns
every verification into a false positive. Every varying field a renderer
emits is passed in by its caller.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

CHANGES_DIRNAME = "changes"


class ChainArtifact(StrEnum):
    """One file in a change's chain. The value is the filename stem."""

    INTENT = "intent"
    SPEC = "spec"
    PLAN = "plan"
    EVIDENCE = "evidence"


@dataclass(frozen=True)
class ChainRecord:
    """One CH-1 record: a change's artifacts as the planner rendered them.

    Carries the rendered bodies as well as their digests, because the stream
    is the transport as well as the anchor — the worktree that materialises
    the chain is often not the process that planned it, and a digest with no
    body cannot be materialised anywhere.
    """

    issue_number: int
    digests: dict[ChainArtifact, str]
    rendered: dict[ChainArtifact, str]
    recorded_at: str

    def to_json_dict(self) -> dict[str, object]:
        """Render for the append-only stream (StrEnum keys become strings)."""
        return {
            "issue_number": self.issue_number,
            "digests": {k.value: v for k, v in sorted(self.digests.items())},
            "rendered": {k.value: v for k, v in sorted(self.rendered.items())},
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, object]) -> ChainRecord:
        """Rebuild a record from its stream form, dropping unknown artifacts.

        Unknown names are dropped rather than raising: the stream is
        append-only and permanent, so a record written by a future version
        that added a fifth artifact must still be readable by this one.
        """
        raw_number = payload.get("issue_number", 0)
        return cls(
            issue_number=raw_number if isinstance(raw_number, int) else 0,
            digests=_by_artifact(payload.get("digests")),
            rendered=_by_artifact(payload.get("rendered")),
            recorded_at=str(payload.get("recorded_at", "")),
        )


def _by_artifact(raw: object) -> dict[ChainArtifact, str]:
    """Coerce a stream mapping to ``{ChainArtifact: str}``, dropping strays."""
    if not isinstance(raw, Mapping):
        return {}
    known = {a.value: a for a in ChainArtifact}
    return {known[key]: str(value) for key, value in raw.items() if key in known}


def digest(text: str) -> str:
    """SHA-256 of *text* as UTF-8 bytes — the exact bytes written to disk."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chain_dir(repo_root: Path, issue_number: int) -> Path:
    """Return the chain directory for *issue_number* inside *repo_root*."""
    return repo_root / "docs" / CHANGES_DIRNAME / f"issue-{issue_number}"


def render_intent(issue_number: int, title: str, body: str, captured_at: str) -> str:
    """Render the issue snapshot taken at plan time."""
    return (
        f"# Intent — Issue #{issue_number}\n\n"
        f"**Title:** {title}\n\n"
        f"**Captured:** {captured_at}\n\n"
        "> Snapshot of the issue body at plan time. Written by the harness;\n"
        "> not hand-edited, and not a live view of the issue.\n\n"
        "---\n\n"
        f"{body.strip()}\n"
    )


def render_spec(
    issue_number: int,
    criteria: Sequence[str],
    judge_verdict: str,
    forwarded_concerns: Sequence[str],
) -> str:
    """Render the pre-implementation acceptance criteria and judge verdict."""
    lines = [
        f"# Spec — Issue #{issue_number}",
        "",
        "Acceptance criteria drafted from the plan before any code existed,",
        "and the SpecJudge verdict on them.",
        "",
        f"**Judge verdict:** {judge_verdict}",
        "",
        "## Acceptance criteria",
        "",
    ]
    if criteria:
        lines.extend(f"- {c}" for c in criteria)
    else:
        lines.append("_(none drafted)_")
    if forwarded_concerns:
        lines.extend(["", "## Concerns forwarded unresolved", ""])
        lines.extend(f"- {c}" for c in forwarded_concerns)
    return "\n".join(lines) + "\n"


def render_plan(issue_number: int, plan: str, summary: str) -> str:
    """Render the plan. Byte-identical to ``planner._save_plan``'s format."""
    return (
        f"# Plan for Issue #{issue_number}\n\n{plan}\n\n---\n**Summary:** {summary}\n"
    )


def render_evidence(
    issue_number: int,
    *,
    approver_role: str,
    chain_position: int,
    approver_identity: str = "",
    change_class: str = "",
    human_required: bool = False,
) -> str:
    """Render the merge receipt.

    A receipt, not the binder: the hash-chained JSONL streams and the RC
    evidence packs stay where they are, and this file cross-references them
    by position and identity.
    """
    return (
        f"# Evidence — Issue #{issue_number}\n\n"
        f"**Approver role:** {approver_role}\n"
        f"**Approver identity:** {approver_identity or '(unrecorded)'}\n"
        f"**Change class:** {change_class or '(unclassified)'}\n"
        f"**Human review required:** {'yes' if human_required else 'no'}\n"
        f"**CH-1 chain position:** {chain_position}\n\n"
        "> Receipt only. The hash-chained audit streams and the RC evidence\n"
        "> packs remain the binder; this file cross-references them.\n"
    )
