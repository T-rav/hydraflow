"""The loops the README names as having a model dial must actually have one.

README line: "Each loop that dispatches an LLM call has its own
`HYDRAFLOW_*_MODEL` env var for cost tuning (...)". That parenthesised list
named eight loops; **four had no config field at all** — `sentry` and
`code_grooming`, `memory_judge`, `memory_compaction`. The sentry one outlived
the loop ADR-0118 deleted, so the README was telling operators to tune a
variable that does nothing, for a loop that does not run.

Prose that names a symbol is a citation, and a citation nothing checks decays
into confident fiction. This is the cheapest possible check on that one
sentence: every name it lists must resolve to a `<name>_model` config field.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from config import HydraFlowConfig  # noqa: E402

_SENTENCE = re.compile(
    r"has its own `HYDRAFLOW_\*_MODEL` env var for cost tuning \(([^)]*)\)"
)


def _listed_loops() -> list[str]:
    text = (_REPO / "README.md").read_text(encoding="utf-8")
    match = _SENTENCE.search(text)
    assert match, (
        "the README sentence this guards has been reworded — update the pattern "
        "rather than deleting the guard, or the list goes unchecked again"
    )
    return [name.strip() for name in match.group(1).split(",") if name.strip()]


@pytest.mark.parametrize("loop", _listed_loops())
def test_each_listed_loop_has_a_model_field(loop: str) -> None:
    field = f"{loop}_model"

    assert field in HydraFlowConfig.model_fields, (
        f"README lists '{loop}' as having a model dial, but "
        f"HydraFlowConfig has no '{field}'. Either the loop was removed and the "
        "README kept its name, or the field was renamed."
    )


def test_the_list_is_not_empty() -> None:
    """The decoy: an empty list would make the parametrised check vacuous."""
    assert _listed_loops(), "parsed no loop names — the guard asserts nothing"
