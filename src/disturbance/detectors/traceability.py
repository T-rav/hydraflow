"""Untraced-requirement-fraction detector (CH-5, #9733).

Reads the committed traceability matrix artifact and emits one finding per
untraced *percentage point* (the ``<!-- untraced-pct: NN -->`` marker), all
sharing a single signature. Under the standard ``{signature: count}``
baseline this ratchets the fraction itself: the percentage may only shrink
(prune the baseline when it does), and a rise past the baseline blocks.

Pure file read, like every detector: git scanning lives in the arch
runner that *generates* the matrix, so the ratchet only moves when a
regenerated artifact is committed — keeping the gate deterministic for a
given checkout.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from disturbance.models import Finding

if TYPE_CHECKING:
    from pathlib import Path

_ARTIFACT_REL = "docs/arch/generated/traceability_matrix.md"
_MARKER_RE = re.compile(r"<!--\s*untraced-pct:\s*(?P<pct>\d+)\s*-->")


class TraceabilityDetector:
    name = "traceability"

    def __init__(self, artifact_rel: str = _ARTIFACT_REL) -> None:
        self._artifact_rel = artifact_rel

    def detect(self, repo_root: Path) -> list[Finding]:
        path = repo_root / self._artifact_rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []  # no matrix artifact → dimension is inert
        match = _MARKER_RE.search(text)
        if match is None:
            return []
        pct = min(int(match.group("pct")), 100)
        finding = Finding(
            dimension=self.name,
            path=self._artifact_rel,
            signature=f"{self._artifact_rel}::untraced-pct",
            message=(
                f"{pct}% of recent PR-merge commits carry no Req-ID line "
                "(requirements-traceability adoption ratchet)"
            ),
        )
        return [finding] * pct
