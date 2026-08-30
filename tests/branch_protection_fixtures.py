"""One definition of the undeclared-legacy-layer fixture (#10148).

Three test modules independently spelled the same five-context list, and all
three rotted together when #11727 moved `quality (.)` from `required_on
["main"]` to `["staging"]`: the audit engine correctly stopped reporting it as
an undeclared layer, and four tests failed asserting it would. Three copies of
one vocabulary is the defect `charter.yaml`'s `actors:` rule refuses by
construction — reproduced inside the tests that guard branch protection.

So the list is DERIVED from the live contract rather than spelled: contexts
the contract does not declare for `staging` are exactly the ones an undeclared
legacy layer on staging must surface. It cannot go stale, because it is
recomputed from the thing that made it stale.
"""

from __future__ import annotations

from pathlib import Path

from scripts.gates.contract import load_gates
from scripts.gates.resolve import resolve_contexts

REPO_ROOT = Path(__file__).resolve().parents[1]
GATES_TOML = REPO_ROOT / "docs/standards/branch_protection/gates.toml"

#: Candidates, in preference order. Every one is a real CI context, so the
#: fixture stays recognisable; the filter below keeps only those the contract
#: does not declare for staging.
_CANDIDATES = (
    "Tests",
    "Type Check",
    "Security Scan",
    "Architecture Check",
    "Lint & Format",
    "Smoke Tests",
    "Scenario Tests",
    "Regression Tests",
    "Principles Audit",
)

#: How many the #10148 scenario needs.
LEGACY_LAYER_SIZE = 5


def undeclared_on_staging() -> list[str]:
    """Five real CI contexts the contract does NOT declare for ``staging``.

    Raises rather than returning a short list: a silently-shrunk fixture would
    weaken every test that consumes it without failing any of them.
    """
    declared = set(resolve_contexts(load_gates(GATES_TOML), "staging"))
    if not declared:
        msg = "no staging contexts resolved — the gate contract went vacuous"
        raise AssertionError(msg)

    available = [name for name in _CANDIDATES if name not in declared]
    if len(available) < LEGACY_LAYER_SIZE:
        msg = (
            f"only {len(available)} of {len(_CANDIDATES)} candidate contexts are "
            f"undeclared for staging ({available}); the #10148 fixture needs "
            f"{LEGACY_LAYER_SIZE}. Add more candidates, or the contract now "
            "declares nearly everything on staging and this scenario needs a "
            "rethink."
        )
        raise AssertionError(msg)
    return available[:LEGACY_LAYER_SIZE]


LEGACY_LAYER_CONTEXTS = undeclared_on_staging()
