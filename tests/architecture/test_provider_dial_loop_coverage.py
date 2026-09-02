"""Every agentic provider dial is a named loop, or says why it is not (#11991).

`orchestrator_common._BACKEND_WORKER_LOOPS` maps a loop to the `*_provider`
dial its spawns route on, and carries a comment asking that it be kept in sync
with the dials in `config.py`. Nothing enforced that, and the consequence it
warns about is silent:

    omitting a core loop here mis-scopes provider credit pauses even though its
    runner correctly routes the actual spawn

So the spawn goes to the right backend and the pause lands on the wrong one —
the runner looks correct at every point a reader would check.

This is also the map #11991's migration has to read. A generated baseline
policy per dial needs to know which spawns each dial governs, and a table that
has quietly fallen behind the dial set would produce a migration missing
exactly the dials nobody noticed were absent.

**Agentic dials only.** A one-shot face is not a loop and has no business in a
loops table; `GATEWAY_ONE_SHOT_PROVIDER_FIELDS` is the repo's own classifier
for that, used here rather than a second spelling of the same judgement.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from config import (  # noqa: E402
    GATEWAY_AGENTIC_PROVIDER_FIELDS,
    HydraFlowConfig,
)
from orchestrator_common import _BACKEND_WORKER_LOOPS  # noqa: E402

#: Agentic dials that are deliberately not loop entries, and why. Each is a
#: claim someone had to write down; an unlisted one fails.
_NOT_A_LOOP: dict[str, str] = {
    "repo_provider": (
        "A repo-wide override, not a loop's dial. `base_runner.apply_repo_provider` "
        "layers it on top of whatever the role already chose, so it has no loop of "
        "its own to scope a credit pause to — it modifies every loop's route."
    ),
    "ac_provider": (
        "The acceptance-criteria generator runs under PostMergeHandler rather "
        "than as a registered background loop, so there is no loop key to file "
        "it under. If it ever becomes one, it belongs in the table and this row "
        "should go."
    ),
}

_DIALS = tuple(
    sorted(n for n in HydraFlowConfig.model_fields if n.endswith("_provider"))
)
_IN_TABLE = frozenset(dial for dial, _model in _BACKEND_WORKER_LOOPS.values())
_AGENTIC = frozenset(GATEWAY_AGENTIC_PROVIDER_FIELDS)


def test_the_dial_set_is_derived_and_non_empty() -> None:
    """Anti-vacuity: an empty dial set would pass every case below."""
    assert len(_DIALS) >= 13
    assert _AGENTIC, "the agentic classification is empty; nothing would be checked"


def test_the_loops_table_is_not_empty() -> None:
    """The other half: an empty table would make every dial look unclaimed."""
    assert len(_IN_TABLE) >= 8


@pytest.mark.parametrize("dial", sorted(_AGENTIC), ids=sorted(_AGENTIC))
def test_an_agentic_dial_is_a_loop_or_says_why_not(dial: str) -> None:
    if dial in _IN_TABLE:
        return

    reason = _NOT_A_LOOP.get(dial)
    assert reason, (
        f"{dial} is an agentic face with no entry in _BACKEND_WORKER_LOOPS and "
        f"no recorded reason. Its spawns route correctly and its credit pause "
        f"is scoped to the wrong provider — the failure the table's own comment "
        f"warns about, and the one a reader cannot see. Add the loop, or record "
        f"here why it is not one."
    )


def test_no_exemption_is_stale() -> None:
    """A dial that became a loop must lose its exemption, not keep it.

    A standing 'not a loop' row for something that IS one would pre-approve the
    exact drift this file exists to catch.
    """
    stale = sorted(set(_NOT_A_LOOP) & _IN_TABLE)

    assert not stale, (
        f"these are recorded as 'not a loop' but appear in the table: {stale}. "
        f"Remove the rows."
    )


def test_every_exemption_names_a_real_dial() -> None:
    unknown = sorted(set(_NOT_A_LOOP) - set(_DIALS))

    assert not unknown, f"these exemptions name dials that no longer exist: {unknown}"
