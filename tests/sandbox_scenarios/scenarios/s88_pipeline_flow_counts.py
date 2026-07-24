"""s88 — Pipeline Flow region shows per-stage and total issue/PR counts (#10488).

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

from mockworld.seed import MockWorldSeed

NAME = "s88_pipeline_flow_counts"
DESCRIPTION = (
    "The Work Stream board's Pipeline Flow region shows per-stage and "
    "pipeline-wide issue/PR count badges, proving pipeline stage membership "
    "reaches the browser via /api/pipeline and renders through countPipeline."
)

STAGE_KEYS = ["triage", "plan", "implement", "review", "hitl", "merged"]

_STAGE_COUNT_PATTERN = re.compile(r"^\d+ · \d+ PR$")
_TOTAL_COUNT_PATTERN = re.compile(r"^\d+ issues · \d+ PRs$")


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

    for stage_key in STAGE_KEYS:
        badge = page.locator(f"[data-testid='flow-count-{stage_key}']")
        await badge.wait_for(timeout=15_000)
        text = await badge.inner_text()
        assert _STAGE_COUNT_PATTERN.match(text), (
            f"stage '{stage_key}' count badge should match '<n> · <n> PR', got {text!r}"
        )

    total = page.locator("[data-testid='flow-total']")
    await total.wait_for(timeout=15_000)
    total_text = await total.inner_text()
    assert _TOTAL_COUNT_PATTERN.match(total_text), (
        f"pipeline total badge should match '<n> issues · <n> PRs', got {total_text!r}"
    )
