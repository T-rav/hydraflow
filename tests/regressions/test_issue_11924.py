"""Regression pins for #11924 — escape ``sampled-audit:11403:0bae96175dde``.

The sampled re-audit of PR #11403 (find #11414) upheld this finding:

    The reducer branches that reset pipelineIssues to emptyPipeline outside of
    the authoritative-snapshot path -- SELECT_REPO on a repo change,
    SESSION_RESET, and the isSessionStart branch -- do not touch
    pipelineSnapshotAt. [...] pipelineIssues goes empty while the staleness
    signal still reads fresh, so the console renders a confidently-empty rail
    with no 'resyncing...' chip until the next authoritative snapshot arrives.

The #11414 fix (squashed onto `staging` from ``e86be4770``) repaired exactly
ONE of the two staleness signals the rail carries.  It stamps
``pipelineSnapshotAt: null`` at all three clear sites, which fixes
``OperatorConsole`` -> ``PipelineRail`` (``isPipelineResyncing(socket.pipelineSnapshotAt)``,
``OperatorConsole.jsx:250``).

It left ``pipelineSnapshotReady`` alone -- and that is the signal the OTHER
consumer reads.  ``StreamView`` derives its badge from
``resyncing={pipelineSnapshotReady === false}`` (``StreamView.jsx:448``), and
``pipelineSnapshotReady`` defaults to ``true`` and is only ever written by the
``PIPELINE_SNAPSHOT`` case.  So after a session reset / repo switch /
orchestrator session start the main console still shows the confidently-empty
rail the escape describes: cards gone, no ``pipeline-resyncing-badge``.

The shipped encoding for #11414 -- ``src/ui/src/context/__tests__/railFreshnessReset.test.jsx``
-- drives only ``SESSION_RESET`` and only asserts on ``pipelineSnapshotAt``, so
neither the sibling reset paths nor the sibling consumer were ever exercised.

These pins are deliberately stated over the RENDERED badge rather than over a
flag, so they go green under either accepted remedy:

  A. the reducer also clears ``pipelineSnapshotReady`` at the three clear sites;
  B. ``StreamView`` derives ``resyncing`` from the ``pipelineSnapshotAt``
     freshness stamp instead of the ready flag.

Both were simulated against a patched copy of ``src/ui/src`` (never the repo)
while writing this file: A turns all three red pins green, B turns all three
green as well, and every control below survives both.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = REPO_ROOT / "src" / "ui"
UI_SRC = UI_ROOT / "src"
NODE_MODULES = UI_ROOT / "node_modules"
VITEST_RUNNER = UI_ROOT / "scripts" / "run-vitest.cjs"

requires_ui_toolchain = pytest.mark.skipif(
    shutil.which("node") is None
    or not NODE_MODULES.is_dir()
    or not VITEST_RUNNER.is_file(),
    reason="node + src/ui/node_modules are required to drive the real reducer/StreamView",
)

VITEST_CONFIG = """\
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { fs: { strict: false } },
  test: { environment: 'jsdom', globals: true, include: ['*.test.jsx'] },
})
"""

# `vi.mock` is hoisted above every binding in the module, so the module paths
# must be inlined string LITERALS here -- a `${UI}` template reference throws
# "Cannot access 'UI' before initialization" at collection time.
SPEC = """\
import React from 'react'
import {{ describe, it, expect, vi, beforeEach }} from 'vitest'
import {{ render, screen, cleanup }} from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('{ui_src}/context/HydraFlowContext', async (importOriginal) => ({{
  ...(await importOriginal()),
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}}))

const {{ reducer, initialState }} = await import('{ui_src}/context/HydraFlowContext')
const {{ StreamView }} = await import('{ui_src}/components/StreamView')

// Wall-clock "now": remedy B compares the stamp against Date.now(), so a
// fixed epoch would make the fresh-rail control stale for a fixture reason.
const NOW = Date.now()

/** A rail that has been authoritatively snapshotted AND has cards in it. */
const seeded = () => reducer(initialState, {{
  type: 'PIPELINE_SNAPSHOT',
  data: {{ plan: [{{ number: 1, title: 'seeded' }}] }},
  at: NOW,
}})

const railIsEmpty = (state) =>
  Object.values(state.pipelineIssues).every((issues) => (issues?.length || 0) === 0)

function mount(state) {{
  mockUseHydraFlow.mockReturnValue({{
    pipelineIssues: state.pipelineIssues,
    prs: [],
    stageStatus: {{}},
    workers: {{}},
    config: {{}},
    pipelineSnapshotReady: state.pipelineSnapshotReady,
    pipelineSnapshotAt: state.pipelineSnapshotAt,
  }})
  render(
    <StreamView
      intents={{[]}}
      expandedStages={{{{}}}}
      onToggleStage={{() => {{}}}}
      onRequestChanges={{() => {{}}}}
    />,
  )
}}

