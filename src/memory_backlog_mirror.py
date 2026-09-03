"""Pure helpers for `MemoryBacklogLoop` (no IO except file read/write).

See `docs/superpowers/specs/2026-05-07-tier2-enforcement-batch-design.md` §6
and `docs/wiki/memory-feedback/README.md` for the frontmatter schema and
status state-machine.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import yaml

logger = logging.getLogger("hydraflow.memory_backlog_mirror")

Status = Literal["pending", "issue-open", "promoted", "wontfix"]
_VALID_STATUS: frozenset[str] = frozenset(
    {"pending", "issue-open", "promoted", "wontfix"}
)


@dataclass(frozen=True)
class MirrorEntry:
    slug: str
    path: Path
    source: str
    name: str
    description: str
    status: Status
    issue: int | None
    promoted_in: str | None
    wontfix_reason: str | None
    body: str


#: The mirror reference every filed issue carries in its body, written by
#: :func:`render_issue_body`. This is what makes the ISSUE the authority on
#: whether an entry has been filed: it survives a re-clone, a reset workspace
#: and a lost DedupStore, none of which the frontmatter does (#11963).
_MIRROR_REF = re.compile(r"memory-feedback/([a-z0-9][a-z0-9._-]*)\.md")


def slug_from_issue_body(body: str) -> str | None:
    """The mirror slug an issue was filed for, or None if it names none.

    Reads the `Mirror:` line `render_issue_body` writes, so the two are one
    format with two readers rather than a convention. An issue a human wrote by
    hand under the same label simply names no mirror and is ignored, which is
    the right answer — it is not evidence that any entry was filed.
    """
    match = _MIRROR_REF.search(body or "")
    return match.group(1) if match else None


def filed_slugs(issues: Iterable[Mapping[str, object]]) -> dict[str, int]:
    """Map mirror slug -> open issue number, from the filed issues themselves.

    The authoritative re-filing guard. ADR-0089 made the mirror frontmatter the
    guard, which put it in whichever checkout happened to be running: the loop
    filed #11947-#11949, wrote `status: issue-open` and committed it into a
    workspace nothing pushes, so `staging` still read `pending` and a re-clone
    would have re-filed all three as duplicates of issues that were still open
    (#11963).

    Lowest number wins on a duplicate so healing is deterministic and points at
    the original rather than whichever row the API returned last.
    """
    found: dict[str, int] = {}
    for issue in issues:
        slug = slug_from_issue_body(str(issue.get("body", "")))
        number = issue.get("number")
        if slug is None or not isinstance(number, int):
            continue
        if slug not in found or number < found[slug]:
            found[slug] = number
    return found


def dedup_key_for(slug: str) -> str:
    return f"memory_backlog:{slug}"


def load_mirror_entry(path: Path) -> MirrorEntry:
    text = path.read_text()
    if not text.startswith("---\n"):
        msg = f"missing frontmatter in {path}"
        raise ValueError(msg)
    end = text.find("\n---", 4)
    if end == -1:
        msg = f"unterminated frontmatter in {path}"
        raise ValueError(msg)
    try:
        front = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as exc:
        # A malformed entry is data corruption, not a loop bug — surface as
        # ValueError so callers (pending_entries) can skip it uniformly.
        msg = f"malformed frontmatter in {path}: {exc}"
        raise ValueError(msg) from exc
    body = text[end + 4 :].lstrip("\n").rstrip() + "\n"
    status = front.get("status", "pending")
    if status not in _VALID_STATUS:
        msg = f"invalid status {status!r} in {path}"
        raise ValueError(msg)
    # `promoted_in` is the terminal transition's evidence, so carrying one while
    # still claiming an earlier status is a contradiction, not a variant
    # (#12069). Only `pending -> issue-open` is automated; the move to
    # `promoted` is manual and drifted on three rows whose PRs had merged and
    # whose issues were closed. Refusing the pair keeps the drift loud instead
    # of leaving the board to disagree with the state machine silently.
    if front.get("promoted_in") is not None and status != "promoted":
        msg = (
            f"{path} carries promoted_in={front['promoted_in']!r} with "
            f"status={status!r}; a row with promoted_in set is `promoted` "
            f"(docs/wiki/memory-feedback/README.md)"
        )
        raise ValueError(msg)
    # ...and the converse, which was documented but never enforced (#12058).
    # The verdict rules require the evidence, not just the label: "Promoted
    # entries must cite a real artifact in `promoted_in`. Wontfix entries must
    # carry `wontfix_reason`." Only the implication above was in code, so a row
    # could be stamped terminal with no evidence at all — the same false-green
    # as a passing test that asserts nothing, and the shape that let three
    # already-enforced rows sit at `pending` while the loop re-filed them.
    if status == "promoted" and front.get("promoted_in") is None:
        msg = (
            f"{path} is `promoted` with no promoted_in; a promotion must cite "
            f"the artifact that enforces it (ADR, hook, ratchet, rule)"
        )
        raise ValueError(msg)
    if status == "wontfix" and front.get("wontfix_reason") is None:
        msg = (
            f"{path} is `wontfix` with no wontfix_reason; declining to build "
            f"enforcement has to say why, or the next reader cannot tell a "
            f"considered verdict from an abandoned row"
        )
        raise ValueError(msg)
    return MirrorEntry(
        slug=path.stem,
        path=path,
        source=str(front.get("source", "")),
        name=str(front.get("name", path.stem)),
        description=str(front.get("description", "")),
        status=cast(Status, status),
        issue=front.get("issue"),
        promoted_in=front.get("promoted_in"),
        wontfix_reason=front.get("wontfix_reason"),
        body=body,
    )


def pending_entries(mirror_dir: Path) -> list[MirrorEntry]:
    entries: list[MirrorEntry] = []
    for path in sorted(mirror_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            entry = load_mirror_entry(path)
        except ValueError as exc:
            logger.warning("Skipping malformed mirror entry %s: %s", path, exc)
            continue
        if entry.status == "pending":
            entries.append(entry)
    return entries


def render_issue_body(entry: MirrorEntry, *, repo_relative_path: str) -> str:
    return (
        f"# {entry.name}\n\n"
        f"{entry.description}\n\n"
        f"## Source memory\n\n"
        f"- Mirror: [`{repo_relative_path}`]({repo_relative_path})\n"
        f"- Originally captured as `{entry.source}`\n\n"
        f"## Rule (from memory)\n\n"
        f"{entry.body}\n"
        f"---\n"
        f"_Filed by `MemoryBacklogLoop` (ADR-0089) — promote by enforcing "
        f"the rule (test/fixture/lint/loop), then close this issue with "
        f"`promoted_in: <PR>` in the mirror frontmatter._\n"
    )


def update_status(
    path: Path,
    *,
    status: Status,
    issue: int | None = None,
    promoted_in: str | None = None,
    wontfix_reason: str | None = None,
) -> None:
    """Re-write only the frontmatter status fields. Preserves body verbatim."""
    text = path.read_text()
    end = text.find("\n---", 4)
    if not text.startswith("---\n") or end == -1:
        msg = f"can't update status — bad frontmatter in {path}"
        raise ValueError(msg)
    front = yaml.safe_load(text[4:end]) or {}
    front["status"] = status
    if issue is not None:
        front["issue"] = issue
    if promoted_in is not None:
        front["promoted_in"] = promoted_in
    if wontfix_reason is not None:
        front["wontfix_reason"] = wontfix_reason
    body = text[end + 4 :].lstrip("\n")
    front_yaml = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
    path.write_text(f"---\n{front_yaml}\n---\n\n{body}")
