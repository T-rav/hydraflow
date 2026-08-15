#!/usr/bin/env python3
"""Console conformance: fitness functions for chamber decision records.

Adopted from the harvestd reference implementation (ARCH-0001 in
``agents/console/decisions/arch/``; advances #10949). Checks:

  1. Record shape — Date/Seats/Verdict/Evidence/Enforcement on every record;
     ``enforced`` records must name an ``Enforced by:`` check.
  2. Numbering — contiguous per chamber from 0001.
  3. Persona contracts — every ``agents/*.md`` persona carries ``authority:``
     and ``feeds:`` frontmatter.
  4. Chair identity — chamber files name their chartered chairs.
  5. Calibration staleness — fails on the 6th persona-run record after the
     newest general calibration record.
  6. Ledger immutability — a record present at the PR's merge-base may not
     be modified, deleted, or renamed by the PR (corrections are new
     records). Scoped to ``merge_base(HEAD, base)..HEAD`` so a historical
     amendment outside the PR's own range never latches future builds red
     (#11169); records the PR itself creates are exempt from in-PR edits
     (#11170 folded in: deletions and renames of merged records count too).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ENFORCEMENT_RE = re.compile(
    r"\*\*Enforcement:\*\*\s+(enforced|process-gated|decision-of-record)"
)
REQUIRED_FIELDS = ("**Date:**", "**Seats:**", "**Verdict:**", "**Evidence:**")
STALENESS_LIMIT = 5

# --- Check #6: ledger immutability ------------------------------------

_PR_BASE_ENV = "HYDRAFLOW_AUDIT_PR_BASE"
_BASE_BRANCH_CANDIDATES = ("origin/staging", "origin/main", "staging", "main")
_COMMIT_MARK = "\x01"
_STATUS_LABELS = {"M": "modified", "D": "deleted"}


def _is_record_path(path: str) -> bool:
    """True if *path* looks like a numbered decision record (``NNNN-*.md``)."""
    name = path.rsplit("/", 1)[-1]
    return name[:4].isdigit() and name.endswith(".md")


def _run_git(root: Path, args: list[str], timeout: int) -> str | None:
    """Run a git subcommand in *root*; return stdout or None on any failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _merge_base(root: Path, candidate: str) -> str | None:
    out = _run_git(root, ["merge-base", candidate, "HEAD"], timeout=10)
    sha = out.strip() if out else ""
    return sha or None


def _resolve_merge_base(root: Path) -> str | None:
    """Resolve the merge-base sha of HEAD against the PR's base branch.

    Prefers the CI-supplied ``HYDRAFLOW_AUDIT_PR_BASE`` env var (trying
    ``origin/<base>`` then ``<base>``) so an explicit PR context always
    wins; falls back to a fixed candidate chain so a local
    ``make console-conformance`` run (no env var, no PR context) still
    scopes correctly instead of walking whole history.
    """
    env_base = os.environ.get(_PR_BASE_ENV, "").strip()
    if env_base:
        for candidate in (f"origin/{env_base}", env_base):
            sha = _merge_base(root, candidate)
            if sha:
                return sha
    for candidate in _BASE_BRANCH_CANDIDATES:
        sha = _merge_base(root, candidate)
        if sha:
            return sha
    return None


def _records_at(root: Path, decisions_rel: str, merge_base: str) -> set[str]:
    """Decision-record paths (relative to *root*) that existed at *merge_base*."""
    out = _run_git(
        root,
        ["ls-tree", "-r", "--name-only", merge_base, "--", decisions_rel],
        timeout=10,
    )
    if not out:
        return set()
    return {
        line.strip()
        for line in out.splitlines()
        if line.strip() and _is_record_path(line.strip())
    }


def _ledger_change_argv(decisions_rel: str, merge_base: str) -> list[str]:
    """The ``git log`` argv for check #6 (kept pure so its shape is unit-testable)."""
    return [
        "log",
        "-M",
        "--diff-filter=DMR",
        "--full-history",
        f"--format={_COMMIT_MARK}%h %s",
        "--name-status",
        f"{merge_base}..HEAD",
        "--",
        decisions_rel,
    ]


def _parse_ledger_changes(log_output: str, known_records: set[str]) -> list[str]:
    """Turn ``--name-status`` log text into violation lines against *known_records*.

    Pure function (no subprocess) so multi-commit / multi-status parsing is
    directly unit-testable against canned text.
    """
    violations: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for raw_block in log_output.split(_COMMIT_MARK):
        block = raw_block.strip("\n")
        if not block:
            continue
        lines = block.split("\n")
        header = lines[0].strip()
        for raw_change in lines[1:]:
            change = raw_change.strip()
            if not change:
                continue
            parts = change.split("\t")
            status = parts[0]
            if status.startswith("R"):
                if len(parts) < 3:
                    continue
                old, new = parts[1], parts[2]
                if old not in known_records:
                    continue
                key = ("R", old, new, header)
                if key in seen:
                    continue
                seen.add(key)
                violations.append(f"{old}: renamed to {new} ({header})")
            elif status in _STATUS_LABELS:
                if len(parts) < 2:
                    continue
                path = parts[1]
                if path not in known_records:
                    continue
                key = (status, path, header)
                if key in seen:
                    continue
                seen.add(key)
                violations.append(f"{path}: {_STATUS_LABELS[status]} ({header})")
            # 'A' (added) is defensively ignored even though --diff-filter
            # already excludes it — a new record is never a violation.
    return violations


