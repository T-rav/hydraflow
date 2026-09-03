---
id: "01M1JPJCBK4BYKVD3SMDZBWT7H"
name: "AgentSkill"
kind: "policy"
bounded_context: "builder"
code_anchor: "src/skill_registry.py:AgentSkill"
aliases: ["post-implementation check", "quality gate skill"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6KA"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B4"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-09-03T03:56:27.891910+00:00"
updated_at: "2026-09-03T03:56:27.891912+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-09-03T03:56:27.891798+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 2
---

## Definition

A declarative post-implementation check that runs against the branch diff after the implementation agent finishes (e.g. diff-sanity, scope-check, plan-compliance, test-adequacy). Each AgentSkill names a workflow checkpoint with a purpose string surfaced to the agent's prompt, a config_key controlling max retry attempts, a blocking flag that determines whether a failed check stops the pipeline or only warns, prompt/result-parser callables, and optional VerifierSpec (independent second-opinion pass) and repair (in-run fix-forward) hooks. BUILTIN_SKILLS is the registry of these checks, orchestrated by AgentRunner._run_skill() in execution order.

## Invariants

- blocking=True skills stop the pipeline on failure; blocking=False skills log a warning and continue
- config_key can be set to 0 to disable the skill entirely
- the optional verifier (VerifierSpec) is an independent second-opinion pass that only runs when trigger(finder_transcript) is true, and its model must stay independent of the finder's review_model
