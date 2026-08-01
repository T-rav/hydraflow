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
  6. Ledger immutability — no record modified after its creating commit
     (corrections are new records).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ENFORCEMENT_RE = re.compile(
    r"\*\*Enforcement:\*\*\s+(enforced|process-gated|decision-of-record)"
)
REQUIRED_FIELDS = ("**Date:**", "**Seats:**", "**Verdict:**", "**Evidence:**")
STALENESS_LIMIT = 5


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
        out = subprocess.run(
            [
                "git",
                "log",
                "--diff-filter=M",
                "--format=%h %s",
                "--",
                f"{decisions}/*/",
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=root,
        ).stdout.strip()
        if out:
            errors.append(
                "record immutability violated (corrections must be new records):\n"
                f"    {out}"
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
