"""Ratchet guard: no NEW god file or god class beyond the committed mass baseline.

The size axis of the god-file family. ``test_concentration_ratchet`` gates
fan-in (#10840); this gate computes the live LOC / method-count reading of
``src/`` (``erosion.mass``) and fails if a file or class crossed a mass
threshold that ``disturbance/baselines/mass.yaml`` did not grandfather.
Growing an existing god class never trips this (the ErosionMetricsLoop files
that as a roster refresh); only a genuinely new one does. Adopting one is a
conscious act: ``python scripts/regen_mass_baseline.py --reason "..."``.
"""

from __future__ import annotations

from pathlib import Path

from erosion.mass import collect_sources, compute
from erosion.mass_baseline import load_mass_baseline, new_god_classes, new_god_files

_BASELINE_REL = "disturbance/baselines/mass.yaml"


def test_no_new_god_files_or_classes_beyond_baseline(real_repo_root: Path) -> None:
    finding = compute(collect_sources(real_repo_root / "src"))
    baseline = load_mass_baseline(real_repo_root / _BASELINE_REL)

    new_files = new_god_files(finding, baseline)
    new_classes = new_god_classes(finding, baseline)

    assert not new_files and not new_classes, (
        "New god file(s)/class(es) crossed the mass threshold that the baseline "
        "did not grandfather:\n  "
        + "\n  ".join(
            [
                f"{g.path} ({g.loc} LOC >= {finding.file_loc_threshold})"
                for g in new_files
            ]
            + [
                f"{c.key} ({c.loc} LOC, {c.methods} methods; thresholds "
                f"{finding.class_loc_threshold} LOC / {finding.class_method_threshold} methods)"
                for c in new_classes
            ]
        )
        + "\n\nSplit the class (extract a cohesive cluster into a new module and "
        "re-export — see the open 'Erosion: … god class' issue for the recipe), or, "
        "if this size is a reviewed decision, regenerate the baseline:\n  "
        'python scripts/regen_mass_baseline.py --reason "<why>"'
    )
    # A baseline entry that shrank below threshold is deliberately NOT a failure —
    # that is decomposition working; only a NEW entry trips the ratchet.
