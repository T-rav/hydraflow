"""Ratchet guard: structural test redundancy may not rise above the committed marks.

``erosion.suite_hygiene`` counts parametrize copies (≥3 tests in one file with
identical normalized bodies) and cross-file duplicate tests (same name + body
in ≥2 files). ``disturbance/baselines/suite_hygiene.yaml`` records the marks
at introduction; a PR that adds another copy-paste test above either mark
fails here with the exact groups to collapse. Falling is never a failure —
after a pruning pass, lock the lower marks in with
``python scripts/regen_suite_hygiene_baseline.py --reason "..."``.
"""

from __future__ import annotations

from pathlib import Path

from erosion.suite_hygiene import collect_tests, compute
from erosion.suite_hygiene_baseline import exceeded, load_suite_hygiene_baseline

_BASELINE_REL = "disturbance/baselines/suite_hygiene.yaml"


def test_structural_redundancy_does_not_exceed_baseline(real_repo_root: Path) -> None:
    finding = compute(collect_tests(real_repo_root / "tests"))
    baseline = load_suite_hygiene_baseline(real_repo_root / _BASELINE_REL)

    messages = exceeded(finding, baseline)

    largest = finding.parametrize_groups[:5]
    assert not messages, (
        "Test-suite structural redundancy rose above the committed marks: "
        + "; ".join(messages)
        + "\n\nLargest parametrize groups right now:\n  "
        + "\n  ".join(f"{g.path}: {', '.join(g.names[:6])}" for g in largest)
        + "\n\nCollapse the new copies into @pytest.mark.parametrize (or delete the "
        "cross-file duplicate) rather than moving the mark. If the rise is a "
        "reviewed decision:\n  "
        'python scripts/regen_suite_hygiene_baseline.py --reason "<why>"'
    )
