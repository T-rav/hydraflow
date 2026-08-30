"""Regression: `main` requires the CI Gate umbrella, not two no-op contexts.

#11727 measured that `main protect`'s two `quality (<dir>)` required contexts
are **vacuous by construction**: `quality (.)` short-circuits every heavy step
("Root covered by ci.yml lanes"), and `src/ui` has no Makefile, so both fall
through to the no-op branch. Two required checks that report SUCCESS by
construction and can never fail for a code reason.

A vacuous required gate is worse than a missing one: it reads as coverage on
the branch-protection page while gating nothing, which is the same shape as
the guards that were watching nothing elsewhere in this repo.

The replacement is the `CI Gate` umbrella, whose `needs:` fans in every lane —
including `arch`, `aggregate-ratchets`, `gateway-package-coverage`, `ui-build`
and `scenario-browser-fast`, five gates `main` did **not** require while it
enumerated lanes individually. So this is strictly stronger, not a relaxation.

Why a test rather than trusting the live ruleset: `gates.toml` is the source
`scripts/setup_branch_protection.py` PUTs from. While it still declared the
individual lanes, running that sanctioned script would have silently REVERTED
`main` to the weaker set and re-added both no-ops — a live drift measured on
2026-08-29, where canonical said 14 contexts and live said 5.
"""

from __future__ import annotations

from pathlib import Path

from scripts.gates.contract import load_gates
from scripts.gates.resolve import resolve_contexts

REPO_ROOT = Path(__file__).resolve().parents[2]
GATES = REPO_ROOT / "docs/standards/branch_protection/gates.toml"

#: Contexts measured in #11727 as no-ops: every heavy step short-circuits.
VACUOUS = ("quality (.)", "quality (src/ui)")


def _main_contexts() -> set[str]:
    return set(resolve_contexts(load_gates(GATES), "main"))


def test_main_requires_the_ci_gate_umbrella() -> None:
    contexts = _main_contexts()

    # Anti-vacuity: an empty context set would satisfy "no no-ops" trivially
    # while leaving `main` unprotected entirely.
    assert len(contexts) >= 4, (
        f"main declares only {len(contexts)} required contexts: {sorted(contexts)}"
    )
    assert "CI Gate" in contexts, (
        "main must require the CI Gate umbrella — it fans in every lane via "
        "`needs:`, including five (arch, aggregate-ratchets, "
        "gateway-package-coverage, ui-build, scenario-browser-fast) that main "
        "did not require when it enumerated lanes individually"
    )


def test_main_does_not_require_a_context_that_cannot_fail() -> None:
    present = sorted(set(VACUOUS) & _main_contexts())
    assert not present, (
        f"main requires {present}, which #11727 measured as no-ops: they "
        "report SUCCESS by construction and gate nothing, while reading as "
        "coverage on the branch-protection page"
    )
