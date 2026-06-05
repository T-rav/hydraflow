---
id: "01KTB3B549EZ17X6Q0VPVT2TKQ"
name: "AgentSkill"
kind: "entity"
bounded_context: "builder"
code_anchor: "src/skill_registry.py:AgentSkill"
aliases: ["post-implementation skill", "quality gate skill", "pipeline skill check"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6KA"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B4"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-05T05:15:54.377318+00:00"
updated_at: "2026-06-05T05:15:54.377321+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-06-05T05:15:54.377250+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 2
---

## Definition

A declarative, immutable descriptor for a post-implementation quality check that runs as a subprocess after AgentRunner finishes a task. Each AgentSkill carries a unique name, a blocking flag (blocking skills halt the pipeline on failure; non-blocking skills emit warnings), a config_key pointing to a HydraFlowConfig field that can zero-out the skill's attempt budget to disable it, a prompt_builder that constructs the check input from the diff and issue context, and a result_parser that extracts a pass/fail verdict plus structured findings from the check's transcript. CorpusLearningLoop additionally references AgentSkill result_parsers directly to gate adversarial corpus cases during self-validation.

## Invariants

- A blocking AgentSkill whose result_parser returns passed=False stops the pipeline and triggers a retry cycle
- Setting the referenced HydraFlowConfig field to 0 disables the skill entirely for all runs
- name is the stable identity used to reference a skill across AgentRunner, CorpusLearningLoop, and the adversarial corpus
