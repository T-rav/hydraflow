"""Ratchet guard: structural test redundancy may not rise above the committed marks.

``erosion.suite_hygiene`` counts parametrize copies (≥3 tests in one file with
identical normalized bodies) and cross-file duplicate tests (same name + body
in ≥2 files). ``disturbance/baselines/suite_hygiene.yaml`` records the marks
at introduction; a PR that adds another copy-paste test above either mark
fails here with the exact groups to collapse. Falling is never a failure —
after a pruning pass, lock the lower marks in with
``python scripts/regen_suite_hygiene_baseline.py --reason "..."``.

Runs in the UNGATED ``aggregate-ratchets`` CI lane (#11730). Its subject is
every pytest-collected module under ``tests/``, so no paths-filter can be wide
enough to trigger it correctly — see
``tests/architecture/aggregate_gate_registry.py``.
"""

from __future__ import annotations

from pathlib import Path

from erosion.suite_hygiene import collect_tests, compute
from erosion.suite_hygiene_baseline import exceeded, load_suite_hygiene_baseline

_BASELINE_REL = "disturbance/baselines/suite_hygiene.yaml"


def test_the_scan_actually_has_a_subject(real_repo_root: Path) -> None:
    """A run that measured nothing must fail, not pass (#11730).

    Both halves of this gate compare a COUNT against a mark, and every count
    over an empty tree is zero — comfortably under every mark. So a scan that
    collected nothing (wrong root, a shallow/sparse checkout, ``collect_tests``
    re-pointed, the tests moved) reports a serene green while measuring its
    subject not at all. That is the same failure this gate's own trigger had:
    silence read as safety. Assert the subject exists before believing the
    verdict about it.
    """
    finding = compute(collect_tests(real_repo_root / "tests"))

    assert finding.total_files and finding.total_tests, (
        "The suite-hygiene scan collected "
        f"{finding.total_files} files / {finding.total_tests} tests under "
        f"{real_repo_root / 'tests'} — nothing to measure, so the ratchet "
        "below would pass vacuously against any mark. The tree is missing, "
        "empty, or collect_tests no longer matches this repo's pytest "
        "python_files globs."
    )


def test_structural_redundancy_does_not_exceed_baseline(real_repo_root: Path) -> None:
    finding = compute(collect_tests(real_repo_root / "tests"))
    baseline = load_suite_hygiene_baseline(real_repo_root / _BASELINE_REL)

    assert baseline.parametrize_copies is not None, (
        f"{_BASELINE_REL} records no parametrize_copies mark, so `exceeded` "
        "returns nothing and this gate passes no matter how far the count "
        "rises. A missing mark is a disabled ratchet, not a permissive one."
    )

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
        "\n\nIf `Aggregate Ratchets` is red on the base branch too, this breach "
        "predates your PR: several changes, each green against its own merge "
        "base, summed past the mark. Heal the base branch — do not raise it."
    )