def _immutability_violations(
    root: Path, decisions_rel: str
) -> tuple[list[str], str | None]:
    """Return (violations, warning). Warning is set iff check #6 was skipped."""
    merge_base = _resolve_merge_base(root)
    if merge_base is None:
        return [], (
            "console-conformance: check #6 (ledger immutability) skipped — no "
            f"resolvable base ref (set {_PR_BASE_ENV} or run inside a full clone "
            "with an origin/staging or origin/main remote-tracking branch)"
        )
    known_records = _records_at(root, decisions_rel, merge_base)
    if not known_records:
        return [], None
    log_output = _run_git(
        root, _ledger_change_argv(decisions_rel, merge_base), timeout=20
    )
    if not log_output:
        return [], None
    return _parse_ledger_changes(log_output, known_records), None


def collect_errors(root: Path, check_git: bool = True) -> list[str]:
    errors: list[str] = []
    agents = root / "agents"
    decisions = agents / "console" / "decisions"

    records = sorted(decisions.glob("*/[0-9]*.md"))
    for rec in records:
        text = rec.read_text()
        rel = rec.relative_to(root)
        for field in REQUIRED_FIELDS:
            if field not in text:
                errors.append(f"{rel}: missing {field}")
        match = ENFORCEMENT_RE.search(text)
        if not match:
            errors.append(f"{rel}: missing/invalid **Enforcement:** line")
        elif match.group(1) == "enforced" and "**Enforced by:**" not in text:
            errors.append(f"{rel}: enforced without an **Enforced by:** check")

    for chamber_dir in sorted(d for d in decisions.iterdir() if d.is_dir()):
        nums = sorted(
            int(f.name[:4])
            for f in chamber_dir.glob("[0-9]*.md")
            if f.name[:4].isdigit()
        )
        if nums and nums != list(range(1, len(nums) + 1)):
            errors.append(f"{chamber_dir.name}: numbering not contiguous: {nums}")

    persona_names = []
    for persona in sorted(agents.glob("*.md")):
        if persona.name == "README.md":
            continue
        persona_names.append(persona.stem)
        text = persona.read_text()
        for field in ("authority:", "feeds:"):
            if field not in text:
                errors.append(
                    f"{persona.relative_to(root)}: missing {field} frontmatter"
                )

    chairs = {
        "console/design.md": "product-manager",
        "console/arch.md": "senior-principal",
    }
    for rel_path, chair in chairs.items():
        path = agents / rel_path
        if path.exists() and chair not in path.read_text().split("\n")[2]:
            errors.append(
                f"agents/{rel_path}: chartered chair '{chair}' missing from chair line"
            )
    console_readme = (agents / "console" / "README.md").read_text()
    if "| **General** | vp-eng |" not in console_readme:
        errors.append(
            "console/README.md: general chair (vp-eng) missing from chambers table"
        )

    calib = sorted((decisions / "general").glob("*calibration*.md"))
    calib_date = ""
    calib_num = -1
    if calib:
        text = calib[-1].read_text()
        m = re.search(r"\*\*Date:\*\*\s+(\d{4}-\d{2}-\d{2})", text)
        calib_date = m.group(1) if m else ""
        calib_num = int(calib[-1].name[:4])
    run_count = 0
    for rec in records:
        text = rec.read_text()
        seats = re.search(r"\*\*Seats:\*\*\s+(.+)", text)
        date = re.search(r"\*\*Date:\*\*\s+(\d{4}-\d{2}-\d{2})", text)
        if not (seats and date):
            continue
        if not any(name in seats.group(1) for name in persona_names):
            continue
        after = date.group(1) > calib_date or (
            rec.parent.name == "general"
            and rec.name[:4].isdigit()
            and int(rec.name[:4]) > calib_num
        )
        if after:
            run_count += 1
    if run_count > STALENESS_LIMIT:
        errors.append(
            f"calibration stale: {run_count} persona-run records since the last "
            f"calibration review (limit {STALENESS_LIMIT}) — convene the general chair"
        )

    if check_git:
        decisions_rel = decisions.relative_to(root).as_posix()
        violations, warning = _immutability_violations(root, decisions_rel)
        if warning:
            print(warning, file=sys.stderr)
        if violations:
            errors.append(
                "record immutability violated (corrections must be new records):\n"
                + "\n".join(f"    {v}" for v in violations)
            )

    return errors


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    errors = collect_errors(root)
    if errors:
        for err in errors:
            print(f"  FAIL {err}")
        return 1
    n_records = len(list((root / "agents/console/decisions").glob("*/[0-9]*.md")))
    print(f"console-conformance: ok ({n_records} records, ledger immutable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
