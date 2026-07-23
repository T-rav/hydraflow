# ADR-0107: Collapse Discover + Shape into Plan — Triage → Plan Directly

**Status:** Accepted
**Accepted on:** 2026-07-21 — operator-approved full removal of the standalone product track (issue #9773).
**Date:** 2026-07-21
**Enforcement:** decision-of-record
**Supersedes:** ADR-0031 (Product Track Architecture — Discover and Shape Phases)
**Amends:** ADR-0002 (GitHub Labels as the Pipeline State Machine); ADR-0064 (Earlier-Adversarial Pipeline — removes the Discover/Shape adversarial stages)

## Context

ADR-0031 introduced a *product track* — two standalone pipeline phases,
**Discover** and **Shape** — that branch from triage and rejoin at plan. Each
is a first-class citizen of the pipeline: a lifecycle label
(`hydraflow-discover`, `hydraflow-shape`), an `IssueStoreStage` queue, a
supervised async loop (`_discover_loop`, `_shape_loop`), a slice of the label
state machine, dashboard track rendering, and its own config knobs
(`max_discover_attempts`, `max_discover_expansions`, `max_shape_attempts`,
`max_shape_turns`).

Triage already forks: `triage_phase.py:_triage_single` routes an issue to
Discover when `needs_discovery` is set **or** `clarity_score < clarity_threshold`
(default 7), and routes everything else straight to Plan. High-clarity issues
therefore *already* skip the product track. The standalone Discover/Shape
phases only ever run for the low-clarity / needs-discovery minority.

Operating experience (issue #9773, filed at operator request) is that the
standalone phases carry disproportionate cost for that minority:

- **Two extra labels and two extra loops** poll GitHub every cycle for work
  that is usually absent, adding latency and label-state-machine surface.
- **The routing authority sits at triage time**, where the only signal is a
  coarse `clarity_score`. The planner — which has far richer context (route-back
  history, escalation labels, codebase exploration, epic lineage) — is a
  better place to decide whether an issue needs discovery research before a
  plan can be written.
- **Shape is a human-interactive conversation loop.** Modelling it as a
  standalone always-on pipeline stage means every low-clarity issue blocks on
  human responsiveness *before* planning, even when the planner could have
  proceeded and surfaced a specific question instead.

The planner already contains the seams this decision needs:
`plan_phase.py:_should_research` gates a research pre-pass (escalated or cycled
issues) via an injected research runner, and `plan_phase.py:_is_product_track_issue`
detects product-track provenance. The discover/shape logic is likewise already
factored into callable engines (`discover_runner.py:DiscoverRunner`,
`shape_runner.py:ShapeRunner`) rather than being welded to their loops — the
planner invokes these runners directly.

## Decision

**Retire Discover and Shape as standalone pipeline phases.** Triage routes
`hydraflow-ready` issues directly to Plan in all cases. Discovery research and
direction shaping become **on-demand helpers the planner invokes behind its own
decision gate**, reusing the existing engines — not pipeline stages, labels, or
loops.

The pipeline topology becomes:

```
Triage ─→ Plan ─→ Implement ─→ Review ─→ (HITL) ─→ Merged
             │
             └─(planner decision gate)─→ [discover research] / [shape question]
```

### Routing (supersedes ADR-0031's fork)

`triage_phase.py:_triage_single` no longer emits `hydraflow-discover`. A ready
issue transitions to `hydraflow-plan` regardless of `clarity_score` or
`needs_discovery`. The `clarity_score` / `needs_discovery` signals are retained
on `models.py:TriageResult` and handed to the planner as *hints* for its gate,
rather than as a triage-time routing verdict. Not-ready issues continue to park
(`hydraflow-parked`) pending author input — unchanged.

### Planner decision gate

The planner gains a gate (extending the existing `_should_research` seam) that,
per issue, decides whether to invoke:

- **Discovery research** (`DiscoverRunner`-backed, read-only, non-interactive) —
  when the issue is vague/broad (low clarity hint, escalation label, or a
  route-back from a later stage). Produces the same structured research brief
  ADR-0031 defined, consumed in-process as `research_context` for the plan run
  instead of being posted as a stage handoff. This is a synchronous helper call,
  not a stage transition.
- **Direction shaping** — when discovery surfaces genuinely divergent product
  directions that need a human choice. Because shaping is human-interactive, the
  planner surfaces the options as a question and yields to the **existing HITL /
  human-steering channel** (ADR-0103) rather than spinning a dedicated Shape
  loop. The multi-turn conversation machinery in `shape_phase.py` is reused as
  the helper that formats options and interprets the human's reply.

Decision inputs the gate uses (all already available at plan time): the triage
`clarity_score` / `needs_discovery` hints, `research_escalation_labels`,
`StateTracker.get_route_back_count`, and epic-child provenance. The gate is
conservative by default — the common, well-specified issue plans directly with
no helper invocation, exactly as a high-clarity issue does today.

### Labels (amends ADR-0002)

`hydraflow-discover` and `hydraflow-shape` are removed from the label state
machine. No transition targets them; the `DISCOVER` / `SHAPE` `IssueStoreStage`
and `PipelineStage` members and their queues are retired. ADR-0002's dual-label
invariant (exactly one pipeline label) is unchanged — the set of pipeline labels
simply shrinks back toward the ADR-0001 five-stage core plus the junction
labels. This ADR is the amending record for that shrink.

### Loops (per ADR-0001)

`_discover_loop` and `_shape_loop` are removed from the orchestrator
`loop_factories`. Discover/shape work no longer has a standalone supervised
loop; it runs inside the plan loop's tick via the gate. The
`DiscoverRunner` / `ShapeRunner` engines (and their expander / completeness /
coherence helpers) survive as planner-invoked helpers; the standalone
`DiscoverPhase` / `ShapePhase` wrappers — and their loop-only council /
challenger machinery (`ExpertCouncil`, `DiscoveryCouncil`, `ShapeChallenger`,
`ShapeExpertCouncil`, `ComplexityGate`) — are removed with the loops.

### Config migration

- `max_discover_attempts`, `max_discover_expansions`, `max_shape_attempts`,
  `max_shape_turns` migrate to bound the planner-invoked helpers (same
  semantics, now read by the gate rather than the standalone loops). Their env
  overrides are preserved so existing deployments keep their tuning.
- `discover_label`, `shape_label` are retired.
- `clarity_threshold` is repurposed as the planner gate's default
  discovery-hint threshold rather than the triage routing threshold.

### Rollout (completed)

Because this change removed load-bearing pipeline stages that ~50 scenario and
unit suites asserted, it landed incrementally behind a single lever,
`collapse_discover_shape` (env `HYDRAFLOW_COLLAPSE_DISCOVER_SHAPE`), mirroring
the flag-gated rollout precedent of ADR-0042 (`HYDRAFLOW_STAGING_ENABLED`):

1. **Keystone (#10145):** the flag (default `False`) and the flag-gated
   Triage→Plan-direct routing. With the flag off, behavior was byte-for-byte the
   ADR-0031 fork, so the full existing suite stayed green.
2. **Planner gate (#10147):** wired the planner decision gate
   (`_should_discover_helper` / `_should_shape_helper`) to invoke the
   `DiscoverRunner` / `ShapeRunner` engines behind the flag.
3. **Full removal (#9773):** made the collapsed behavior **unconditional** and
   **removed the flag entirely**, along with the standalone `_discover_loop` /
   `_shape_loop`, the `hydraflow-discover` / `hydraflow-shape` labels, the
   `IssueStoreStage` / `PipelineStage` `DISCOVER` / `SHAPE` members and their
   queues, the dashboard track rendering, the `DiscoverPhase` / `ShapePhase`
   wrappers and their loop-only council/challenger/gate modules, and migrated
   the product-track scenarios/tests.

The flag was a migration lever, not a permanent operating mode — it has been
removed now that the collapsed topology is the only path.

## Consequences

**Positive:**

- One entry fork fewer: Triage has a single forward edge (Plan) plus park/close
  terminals. Two labels and two supervised loops leave the hot path.
- Discovery/shaping authority moves to the planner, which has strictly more
  context than triage's `clarity_score`, so the decision to spend research
  budget is better-informed.
- The common, well-specified issue is unaffected — it already skipped the
  product track and still does.
- Human interaction for shaping reuses the one continuous human-steering channel
  (ADR-0103) instead of a bespoke always-on Shape loop.

**Negative / Trade-offs:**

- The planner tick gets heavier and less uniform: a plan run may now fan out to
  a research sub-pass (and, rarely, a human shaping question) inline, so plan
  latency has higher variance than the old fixed-stage model.
- The discover/shape engines remain in the tree as planner helpers, so the code
  is not deleted outright — the *pipeline surface* shrinks, not the engine LOC.
- The flag-gated rollout means two routing code paths coexist until the default
  flips; the flag must be removed (not left indefinitely) once step 2 lands.
- ADR-0031's "product track" vocabulary (`PRODUCT_TRACK_KEYS`, the three-track UI
  model, the `DECOMPOSITION REQUIRED` handoff marker) is deprecated; downstream
  product-track detection collapses into ordinary planner decomposition.

## Related

- ADR-0031 (Product Track Architecture — Discover and Shape Phases) — **superseded
  by this ADR**; its fork-at-triage routing rule and standalone-phase model are
  retired.
- ADR-0002 (GitHub Labels as the Pipeline State Machine) — **amended**: the
  `hydraflow-discover` / `hydraflow-shape` labels are removed from the state
  machine.
- ADR-0001 (Five Concurrent Async Loops) — the five-stage core this ADR returns
  the pipeline toward by retiring the two product-track loops.
- ADR-0103 (Continuous Human Steering Channel) — the channel that absorbs
  human-interactive shaping instead of a dedicated Shape loop.
- ADR-0042 (Two-Tier Branch Release Promotion) — precedent for landing a
  topology change behind a boolean rollout flag.
- `src/triage_phase.py:_triage_single` — routing; the Discover branch is removed, so a ready
  issue always transitions to `hydraflow-plan`.
- `src/plan_phase.py:_should_research` — existing gate the planner discovery
  decision extends.
- `src/plan_phase.py:_should_discover_helper` / `_should_shape_helper` — the
  planner decision gate that invokes the discover/shape engines on demand.
- `src/plan_phase.py:_is_product_track_issue` — product-track detection that
  collapses into planner decomposition.
- `src/discover_runner.py:DiscoverRunner` — retained as the planner-invoked
  research engine (the standalone `DiscoverPhase` wrapper was removed).
- `src/shape_runner.py:ShapeRunner` — retained as the planner-invoked shaping
  engine (the standalone `ShapePhase` wrapper was removed).
- `src/models.py:TriageResult` — `clarity_score` / `needs_discovery` become
  planner hints rather than triage routing verdicts.
