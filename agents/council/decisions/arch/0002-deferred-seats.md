# ARCH-0002: Ops, SRE, and security seats deferred (unheld-duties rule)

**Date:** 2026-07-31 · **Seats:** operator + session clerk · **Verdict:** ACCEPT (defer)
**Dissent:** none
**Enforcement:** decision-of-record
**Evidence:** caretaker-loop fleet + operators console (runtime duties held) · `factory_autonomy/policy.yaml` + gates + break-glass audit chain (authority surface held) · harvestd ARCH-0004/0005 (the rule applied in both directions, same day)

A seat charters only for a duty no machinery or sitting contract holds. HydraFlow's runtime is watched by its own loop fleet and operated from its console — an ops/SRE persona today would be a hat on the machinery. Its authority surface is governed by policy, gates, and the approval-record chain — a security seat waits for a duty those don't hold (candidate: the identity/attribution gap, when that work opens). Revisit on evidence, not appetite.
