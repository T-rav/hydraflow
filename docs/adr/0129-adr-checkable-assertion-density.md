# ADR-0129: Checkable-assertion density as an ADR setpoint-erosion series

- **Status:** Proposed
- **Date:** 2026-08-05
- **Related:** epic #10914 (setpoint erosion sensor — ADR quality instrument, #10829); the sibling series #10916 (REAL/WEAK/MISSING distribution) and the framework child #10915 (shared Shewhart baseline framework — human-required, not built); `adr_conformance.classify_adr_enforcement` + the `adr-enforcement.md` generator (the enforcement *quality* lens this density series is orthogonal to); [ADR-0123](0123-bidirectional-enforcement.md) (the `**Enforced by:**` / `**Binds:**` frontmatter this parses); `judge_independence.shewhart_c_chart_ucl` (the control-limit helper reused here, one home for the c-chart assumption)
- **Enforcement:** enforced
- **Enforced by:** `pytest:tests/test_adr_assertion_density.py`
- **Binds:** factory
- **Addresses:** #10917 (checkable-assertion density per ADR — the second setpoint-erosion series)

> **This is a Proposed ADR — a design ruling for decision, not an accepted commitment.** It records the metric's definition and, deliberately, what is *real today* (the per-PR snapshot surface) versus *deferred* to the epic's framework child (the monthly time-series + shared Shewhart baseline, #10915). Accept, amend, or reject.

## Context

The setpoint-erosion epic (#10914) wants ADR quality tracked as a control signal. The obvious axis — does an ADR *declare* enforcement (`**Enforced by:**` present) — is **saturated**: 44/45 (now 80/80) Accepted ADRs declare it, so it cannot move and is useless as an erosion setpoint. A saturated metric is not a setpoint.

The actionable axis is **how executable** the declared enforcement is. An ADR enforced by `pytest:tests/test_x.py` carries a higher *checkable-assertion density* than one enforced only by `prose`. A decline in that density across the corpus — especially if concentrated in a subset of ADRs, e.g. agent-authored ones that reach for prose enforcement because it is cheaper to write — is an erosion signal.

This is **orthogonal** to the existing enforcement-*quality* lens (`adr_conformance.classify_adr_enforcement` → REAL/WEAK/MISSING, rendered by `adr-enforcement.md`). That lens *resolves* each check against the tree to ask "is this cited test actually a real, asserting check?" — it moves when a test's body changes. This series asks a cheaper, structural question — "what *kind* of check is cited, and what share are executable?" — from the ADR frontmatter alone, so it is deterministic and never drifts on a test-body edit.

## Decision

Add a pure engine `src/adr_assertion_density.py` and a deterministic arch surface `docs/arch/generated/adr-assertion-density.md`:

- **Density = executable checks / all cited checks**, per ADR, in `[0, 1]`. `pytest`/`make`/`script` are executable assertions; `prose` is not. An ADR citing no checks reads as `0.0` density (an unenforced decision is zero, not undefined).
- **Two population measures, reported together** (never one alone): the **mean per-ADR density** (each ADR counts once — a verbose ADR cannot dominate) and the **executable fraction** (check-weighted — executable checks / all checks). A corpus that adds one all-prose ADR is distinguishable from one that dilutes an executable ADR only if both are shown.
- **A Shewhart c-chart UCL on the per-ADR prose count** (reusing `judge_independence.shewhart_c_chart_ucl`) flags ADRs where non-executable enforcement is anomalously concentrated — the erosion hot-spots to look at first.

The surface is refreshed on every `make arch-regen` (like the sibling arch reports), so it stays fresh per-PR without a loop.

## Consequences

- The epic gains its second, *unsaturated* erosion series, orthogonal to the REAL/WEAK/MISSING quality lens.
- Because it reads frontmatter only, it is cheap and drift-free — but it therefore measures the *form* of enforcement (executable vs prose), not whether an executable check actually asserts anything (that is the sibling lens's job). The two are complementary and must both be read.
- **Deferred to the framework child (#10915, human-required):** a true monthly *time-series* (this ADR ships the per-PR snapshot; longitudinal trend needs the shared baseline framework) and the epic-wide Shewhart baselining convention. Until then the c-chart UCL here is an indicative within-snapshot limit, not a historical baseline.
