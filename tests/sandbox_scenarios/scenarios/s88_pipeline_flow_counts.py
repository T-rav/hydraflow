"""s88 — Pipeline Flow region shows per-stage and total issue counts (#10488).

Badge text is issue-count-only since #10609 dropped the PR count from the strip
(per-stage ``N``, pipeline total ``N issues``); see #10664.

The sandbox e2e layer for the Pipeline Flow count badges. It proves the real
end-to-end wiring path only a live browser against the real Docker stack can
exercise: dashboard load → ``GET /api/pipeline`` stage membership → the React
``stageGroups`` derivation in ``StreamView`` → ``countPipeline`` → the
per-stage ``flow-count-<stageKey>`` badges and the pipeline-wide ``flow-total``
badge. A break anywhere on that chain (a missing API field, a stage-key
mismatch between ``PIPELINE_STAGES`` and the API payload, a dropped prop, a
render guard hiding the badge) leaves the operator staring at a Pipeline Flow
region with no numeric read on how much is in each stage — the exact gap this
feature closes.

Deliberately scoped to "the badges render with numeric content on board
load," not to driving specific seeded issue/PR counts through the pipeline
and asserting exact numbers. The badges read directly off
``PIPELINE_STAGES``/``stageGroups`` and render unconditionally (including the
all-zero case), so no seeded pipeline activity is needed for this layer to be
meaningful — matching the s59 queue-strategy-badge precedent, which stays
scoped to "the badge renders" for the same reason (seeding queued issues to
assert on precise counts here would reintroduce the dispatch-timing race
class that s59's docstring calls out). The exact-number-matches-seeded-state
assertions belong to the deterministic unit tiers instead:
``pipelineCounts.test.js`` (``countPipeline`` given known stage groups) and
``StreamView.test.jsx`` (badge text given known props). This Tier-2 layer's
job is only to prove the wiring is live end-to-end in the real stack.
"""

from __future__ import annotations

import re
from pathlib import Path

from mockworld.seed import MockWorldSeed

NAME = "s88_pipeline_flow_counts"
DESCRIPTION = (
    "The Work Stream board's Pipeline Flow region shows per-stage and "
    "pipeline-wide issue/PR count badges, proving pipeline stage membership "
    "reaches the browser via /api/pipeline and renders through countPipeline."
)

# The whole repo is mounted read-only at the container root, so constants.js is
# reachable from the scenario (Dockerfile.playwright / docker-compose.sandbox).
_CONSTANTS_JS = (
    Path(__file__).resolve().parents[3] / "src" / "ui" / "src" / "constants.js"
)


def _canonical_stage_keys() -> list[str]:
    """Derive the pipeline stage keys from the canonical PIPELINE_STAGES source.

    The frontend defines ``PIPELINE_STAGES`` once (``src/ui/src/constants.js``)
    and derives ``STAGE_KEYS = PIPELINE_STAGES.map(s => s.key)`` plus every
    per-stage view from it. Parsing the same array here — instead of duplicating
    the list — keeps this scenario in lockstep: a stage added, removed, or
    renamed there flows through automatically, so the scenario can never go
    stale and silently stop covering a stage (the #10601 false-green). Fails
    loud if the array can't be located rather than falling back to a guessed set.
    """
    src = _CONSTANTS_JS.read_text(encoding="utf-8")
    block = re.search(r"PIPELINE_STAGES\s*=\s*\[(.*?)\]", src, re.S)
    if not block:
        raise RuntimeError(f"could not locate PIPELINE_STAGES array in {_CONSTANTS_JS}")
    keys = re.findall(r"key:\s*'([^']+)'", block.group(1))
    if not keys:
        raise RuntimeError(f"PIPELINE_STAGES in {_CONSTANTS_JS} yielded no keys")
    return keys


STAGE_KEYS = _canonical_stage_keys()

# #10609 dropped the PR count from the Pipeline Flow strip: the per-stage badge
# now renders a bare issue count (``N``) and the pipeline total renders
# ``N issues`` — no more ``· N PR`` / ``· N PRs`` suffix. These patterns track
# that current render (pinned by the frontend's own StreamView.test.jsx: a
# flow-count badge is ``'2'``, flow-total is ``'3 issues'``). See #10664.
_STAGE_COUNT_PATTERN = re.compile(r"^\d+$")
_TOTAL_COUNT_PATTERN = re.compile(r"^\d+ issues$")


def seed() -> MockWorldSeed:
    # The board (Work Stream tab) is the default view; no pipeline activity is
    # needed — the badges read counts off PIPELINE_STAGES/stageGroups and
    # render even when every stage is empty.
    return MockWorldSeed(cycles_to_run=1)


async def assert_outcome(api, page) -> None:
    await page.goto("/")

    # The board is the default tab; the Pipeline Flow header carries the badges.
    flow = page.locator("[data-testid='pipeline-flow']")
    await flow.wait_for(timeout=15_000)

    # Derive the stage set from what the board actually rendered rather than a
    # hardcoded list: StreamView emits one flow-count-<key> badge per
    # PIPELINE_STAGES entry (its stageGroups map), so enumerating the badges
    # keeps this scenario automatically in sync when a stage is added, removed,
    # or renamed — no stale copy silently dropping coverage (#10601).
    count_badges = page.locator("[data-testid^='flow-count-']")
    await count_badges.first.wait_for(timeout=15_000)
    rendered_keys: list[str] = await count_badges.evaluate_all(
        "els => els.map(e => "
        "e.getAttribute('data-testid').substring('flow-count-'.length))"
    )
    assert rendered_keys, "Pipeline Flow rendered no per-stage flow-count badges"

    # Cross-check the rendered stage set against the canonical PIPELINE_STAGES
    # keys. A mismatch means /api/pipeline stage membership and PIPELINE_STAGES
    # have drifted apart (a dropped or renamed stage) — the exact stage-key
    # mismatch this scenario exists to catch, now surfaced as a failure instead
    # of a false-green.
    assert set(rendered_keys) == set(STAGE_KEYS), (
        f"rendered Pipeline Flow stages {sorted(rendered_keys)} drifted from the "
        f"canonical PIPELINE_STAGES keys {sorted(STAGE_KEYS)} "
        "(src/ui/src/constants.js)"
    )

    for stage_key in rendered_keys:
        badge = page.locator(f"[data-testid='flow-count-{stage_key}']")
        await badge.wait_for(timeout=15_000)
        text = await badge.inner_text()
        assert _STAGE_COUNT_PATTERN.match(text), (
            f"stage '{stage_key}' count badge should match '<n>', got {text!r}"
        )

    total = page.locator("[data-testid='flow-total']")
    await total.wait_for(timeout=15_000)
    total_text = await total.inner_text()
    assert _TOTAL_COUNT_PATTERN.match(total_text), (
        f"pipeline total badge should match '<n> issues', got {total_text!r}"
    )
