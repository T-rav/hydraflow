"""Every Accepted ADR carries a ``**Date:**`` frontmatter line (#10939).

Month-bucketed instruments over the ADR corpus (the ADR-quality setpoint series)
can only cover ADRs that declare a date. A contiguous undated era is worse than a
random gap. This guard fails if an Accepted ADR is missing its ``**Date:**`` line,
so the undated set can never grow back.
"""

from __future__ import annotations

import re
from pathlib import Path

_ACCEPTED_RE = re.compile(
    r"(?:^|\n)(?:-\s*\*\*Status:\*\*|##\s*Status)\s*[:\n]*\s*Accepted"
)
_DATE_RE = re.compile(r"\*\*Date:\*\*")


def test_every_accepted_adr_has_a_date_line(real_repo_root: Path) -> None:
    adr_dir = real_repo_root / "docs" / "adr"
    undated: list[str] = []
    for adr in sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md")):
        text = adr.read_text(encoding="utf-8")
        if _ACCEPTED_RE.search(text) and not _DATE_RE.search(text):
            undated.append(adr.name)

    assert undated == [], (
        "Accepted ADRs missing a `**Date:**` frontmatter line (#10939). Add one "
        "(the authored date):\n  " + "\n  ".join(undated)
    )
