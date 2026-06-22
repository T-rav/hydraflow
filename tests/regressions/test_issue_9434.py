"""Regression test for issue #9434.

Bug: the *second* pipeline-flow diagram -- the ``PipelineFlow`` component in
``src/ui/src/components/StreamView.jsx`` (``data-testid="pipeline-flow"``) --
has the same linear-terminal topology bug as the Header (issue #9224).

``hitl`` ("Needs Human") and ``merged`` are both *terminal* end-states: after
review an issue goes to a human *or* gets merged, never both. But
``PipelineFlow`` sweeps every post-triage stage (including those two terminals)
into one flat ``postTriageGroups.map`` (StreamView.jsx lines ~108-113), emitting
a ``flowConnector`` before each pill. That renders ``... review -> hitl ->
merged`` -- a linear chain that wrongly implies ``merged`` follows ``hitl`` and
leaves a trailing connector after the ``hitl`` terminal.

The Header already gets a dedicated fix (issue #9224). #9434 asks for the same
``review -> fork(hitl | merged)`` treatment in StreamView so the two
pipeline-flow diagrams are visually consistent, "reusing the new
TERMINAL_STAGE_KEYS set (from constants.js)".

Expected behaviour after fix (issue acceptance criteria):
  - StreamView's ``PipelineFlow`` forks ``review`` into the two terminal arms
    (``hitl`` and ``merged``) using the same fork visual treatment as the
    product-track fork, rather than chaining the terminals linearly.
  - No trailing arrow/connector after either terminal.

This test asserts the CORRECT (post-fix) topology and is therefore RED against
the current buggy ``StreamView.jsx``. It is a pure source-structure check --
the frontend JS toolchain is not required to run it (mirrors
``tests/regressions/test_issue_9224.py``).

NOTE on signal choice: unlike the #9224 Header test, this test does NOT use the
"all terminal keys appear as quoted strings" signal. ``'hitl'`` and ``'merged'``
already appear as quoted literals throughout StreamView.jsx (status comparisons,
the merged-count computation, the no-role label/dot maps) for reasons unrelated
to the fork topology, so that signal is already satisfied and would mask the
bug. We rely instead on signals that are uniquely produced by the fork fix.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STREAMVIEW_JSX = _REPO_ROOT / "src" / "ui" / "src" / "components" / "StreamView.jsx"
_CONSTANTS_JS = _REPO_ROOT / "src" / "ui" / "src" / "constants.js"


def _read(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"expected source file is missing: {path}")
    return path.read_text(encoding="utf-8")


def _parse_pipeline_stages(constants_src: str) -> list[dict]:
    """Extract the PIPELINE_STAGES entries (key / track / role) from constants.js."""
    block = re.search(r"PIPELINE_STAGES\s*=\s*\[(.*?)\]", constants_src, re.S)
    assert block, "could not locate PIPELINE_STAGES array in constants.js"
    stages: list[dict] = []
    for entry in re.finditer(r"\{([^}]*)\}", block.group(1)):
        body = entry.group(1)
        key = re.search(r"key:\s*'([^']+)'", body)
        if not key:
            continue
        role = re.search(r"role:\s*(null|'[^']*')", body)
        config_key = re.search(r"configKey:\s*(null|'[^']*')", body)
        stages.append(
            {
                "key": key.group(1),
                "role_is_null": bool(role and role.group(1) == "null"),
                "config_key_is_null": bool(
                    config_key and config_key.group(1) == "null"
                ),
            }
        )
    return stages


def _terminal_stage_keys(constants_src: str) -> list[str]:
    """Terminal end-states = stages with no processing role and no config knob."""
    return [
        s["key"]
        for s in _parse_pipeline_stages(constants_src)
        if s["role_is_null"] and s["config_key_is_null"]
    ]


def test_terminal_endstates_are_hitl_and_merged() -> None:
    """Premise: hitl and merged are the diagram's terminal end-states.

    Shared with the #9224 Header test -- both pipeline-flow diagrams derive
    their terminals from the same PIPELINE_STAGES definition.
    """
    terminals = _terminal_stage_keys(_read(_CONSTANTS_JS))
    assert set(terminals) == {"hitl", "merged"}, (
        "Expected exactly hitl + merged to be terminal end-states "
        f"(role/configKey null); got {terminals}. The fork-topology check "
        "below assumes these two terminals."
    )


def test_streamview_pipelineflow_forks_review_into_terminals_not_linear_chain() -> None:
    """StreamView's PipelineFlow must fork review into hitl + merged, not chain them.

    Currently StreamView.jsx builds ``postTriageGroups`` as every non-triage
    main-track group -- which INCLUDES the hitl and merged terminals -- and
    renders them through one flat ``.map`` with a ``flowConnector`` before each
    pill (``review -> hitl -> merged``). The fix introduces a review fork
    (analogous to the existing product-track fork) so the two terminals render
    as parallel arms with no trailing connector.

    Detected via mutually-tolerant signals so the test accepts either a
    data-driven (TERMINAL_STAGE_KEYS / track:'terminal') or a hardcoded
    (second fork block) implementation. Every signal below is FALSE against the
    current buggy source, so the assertion fails until the fork is added.
    """
    src = _read(_STREAMVIEW_JSX)
    terminals = _terminal_stage_keys(_read(_CONSTANTS_JS))

    # The product-track fork is the only fork present today (single
    # `styles.flowFork` container usage). A correct fix adds a second fork for
    # the review terminals.
    second_fork_block = len(re.findall(r"styles\.flowFork\b", src)) >= 2

    # A data-driven fix may introduce a 'terminal' track in PIPELINE_STAGES and
    # branch on it here, mirroring the existing PRODUCT_TRACK_KEYS handling.
    terminal_track = ("'terminal'" in src) or ('"terminal"' in src)

    # The issue explicitly suggests reusing the new TERMINAL_STAGE_KEYS set from
    # constants.js to split the terminals out of the linear postTriage chain.
    terminal_set_used = "TERMINAL_STAGE_KEYS" in src

    # A fix may name the new fork concept directly.
    terminal_fork_named = bool(
        re.search(r"(terminal|review)\s*Fork|fork\s*Terminal|terminalGroups", src, re.I)
    )

    review_fork_present = (
        second_fork_block or terminal_track or terminal_set_used or terminal_fork_named
    )

    assert review_fork_present, (
        "StreamView.jsx's PipelineFlow renders the REVIEW terminals "
        f"({terminals}) in the flat post-triage linear chain "
        "(postTriageGroups.map) instead of forking REVIEW into two terminal "
        "arms. Expected a second fork block (styles.flowFork), a "
        "track:'terminal' / TERMINAL_STAGE_KEYS concept, or a named terminal "
        "fork -- found none. The two pipeline-flow diagrams (Header + "
        "StreamView) are therefore visually inconsistent -- issue #9434."
    )