const badge = () => screen.queryByTestId('pipeline-resyncing-badge')

const RESET_ACTIONS = {{
  session_reset: {{ type: 'SESSION_RESET' }},
  repo_switch: {{ type: 'SELECT_REPO', data: {{ slug: 'owner/other' }} }},
  session_start: {{ type: 'orchestrator_status', data: {{ status: 'running', reset: true }} }},
}}

beforeEach(() => {{
  cleanup()
  mockUseHydraFlow.mockReset()
}})

describe('#11924 / escape sampled-audit:11403:0bae96175dde', () => {{
  it('session reset never renders a confidently-empty rail', () => {{
    const state = reducer(seeded(), RESET_ACTIONS.session_reset)
    expect(railIsEmpty(state)).toBe(true)
    mount(state)
    expect(badge()).not.toBeNull()
  }})

  it('repo switch never renders a confidently-empty rail', () => {{
    const state = reducer(seeded(), RESET_ACTIONS.repo_switch)
    expect(railIsEmpty(state)).toBe(true)
    mount(state)
    expect(badge()).not.toBeNull()
  }})

  it('orchestrator session start never renders a confidently-empty rail', () => {{
    const state = reducer(seeded(), RESET_ACTIONS.session_start)
    expect(railIsEmpty(state)).toBe(true)
    mount(state)
    expect(badge()).not.toBeNull()
  }})

  // ---- controls: green today, and green under either remedy --------------

  it('an authoritative populated snapshot is presented as truth', () => {{
    const state = seeded()
    expect(railIsEmpty(state)).toBe(false)
    mount(state)
    expect(badge()).toBeNull()
  }})

  it('a not-ready snapshot over a populated rail still warns (#11279)', () => {{
    const state = reducer(seeded(), {{
      type: 'PIPELINE_SNAPSHOT',
      data: {{ plan: [] }},
      ready: false,
      at: NOW,
    }})
    mount(state)
    expect(badge()).not.toBeNull()
  }})

  it('every reset path still clears the #11414 freshness stamp', () => {{
    for (const action of Object.values(RESET_ACTIONS)) {{
      const state = reducer(seeded(), action)
      expect(railIsEmpty(state)).toBe(true)
      expect(state.pipelineSnapshotAt).toBeNull()
    }}
  }})
}})
"""

# vitest title -> what it proves.  Split out so each pytest case names one
# assertion instead of one opaque "the suite failed".
RED_PINS = {
    "session reset never renders a confidently-empty rail": (
        "SESSION_RESET empties pipelineIssues but leaves pipelineSnapshotReady "
        "true, so StreamView renders an empty rail with no resyncing badge"
    ),
    "repo switch never renders a confidently-empty rail": (
        "SELECT_REPO on a repo change empties pipelineIssues but leaves "
        "pipelineSnapshotReady true, so the new scope's empty rail reads as truth"
    ),
    "orchestrator session start never renders a confidently-empty rail": (
        "orchestrator_status reset=true empties pipelineIssues but leaves "
        "pipelineSnapshotReady true, so the restarted rail reads as truth"
    ),
}

CONTROLS = (
    "an authoritative populated snapshot is presented as truth",
    "a not-ready snapshot over a populated rail still warns (#11279)",
    "every reset path still clears the #11414 freshness stamp",
)


@lru_cache(maxsize=1)
def _vitest_results() -> dict[str, str]:
    """Run the spec once in a throwaway project OUTSIDE the repo.

    Outside, so ``src/ui``'s own vitest run never collects this pin; the
    symlinked ``node_modules`` is what lets vite resolve react/testing-library
    from a /tmp root.
    """
    tmp = Path(tempfile.mkdtemp(prefix="hf_issue_11924_"))
    try:
        os.symlink(NODE_MODULES, tmp / "node_modules")
        (tmp / "vitest.config.mjs").write_text(VITEST_CONFIG)
        (tmp / "rail.test.jsx").write_text(SPEC.format(ui_src=UI_SRC))
        report = tmp / "report.json"
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                "node",
                str(VITEST_RUNNER),
                "run",
                "--root",
                str(tmp),
                "--reporter=json",
                f"--outputFile={report}",
            ],
            cwd=UI_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if not report.is_file():
            raise AssertionError(f"vitest produced no report under {tmp}")
        payload = json.loads(report.read_text())
        return {
            assertion["title"]: assertion["status"]
            for file_result in payload.get("testResults", [])
            for assertion in file_result.get("assertionResults", [])
        }
    finally:
        # Drop the symlink FIRST so the cleanup never walks the real tree.
        (tmp / "node_modules").unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)


@requires_ui_toolchain
@pytest.mark.parametrize("title", sorted(RED_PINS))
def test_reset_paths_never_present_an_empty_rail_as_truth(title: str) -> None:
    results = _vitest_results()
    assert title in results, f"vitest never ran {title!r}; got {sorted(results)}"
    assert results[title] == "passed", (
        f"{RED_PINS[title]}.\n\n"
        "#11414 stamped pipelineSnapshotAt: null at this clear site, which "
        "repairs OperatorConsole/PipelineRail — but StreamView reads "
        "pipelineSnapshotReady (StreamView.jsx:448), which no reset path "
        "touches. The escape's 'stale/empty rail presented as truth with no "
        "staleness signal' therefore still ships on the main console "
        "(escape sampled-audit:11403:0bae96175dde, #11924)."
    )


@requires_ui_toolchain
@pytest.mark.parametrize("title", CONTROLS)
def test_control_holds(title: str) -> None:
    """Green today; a remedy that breaks one of these has over-corrected."""
    results = _vitest_results()
    assert title in results, f"vitest never ran {title!r}; got {sorted(results)}"
    assert results[title] == "passed", (
        f"control {title!r} regressed — the rail must still present a fresh, "
        "populated, authoritative snapshot as truth, must still warn on a "
        "not-ready snapshot (#11279), and must keep the #11414 stamp reset."
    )


# ---------------------------------------------------------------------------
# The ratchet: one question, one answer.
#
# The pins above are about three reset paths. This is about the shape that let
# a fixed defect ship a second time: the rail's staleness question had TWO
# derivations, in two components, and repairing one said nothing about the
# other. A third consumer is free to invent a fourth rule unless something
# forbids it.
#
# The guarded set is DERIVED, never spelled. Spelling it would pass forever
# while a file added tomorrow reads a raw signal — the same N-1 coverage that
# put us here.
# ---------------------------------------------------------------------------

#: Raw staleness state. Only the reducer may write these and only the
#: freshness util may interpret them; everyone else asks `railIsResyncing`.
_RAW_RAIL_SIGNALS = ("pipelineSnapshotReady", "pipelineSnapshotAt")

#: The two files that are allowed to name a raw signal, by role: the reducer
#: that owns the state, and the util that turns it into the one answer.
_SIGNAL_OWNERS = {
    Path("src") / "ui" / "src" / "context" / "HydraFlowContext.jsx",
    Path("src") / "ui" / "src" / "utils" / "pipelineFreshness.js",
}


def _ui_sources() -> list[Path]:
    return [
        path
        for pattern in ("*.js", "*.jsx")
        for path in UI_SRC.rglob(pattern)
        if "__tests__" not in path.parts and "node_modules" not in path.parts
    ]


def test_no_component_derives_rail_staleness_from_a_raw_signal() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _ui_sources():
        relative = path.relative_to(REPO_ROOT)
        if relative in _SIGNAL_OWNERS:
            continue
        text = path.read_text(encoding="utf-8")
        named = [signal for signal in _RAW_RAIL_SIGNALS if signal in text]
        if named and "railIsResyncing" not in text:
            offenders[str(relative)] = named

    assert not offenders, (
        "these read the rail's raw staleness state without going through "
        f"railIsResyncing: {offenders}. The rail carries two independent "
        "signals and neither implies the other, so a component that consults "
        "one of them answers a different question than the rest of the "
        "console. That is exactly how the #11414 fix repaired "
        "OperatorConsole and left StreamView shipping the same "
        "confidently-empty rail (#11924). Ask railIsResyncing, or extend it."
    )


def test_the_one_answer_still_reads_every_raw_signal() -> None:
    """The guard above is worthless if the util stops consulting a signal.

    Dropping a term from `railIsResyncing` would make every consumer agree —
    on the wrong answer — while the membership check above stayed green.
    """
    util = (UI_SRC / "utils" / "pipelineFreshness.js").read_text(encoding="utf-8")
    body = util[util.index("export function railIsResyncing") :]
    missing = [
        signal
        for signal in _RAW_RAIL_SIGNALS
        if signal.removeprefix("pipeline")[0].lower() + signal.removeprefix("pipeline")[1:]
        not in body
    ]
    assert not missing, (
        f"railIsResyncing no longer consults {missing}. Every consumer now "
        "agrees on an answer that ignores a real staleness signal."
    )
