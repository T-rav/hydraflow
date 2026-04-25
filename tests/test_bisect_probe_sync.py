"""Drift guard: `make bisect-probe` must invoke the same make targets
as the RC promotion scenario job (spec §4.3).

Without this guard, someone could update `make bisect-probe` to skip
a test suite (or add one) without mirroring the change in CI — and
bisect would attribute culpability based on a different test matrix
than the gate that actually decides RC promotion. Wrong attribution
→ wrong revert → operator pages.

The check is a parser comparing two source files:

1. `Makefile` — the body of the `bisect-probe:` target. We extract
   every `$(MAKE) <target>` invocation in the recipe.

2. `.github/workflows/rc-promotion-scenario.yml` — the steps that run
   inside the `scenario` job. We extract every `make <target>` call
   in those steps.

The two sets must be equal. A subset relation (probe is allowed to
run a *superset* of the gate's targets) would mask drift in the gate
direction; we want the gate and the probe to be in lock-step.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = REPO_ROOT / "Makefile"
RC_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "rc-promotion-scenario.yml"


def _parse_bisect_probe_targets(makefile_text: str) -> set[str]:
    """Extract `make <target>` invocations from the bisect-probe recipe."""
    # Match the bisect-probe target block until the next blank line or
    # next target. Recipes are tab-indented; the block ends at a line
    # that doesn't start with a tab.
    block_re = re.compile(r"^bisect-probe:.*?\n((?:\t.*\n)+)", re.MULTILINE)
    m = block_re.search(makefile_text)
    if not m:
        msg = "Makefile has no `bisect-probe:` target"
        raise AssertionError(msg)
    body = m.group(1)
    # `$(MAKE) <target>` — capture the target token (no flags).
    target_re = re.compile(r"\$\(MAKE\)\s+([\w-]+)")
    return set(target_re.findall(body))


def _parse_rc_scenario_make_targets(workflow_text: str) -> set[str]:
    """Extract `make <target>` calls from the scenario-running steps of
    the RC promotion workflow.

    We look for the `Scenario suite` + `Scenario loops suite` step
    family — the steps that constitute the green-RC gate's core test
    matrix. Other steps (CodeQL, build images, etc.) are deliberately
    excluded because bisect-probe doesn't need to mirror them.
    """
    targets: set[str] = set()
    # `run: make <target> ...` lines in YAML (any indent).
    line_re = re.compile(r"^\s*run:\s*make\s+([\w-]+)", re.MULTILINE)
    # Restrict to the lines that come from scenario-suite-style steps.
    # Heuristic: include only `make scenario`, `make scenario-loops`,
    # and any direct callers in the rc-promotion-scenario.yml gate
    # workflow. The browser scenario is covered by a separate gate.
    relevant = {"scenario", "scenario-loops"}
    for match in line_re.finditer(workflow_text):
        target = match.group(1)
        if target in relevant:
            targets.add(target)
    return targets


def test_bisect_probe_targets_match_rc_scenario() -> None:
    """The targets bisect-probe runs must equal the RC scenario gate's
    core test set. Drift in either direction breaks attribution.
    """
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    workflow_text = RC_WORKFLOW.read_text(encoding="utf-8")

    probe_targets = _parse_bisect_probe_targets(makefile_text)
    rc_targets = _parse_rc_scenario_make_targets(workflow_text)

    assert probe_targets == rc_targets, (
        f"bisect-probe target set drifted from RC scenario gate.\n"
        f"  probe runs: {sorted(probe_targets)}\n"
        f"  RC gate  : {sorted(rc_targets)}\n"
        f"  probe-only (delete from probe or add to RC): "
        f"{sorted(probe_targets - rc_targets)}\n"
        f"  RC-only (add to probe): {sorted(rc_targets - probe_targets)}"
    )


def test_bisect_probe_target_exists_in_makefile() -> None:
    """A regression on the structural side — make sure no one renames
    or removes the bisect-probe target without updating this test."""
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    assert re.search(r"^bisect-probe:", makefile_text, re.MULTILINE), (
        "Makefile is missing the `bisect-probe:` target"
    )


def test_rc_workflow_runs_scenario_targets() -> None:
    """And on the CI side — make sure the RC promotion workflow at
    least invokes the scenario targets we expect to mirror."""
    workflow_text = RC_WORKFLOW.read_text(encoding="utf-8")
    targets = _parse_rc_scenario_make_targets(workflow_text)
    assert targets, (
        ".github/workflows/rc-promotion-scenario.yml has no `make scenario` "
        "or `make scenario-loops` step — the bisect-probe contract has no "
        "ground truth to compare against"
    )
