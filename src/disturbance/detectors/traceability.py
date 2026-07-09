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

import yaml

from disturbance.models import Finding

if TYPE_CHECKING:
    from pathlib import Path

_ARTIFACT_REL = "docs/arch/generated/traceability_matrix.md"
_BASELINE_REL = "disturbance/baselines/traceability.yaml"
_MARKER_RE = re.compile(r"<!--\s*untraced-pct:\s*(?P<pct>\d+)\s*-->")
_SIGNATURE = f"{_ARTIFACT_REL}::untraced-pct"


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


def sync_traceability_baseline(repo_root: Path) -> bool:
    """Prune the traceability baseline to the regenerated matrix's pct.

    The matrix and the ratchet baseline are two views of one number: when
    a regen (``make arch-regen`` / ``DiagramLoop``) commits a matrix with
    a *lower* ``<!-- untraced-pct: N -->`` than the baseline count, the
    gate's ``resolved`` assertion would fail on the next unrelated PR
    unless the baseline shrinks in the same change. This helper keeps
    them in lockstep.

    Ratchet-preserving by construction: the baseline count only ever
    moves DOWN. A marker above the baseline is left alone so the gate
    still blocks growth as ``new``. Missing artifact, missing marker, or
    missing baseline file are all inert (the dimension simply isn't
    adopted in that checkout).

    Returns True when the baseline file was rewritten.
    """
    artifact = repo_root / _ARTIFACT_REL
    baseline_path = repo_root / _BASELINE_REL
    try:
        text = artifact.read_text(encoding="utf-8")
        raw = yaml.safe_load(baseline_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return False
    match = _MARKER_RE.search(text)
    if match is None:
        return False
    pct = min(int(match.group("pct")), 100)

    entries = dict(raw.get("entries") or {})
    if _SIGNATURE not in entries:
        return False
    current = int(entries[_SIGNATURE])
    if pct >= current:
        return False  # equal → nothing to do; higher → the gate must block it

    if pct == 0:
        del entries[_SIGNATURE]
    else:
        entries[_SIGNATURE] = pct
    raw["entries"] = entries
    baseline_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return True
