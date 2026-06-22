"""Regression test for issue #9224.

Bug: the pipeline flow diagram in the ``Header`` component
(``src/ui/src/components/Header.jsx``) renders two topology errors:

  1. ``REVIEW`` does not fork to its two terminal end-states. ``hitl``
     ("Needs Human") and ``merged`` are both terminals, but the diagram
     sweeps them into the generic post-triage linear chain
     (``postTriage.map`` at lines 285-290), rendering
     ``... review -> hitl -> merged`` with an arrow before ``merged``.
     This implies ``merged`` follows ``hitl``, which is wrong: after
     review an issue goes to a human *or* gets merged, never both.

  2. The ``TRIAGE -> PLAN`` direct path has no explicit arrow. The
     product-track fork renders ``^ discover -> shape v`` on the top arm
     and only the bare text label ``direct`` on the bottom arm
     (``forkBottom`` at lines 279-281) -- there is no arrow glyph or
     arrow element representing the bypass straight to ``plan``.

Expected behaviour after fix (see issue acceptance criteria):
  - After ``review`` the diagram forks into two terminal arms
    (``hitl`` and ``merged``), reusing the existing fork visual treatment
    rather than chaining the terminals linearly.
  - The product-track fork's direct arm renders an explicit arrow to
    ``plan``, not just the word "direct".

Both tests assert the CORRECT (post-fix) topology and are therefore RED
against the current buggy ``Header.jsx``. These are pure source-structure
checks -- the frontend JS toolchain is not required to run them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HEADER_JSX = _REPO_ROOT / "src" / "ui" / "src" / "components" / "Header.jsx"
_CONSTANTS_JS = _REPO_ROOT / "src" / "ui" / "src" / "constants.js"

# Rightward / branch arrow glyphs that can represent a flow edge. The diagram
# currently uses U+2192 (->), U+2197 (^/up-right) and U+2198 (down-right).
_ARROW_GLYPHS = "→↗↘⟶➝⇒⟹⮕▶"


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
        track = re.search(r"track:\s*'([^']+)'", body)
        role = re.search(r"role:\s*(null|'[^']*')", body)
        config_key = re.search(r"configKey:\s*(null|'[^']*')", body)
        stages.append(
            {
                "key": key.group(1),
                "track": track.group(1) if track else None,
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


def _extract_balanced_span(src: str, marker: str) -> str | None:
    """Return the inner content of the ``<span>`` whose attributes contain ``marker``.

    Handles nested ``<span>`` elements via depth counting so that, e.g., the
    ``forkBottom`` arm (which wraps a nested ``forkDirect`` span) is returned in
    full rather than truncated at the first inner ``</span>``.
    """
    idx = src.find(marker)
    if idx == -1:
        return None
    open_tag_end = src.find(">", idx)
    if open_tag_end == -1:
        return None
    depth = 1
    cursor = open_tag_end + 1
    while depth > 0:
        next_open = src.find("<span", cursor)
        next_close = src.find("</span>", cursor)
        if next_close == -1:
            return None
        if next_open != -1 and next_open < next_close:
            depth += 1
            cursor = next_open + len("<span")
        else:
            depth -= 1
            if depth == 0:
                return src[open_tag_end + 1 : next_close]
            cursor = next_close + len("</span>")
    return None


def test_terminal_endstates_are_hitl_and_merged() -> None:
    """Premise: hitl and merged are the diagram's terminal end-states."""
    terminals = _terminal_stage_keys(_read(_CONSTANTS_JS))
    assert set(terminals) == {"hitl", "merged"}, (
        "Expected exactly hitl + merged to be terminal end-states "
        f"(role/configKey null); got {terminals}. The fork-topology checks "
        "below assume these two terminals."
    )


def test_review_forks_to_two_terminal_endstates_not_linear_chain() -> None:
    """REVIEW must branch to the hitl + merged terminals, not chain them linearly.

    Currently Header.jsx renders every post-triage stage (including the two
    terminals) through one flat ``postTriage.map`` with a plain arrow before
    each pill, producing ``review -> hitl -> merged``. The fix introduces a
    review fork analogous to the product-track fork so the terminals render as
    two parallel arms with no trailing arrow.
    """
    header_src = _read(_HEADER_JSX)
    terminals = _terminal_stage_keys(_read(_CONSTANTS_JS))

    # The product-track fork is the only fork present today (single
    # `styles.pipelineFork` usage). A correct fix adds a second fork for the
    # review terminals -- detectable via any of these mutually-tolerant signals
    # so the test accepts either a data-driven or a hardcoded implementation.
    second_fork_block = header_src.count("styles.pipelineFork") >= 2
    terminal_track = ("'terminal'" in header_src) or ('"terminal"' in header_src)
    terminal_set_import = "TERMINAL_STAGE_KEYS" in header_src
    explicit_terminal_keys = all(
        re.search(rf"['\"]{re.escape(key)}['\"]", header_src) for key in terminals
    )

    review_fork_present = (
        second_fork_block
        or terminal_track
        or terminal_set_import
        or explicit_terminal_keys
    )

    assert review_fork_present, (
        "Header.jsx renders the REVIEW terminals (hitl, merged) in the flat "
        "post-triage linear chain instead of forking REVIEW into two terminal "
        "arms. Expected a second fork block (styles.pipelineFork), a "
        "track:'terminal' / TERMINAL_STAGE_KEYS concept, or explicit handling "
        f"of the terminal keys {terminals}. Found none -- issue #9224 bug 1."
    )


def test_triage_fork_has_explicit_direct_arrow_to_plan() -> None:
    """The product-track fork's direct arm must render an explicit arrow, not bare text.

    Today the bottom arm of the fork is only ``<span ...forkDirect>direct</span>``
    -- a text label with no arrow. The fix adds an explicit arrow representing
    the TRIAGE -> PLAN bypass, parallel to the ``^ discover -> shape v`` arc.
    """
    header_src = _read(_HEADER_JSX)

    direct_arm = _extract_balanced_span(header_src, "styles.forkBottom")
    assert direct_arm is not None, (
        "Could not locate the product-track fork's direct arm "
        "(styles.forkBottom) in Header.jsx."
    )

    has_arrow = (
        any(glyph in direct_arm for glyph in _ARROW_GLYPHS)
        or "{arrow}" in direct_arm
        or "forkArrow" in direct_arm
        or "pipelineArrow" in direct_arm
    )

    assert has_arrow, (
        "The TRIAGE -> PLAN direct path in Header.jsx is rendered as a bare "
        "text label ('direct') with no arrow. Expected an explicit arrow "
        "(glyph or arrow element) in the fork's direct arm pointing to plan. "
        f"Direct-arm content was: {direct_arm.strip()!r} -- issue #9224 bug 2."
    )
