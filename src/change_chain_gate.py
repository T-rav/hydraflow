"""Verification for the per-change artifact chain (ADR-0149).

Pure. Takes a repo root, an issue number, the anchored record and the list
of files a PR touched; returns findings. It reads files and hashes them; it
writes nothing and spawns nothing. Producing *changed_files* is the
caller's job, per the engine/subprocess separation this repo already
applies to its other verifiers.

Three checks, in the order a reader should think about them:

1. **presence** — an artifact the record anchored is missing from the branch
2. **digest** — the committed file is not the one that was anchored
3. **scope** — the PR touched a file the plan never named

Report-only for now (ADR-0149's P4 stages the gate the way vitals and
setpoints were staged). The scope check in particular reads prose with a
regex and will produce false positives; that is why its findings are read
before they bite.

Everything here resolves a change's directory through
``change_chain.resolve_chain_dir`` rather than building the live path.
Ruling 2 compacts quarterly, and a gate that stops finding its subject
reports no findings — which reads exactly like a clean change.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from change_chain import (
    CHANGES_PREFIX,
    ChainArtifact,
    ChainRecord,
    digest,
    resolve_chain_dir,
)

FINDING_MISSING = "chain-artifact-missing"
FINDING_DIGEST_MISMATCH = "chain-digest-mismatch"
FINDING_SCOPE_DEPARTURE = "chain-scope-departure"
FINDING_NO_CHAIN = "chain-absent"

# A path-shaped token in plan prose: at least one directory separator or a
# dotted extension. Deliberately permissive — the scope check is report-only
# and a miss here is a false positive, which is the failure mode being
# measured before the gate is allowed to bite.
_PATH_IN_PLAN = re.compile(r"[\w./-]*\w+\.[A-Za-z0-9]+")


@dataclass(frozen=True)
class ChainFinding:
    """One thing wrong with a change's chain."""

    code: str
    detail: str


def verify_chain(
    repo_root: Path,
    issue_number: int,
    record: ChainRecord | Mapping[str, object] | None,
    changed_files: Sequence[str],
    *,
    required: Collection[str] = (),
) -> tuple[ChainFinding, ...]:
    """Return findings for *issue_number*'s chain. Empty means clean.

    *required* is the repo's ``charter.yaml`` ``artifacts.chain`` declaration.
    Passing it is what makes that declaration mean something: without it the
    gate only checks what happens to be anchored, so a change that silently
    stopped anchoring an artifact would verify clean.

    **Reads the working tree, not the branch.** An implementer that runs
    ``git rm --cached`` on a chain file, or amends the harness's chain commit
    away, leaves the file on disk and this returns clean. Closing that needs
    content from ``git show <ref>:<path>``; the gate is report-only until the
    caller that supplies it exists, and the limitation is stated here rather
    than implied by the finding text.
    """
    if record is None:
        return (
            ChainFinding(
                FINDING_NO_CHAIN,
                f"issue #{issue_number} has no anchored chain record, so its "
                "committed chain cannot be verified",
            ),
        )
    if isinstance(record, ChainRecord):
        anchored = record
    else:
        anchored = ChainRecord.from_json_dict(record)

    directory = resolve_chain_dir(repo_root, issue_number)
    if directory is None:
        return (
            ChainFinding(
                FINDING_MISSING,
                f"issue #{issue_number} anchored "
                f"{len(anchored.digests)} artifacts but has no chain "
                "directory, live or archived",
            ),
        )

    findings: list[ChainFinding] = []
    plan_text: str | None = None
    for artifact in ChainArtifact:
        expected = anchored.digests.get(artifact)
        if expected is None:
            if artifact.value in required:
                findings.append(
                    ChainFinding(
                        FINDING_MISSING,
                        f"{artifact.value}.md is required by the charter but "
                        "was never anchored for this change",
                    )
                )
            continue
        path = directory / f"{artifact.value}.md"
        if not path.is_file():
            findings.append(
                ChainFinding(
                    FINDING_MISSING,
                    f"{artifact.value}.md is anchored but absent from the branch",
                )
            )
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            # ValueError covers UnicodeDecodeError: a chain file that is not
            # valid UTF-8 is a corrupt chain, which is a finding this gate
            # exists to emit — not a crash of whatever wired it.
            findings.append(
                ChainFinding(
                    FINDING_DIGEST_MISMATCH,
                    f"{artifact.value}.md could not be read as UTF-8 — the "
                    "committed file is not the one that was planned",
                )
            )
            continue
        if digest(body) != expected:
            findings.append(
                ChainFinding(
                    FINDING_DIGEST_MISMATCH,
                    f"{artifact.value}.md does not match its anchored digest — "
                    "the committed file is not the one that was planned",
                )
            )
            continue
        if artifact is ChainArtifact.PLAN:
            plan_text = body

    if plan_text is not None:
        findings.extend(_scope_findings(plan_text, issue_number, changed_files))
    return tuple(findings)


def _scope_findings(
    plan_text: str, issue_number: int, changed_files: Sequence[str]
) -> list[ChainFinding]:
    """Findings for files the plan never names.

    The change's own chain directory is never a departure — the harness
    commits it, no plan names it, and counting it would make every change
    report a finding against itself. Archived chain paths are excluded on
    the same grounds.
    """
    named = {token for token in _PATH_IN_PLAN.findall(plan_text) if token}
    return [
        ChainFinding(
            FINDING_SCOPE_DEPARTURE,
            f"{path} was changed but the plan never names it",
        )
        for path in changed_files
        if not _is_own_chain(path, issue_number) and not _is_named(path, named)
    ]


def _is_own_chain(path: str, issue_number: int) -> bool:
    """True when *path* is this change's own chain artifact."""
    normalised = Path(path).as_posix().removeprefix("./")
    if not normalised.startswith(f"{CHANGES_PREFIX}/"):
        return False
    return f"issue-{issue_number}" in Path(normalised).parts


def _is_named(path: str, named: set[str]) -> bool:
    """True when the plan names *path*, by full path or by basename."""
    basename = Path(path).name
    return any(token in (path, basename) or path.endswith(token) for token in named)
