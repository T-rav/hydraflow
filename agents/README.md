# Agents

Durable persona definitions for HydraFlow — repo-owned, like `docs/`. (`.claude/agents/` holds harness-managed `hf.*` assets; project personas never live there.) Adopted 2026-07-31 from the harvestd reference implementation (see `agents/console/decisions/arch/0001-console-charter.md`; advances #10949).

**Two layers, deliberately separate:** persona files define *who judges and in what format*; [console/](console/README.md) defines *how they are convened, measured, and kept honest* (chambers, evidence shape, vote-counting honesty, survival-rate calibration, decision records).

**Relationship to existing machinery — no duplication:** the judge fleet scores outputs; caretaker loops detect drift; Emulated Travis handles HITL escalation. Personas *adjudicate* — verdicts on artifacts before they become load-bearing. Different layer, different authority (proposal-only, always).

## Roster

| Persona | File | Convene for |
|---|---|---|
| Product manager | [product-manager.md](product-manager.md) | Backlog/epic/roadmap reviews: outcome traceability, right-sizing, stillness alignment, priority correctness |
| VP-Eng (grumpy) | [vp-eng.md](vp-eng.md) | Claims and headline metrics: converse errors, claimed-vs-demonstrated, green-because-it-never-ran |
| Senior Principal | [senior-principal.md](senior-principal.md) | Definitions, invariants, seams, boundary arithmetic: the minimal fix that makes a structure hold |

Deferred seats (ARCH-0002, by the unheld-duties rule): **ops/SRE** — the caretaker-loop fleet and operators console hold runtime duties; **security** — the factory-autonomy policy, gates, and break-glass audit chain hold the authority surface today. A seat charters only when a duty exists that no machinery or sitting contract holds.

## Operating model

Personas are convened manually (any runtime: read the file, embody it fully, verdict formats binding) and are deliberately not auto-registered into any harness. Trajectory: graduation into scheduled/event-driven runs emitting only intake artifacts (`hydraflow-find` issues, verdicts) — proposal-only by construction, same gates as all work.
