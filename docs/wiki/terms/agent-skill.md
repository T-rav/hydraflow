---
id: "01KYME2A932ASJZ2FDFXPYR5XC"
name: "AgentSkill"
kind: "value_object"
bounded_context: "builder"
code_anchor: "src/skill_registry.py:AgentSkill"
aliases: ["skill", "post-implementation check", "quality gate"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6KA"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B4"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-28T13:19:16.259502+00:00"
updated_at: "2026-07-28T13:19:16.259505+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-28T13:19:16.259456+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 2
---

## Definition

AgentSkill is a declarative specification of a post-implementation quality check that runs against the branch diff after the implementation agent finishes. Each skill carries a name, a one-line purpose injected into the agent prompt, a prompt builder, a result parser that extracts structured pass/fail findings from the agent transcript, and a blocking flag that determines whether a failed check stops the pipeline. Built-in skills — diff-sanity, scope-check, plan-compliance, test-adequacy, discover-completeness, and shape-coherence — are registered in execution order and orchestrated by AgentRunner._run_skill(). The test-adequacy skill additionally carries a VerifierSpec for an independent second-opinion pass.

## Invariants

- Skills execute in registration order (BUILTIN_SKILLS list); ordering is significant.
- A blocking skill failure stops the pipeline; a non-blocking failure is logged as a warning.
- Setting the skill's config_key field on HydraFlowConfig to 0 disables that skill.
