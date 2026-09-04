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
ARCHIVE_DIRNAME = "archive"

#: The chain tree's repo-relative prefix. The single source for every site
#: that must recognise a chain path — the writer's commit pathspec, the
#: delivery-commit exclusion in ``agent/_commit.py``, and the non-deliverable
#: classification in ``null_delivery``. Moving the tree means editing this.
CHANGES_PREFIX = f"docs/{CHANGES_DIRNAME}"


class ChainArtifact(StrEnum):
    """One file in a change's chain. The value is the filename stem."""

    INTENT = "intent"
    CRITERIA = "criteria"
    PLAN = "plan"
    EVIDENCE = "evidence"


@dataclass(frozen=True)
class ChainRecord:
    """One CH-1 record: the digests a change's artifacts had at plan time.

    ``rendered`` is populated in memory by the recorder and written to the
    local body cache; it is deliberately NOT part of the stream payload (see
    :meth:`to_json_dict`), so a record read back from the stream always has
    ``rendered == {}``.

    The consequence is real and bounded: the anchor is permanent and the
    bodies are not. A change planned on one host and implemented on another,
    or planned before a data-root GC sweep and implemented after it, finds no
    cached bodies — the writer then rejects every artifact and the change
    ships with no chain, which the gate reports as unanchored rather than
    passing silently. Both hosts today are the same host (the plan and
    implement phases run in one factory process against one data root), so
    this is a constraint to preserve, not a live gap.
    """

    issue_number: int
    digests: dict[ChainArtifact, str]
    rendered: dict[ChainArtifact, str]
    recorded_at: str

    def to_json_dict(self) -> dict[str, object]:
        """Render for the append-only stream (StrEnum keys become strings).

        **Digests only — never the bodies.** Two reasons, both load-bearing:

        1. ``AuditChain.append`` secret-scrubs the payload it writes. Scrubbing
           a rendered body changes it, so a digest taken before the append
           would no longer match what the stream carried, and the gate's one
           tamper signal would fire on an entirely honest change.
        2. The scrubber rewrites serialized JSON, and its credential value
           class does not exclude a backslash — an issue body containing a
           credential-shaped token next to an escaped quote produced invalid
           JSON and crashed the plan phase. Arbitrary, externally-authored
           prose does not belong in an audit payload.

        Bodies travel through the local chain cache instead (see
        ``change_chain_recorder``); this record anchors them.
        """
        return {
            "issue_number": self.issue_number,
            "digests": {k.value: v for k, v in sorted(self.digests.items())},
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
    """Return the LIVE chain directory for *issue_number* inside *repo_root*.

    Where a change's files are written. Readers want :func:`resolve_chain_dir`
    instead — this one does not know about the archive.
    """
    return repo_root / "docs" / CHANGES_DIRNAME / f"issue-{issue_number}"


def archive_root(repo_root: Path) -> Path:
    """Return the compaction archive root (ADR-0149 ruling 2)."""
    return repo_root / "docs" / CHANGES_DIRNAME / ARCHIVE_DIRNAME


def resolve_chain_dir(repo_root: Path, issue_number: int) -> Path | None:
    """Find *issue_number*'s chain directory, live or archived.

    ADR-0149 ruling 2 folds each quarter into
    ``docs/changes/archive/YYYY-Qn/``, so a reader that only knows the live
    path stops finding a change the first time it is compacted — and a gate
    that stops finding its subject goes green, which is the failure mode
    this repo has shipped before. Every reader resolves; nobody memoises.

    Returns ``None`` when the change has no chain in either place.
    """
    live = chain_dir(repo_root, issue_number)
    if live.is_dir():
        return live
    archive = archive_root(repo_root)
    if not archive.is_dir():
        return None
    name = f"issue-{issue_number}"
    for quarter in sorted(archive.iterdir(), reverse=True):
        candidate = quarter / name
        if candidate.is_dir():
            return candidate
    return None


def render_intent(issue_number: int, title: str, body: str, captured_at: str) -> str:
    """Render the issue snapshot taken at plan time."""
    return (
        f"# Intent — Issue #{issue_number}\n\n"
        f"**Title:** {title}\n\n"
        f"**Captured:** {captured_at}\n\n"
        "> Snapshot of the issue body at plan time. Written by the harness;\n"
        "> not hand-edited, and not a live view of the issue.\n\n"
        "---\n\n"
        f"{_quote(body)}"
    )


def _quote(body: str) -> str:
    """Blockquote the issue body so its content cannot be read as markup.

    An issue body is externally authored and lands in a file the harness
    commits. HydraFlow issues routinely paste merge-conflict hunks, and this
    repo runs `scripts/check_conflict_markers.py` over tracked files — a
    line starting `<<<<<<< ` would either block the chain commit via the
    pre-commit hook or, on a host without hooks, fail CI permanently on
    staging in a file no agent is allowed to edit.

    Prefixing every line with "> " defuses that and every other line-start
    construct in one move, and the digest covers the quoted form, so the
    committed bytes are the bytes that were anchored.
    """
    lines = body.strip().splitlines() or [""]
    return "".join(f"> {line}\n" if line else ">\n" for line in lines)


def render_criteria(
    issue_number: int,
    criteria: Sequence[str],
    judge_verdict: str,
    forwarded_concerns: Sequence[str],
) -> str:
    """Render the pre-implementation acceptance criteria and judge verdict."""
    lines = [
        f"# Criteria — Issue #{issue_number}",
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
