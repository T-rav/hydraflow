"""Ratchet guard: no NEW god-files beyond the committed baseline (#10840).

The concentration counter-metric to ``erosion.spread`` (god-file / fan-in) is
made to *flow* by this gate: it computes the live file-level fan-in of ``src/``
and fails if any module has crossed the god-file threshold that the committed
baseline (``disturbance/baselines/concentration.yaml``) did not grandfather.

Adopting a new god-file is then a conscious act — regenerate the baseline via
``scripts/regen_concentration_baseline.py --reason "..."`` when the new
concentration point is a reviewed decision. Fan-in churn on the EXISTING gods
(``models``, ``config``, …) never trips this — only a genuinely new one does.
"""

from __future__ import annotations

from pathlib import Path

from erosion.concentration import compute, extract_file_import_graph
from erosion.concentration_baseline import (
    load_concentration_baseline,
    new_god_files,
)

_BASELINE_REL = "disturbance/baselines/concentration.yaml"


def test_no_new_god_files_beyond_baseline(real_repo_root: Path) -> None:
    finding = compute(extract_file_import_graph(real_repo_root / "src"))
    baseline = load_concentration_baseline(real_repo_root / _BASELINE_REL)
    new = new_god_files(finding, baseline)
    assert not new, (
        "New god-file(s) crossed the concentration threshold "
        f"(fan-in ≥ {finding.threshold}) that the baseline did not grandfather:\n  "
        + "\n  ".join(f"{g.module} ({g.fan_in} dependents)" for g in new)
        + "\n\nA new module that much of the codebase now depends on is a "
        "concentration point (#10840). If this is a reviewed, deliberate choice, "
        "regenerate the baseline:\n  python scripts/regen_concentration_baseline.py "
        '--reason "<why>"'
    )
    # Note: a baseline entry falling BELOW threshold (a god-file that improved) is
    # deliberately NOT a failure — that is good news, and gating it would punish
    # decomposition. Only a NEW god-file trips the ratchet.
