"""Regression test for issue #10601.

The s88 sandbox scenario
(``tests/sandbox_scenarios/scenarios/s88_pipeline_flow_counts.py``) hardcoded
its ``STAGE_KEYS`` list, duplicating the canonical ``PIPELINE_STAGES``
definition in ``src/ui/src/constants.js``. When a pipeline stage is added,
removed, or renamed there, the hardcoded copy went stale and the scenario
silently stopped covering the changed stage set -- a false-green rather than a
failure.

The fix derives the scenario's stage keys from the canonical source so drift is
impossible: a stage added/removed/renamed in ``constants.js`` flows through to
the scenario automatically. These are pure source/derivation checks -- the
frontend JS toolchain and the Docker sandbox are not required to run them
(mirrors ``tests/regressions/test_issue_9434.py``).
"""

from __future__ import annotations

import re
from pathlib import Path

import tests.sandbox_scenarios.scenarios.s88_pipeline_flow_counts as s88

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONSTANTS_JS = _REPO_ROOT / "src" / "ui" / "src" / "constants.js"


def _canonical_pipeline_stage_keys() -> list[str]:
    """Extract the PIPELINE_STAGES ``key`` values (in order) from constants.js.

    Independent of the scenario's own parser so the two cannot drift into
    agreement through a shared bug.
    """
    src = _CONSTANTS_JS.read_text(encoding="utf-8")
    block = re.search(r"PIPELINE_STAGES\s*=\s*\[(.*?)\]", src, re.S)
    assert block, f"could not locate PIPELINE_STAGES array in {_CONSTANTS_JS}"
    keys = re.findall(r"key:\s*'([^']+)'", block.group(1))
    assert keys, "PIPELINE_STAGES yielded no stage keys"
    return keys


def test_s88_stage_keys_match_canonical_pipeline_stages_10601() -> None:
    """s88.STAGE_KEYS must equal the canonical PIPELINE_STAGES keys, in order.

    Parity proves the scenario reads its stage set from the same source the
    dashboard derives ``STAGE_KEYS = PIPELINE_STAGES.map(s => s.key)`` from; a
    stage added/removed/renamed in constants.js is reflected here automatically
    instead of leaving a stale hardcoded copy behind.
    """
    assert _canonical_pipeline_stage_keys() == s88.STAGE_KEYS


def test_s88_does_not_hardcode_stage_keys_literal_10601() -> None:
    """The scenario must derive STAGE_KEYS, not assign a string-literal list.

    A literal ``STAGE_KEYS = ["triage", ...]`` is exactly the duplicated,
    drift-prone copy #10601 removes; guard against reintroducing it. The
    canonical set must instead be derived from PIPELINE_STAGES at runtime.
    """
    source = Path(s88.__file__).read_text(encoding="utf-8")
    literal_assignment = re.search(r"STAGE_KEYS\s*=\s*\[\s*['\"]", source)
    assert literal_assignment is None, (
        "s88 STAGE_KEYS is assigned a hardcoded string-literal list; derive it "
        "from the canonical PIPELINE_STAGES (src/ui/src/constants.js) instead "
        "(#10601)."
    )
