# ADR-0132: The cognitive-process constitution — the harness as a governor of thought

- **Status:** Proposed
- **Date:** 2026-08-08
- **Enforcement:** decision-of-record
- **Binds:** factory
- **Related:** [ADR-0122](0122-vocabulary-scopes-for-the-three-assurance-disciplines.md) (the three assurance disciplines — constitutional/legal, formal methods, control theory — this ADR gives the *unified statement* of); [ADR-0099](0099-orchestration-as-a-control-system.md) (orchestration as a control system — the control frame); [ADR-0044](0044-hydraflow-principles.md) (the principles audit — assumptions made executable); [ADR-0123](0123-bidirectional-enforcement.md) (`**Binds:**` — the authority frame); [ADR-0100](0100-adr-conformance-as-a-measured-contract.md) (conformance — assumptions as a measured contract); [ADR-0120](0120-stillness-control-architecture.md) (the control architecture — bounded execution, exit criteria); [ADR-0131](0131-spec-intake-gate.md) (spec-intake — one meaning-construction step already built); [ADR-0143](0143-paaa-governance-model-and-the-decision-seam.md) (PAAA — the four-layer ontology that names *what* the four constitutional mechanisms here govern: Purpose, Articles, Actors, Artifacts); #11035 (the cognitive-process-manager epic) and its children #11036–#11041 (the loop this constitution governs); #10833 (the authority-kernel model-check — the formal-methods leg of the limit frame; **proposed, unbuilt**); #10849 (the bidirectional-enforcement finding — the forcing receipt below)
- **Addresses:** #11040 (name the harness as a governor of thought; make its assumptions / authority / evidence / correction explicit as one constitution)

**Precedent:** Constitutional government + separation of powers (the authority to *act* is separated from the authority to *authorize*, and both are bounded by a written charter and a correction mechanism); cybernetic governance (Beer, *Brain of the Firm*, 1972 — a viable system regulates itself through recursive control loops, not through a smarter central controller).
**Divergence:** a constitution governs *people*, whose capability is assumed and whose compliance is voluntary; here the governed actor is a **model whose capability is a moving, jagged, partly-unknowable bound** and whose "compliance" is whatever the harness mechanically permits — so the charter must (1) carry a *capability-limit* frame that a human constitution never needs (you cannot legislate a capability the model does not have, nor assume one it does), and (2) make every clause a *mechanism*, not an appeal to good faith (receipt: ADR-0123 / #10849 — the bidirectional-enforcement finding that the factory enforced its principles on what it *builds* but not on *itself*, made concrete by the #10844 credit-exhaustion two-day blind spot where an ungoverned governor ran unchecked; forcing condition: once the harness shapes what is remembered, retrieved, questioned, and acted on for every user inside it, "assume the reviewer acts in good faith" is not available — the harness *is* the reviewer).

> **This is a Proposed ADR — a design ruling for decision, not an accepted commitment.** It names a governance frame the factory already half-embodies, and states one load-bearing constraint (propose vs commit) that the meaning-construction children (#11036–#11041) all depend on. It adds no code; it makes an implicit constitution explicit so the children can be judged against it. Accept, amend, or reject the framing.

## Context

HydraFlow is a harness around a model. The model supplies cognitive capability; the harness decides what that capability is allowed to do — what is remembered, retrieved, questioned, and acted upon. The cognitive-process-manager thesis (#11035) pushes the harness further: from *executing* well-formed intent toward *progressively constructing* meaning and *choosing the cognitive mode* a problem needs (#11041). The moment the harness does that, it is no longer merely assisting thought. **It is structuring thought.** A system that structures thought can structure it wrongly — so its assumptions, authority boundaries, evidence requirements, and correction mechanisms stop being convenience and become constitutional.

HydraFlow already *has* those four mechanisms, but scattered and unnamed as a governance of cognition. ADR-0122 already scoped the *vocabulary* of the three disciplines this sits inside — constitutional/legal, formal methods, control theory — but stopped at deconflicting the words. This ADR states the sentence they compose.

## Decision

Name the harness explicitly as a **governed cognitive-process manager**, and unify its four constitutional mechanisms under one frame.

### The clean thesis

> **The model provides cognitive capability. The harness determines how that capability participates in a governed feedback loop.**

Capability is the worker; the harness is the constitution *and* the control loop around it. Everything below is that sentence expanded.

### The three-frame stack (the governance spine — aligned with, not identical to, ADR-0122's three disciplines)

ADR-0122 already scoped the vocabulary of HydraFlow's three assurance disciplines — constitutional/legal, formal methods, control theory. The vault's governance spine is **Limit (Gödel) / constitution / control**. The alignment is exact on two frames (constitution ↔ constitutional/legal; control ↔ control theory) and **only partial on the third**: the Limit frame is broader than ADR-0122's *formal methods*. Formal methods proves the *harness's own kernel* (#10833) and is deliberately silent on model capability; the Limit frame also covers *model capability*, which is not provable and is measured empirically. So the two legs of the Limit frame — proof and measurement — must be kept distinct, not collapsed.

| Frame | Question it answers | Where it lives today |
|---|---|---|
| **Limit** (Gödel) | *What can this capability actually do or prove?* You cannot legislate a capability the model lacks, nor assume one it has — and a system cannot fully certify itself. | Two distinct legs: **(a) proof** — the harness's own gate/verdict logic, model-checkable (formal methods, #10833 — **proposed, unbuilt**); **(b) measurement** — the model's capability, *not* provable, measured empirically by the calibration instruments (judge calibration #10836, finder calibration #10821 — **live**). Today the frame is embodied by (b); (a) is aspirational. |
| **Constitution** | *What is permitted — remembered, retrieved, questioned, acted on — and by whose authority?* | assumptions of record (the ADR corpus, ADR-0100); authority boundaries (`**Binds:**`, ADR-0123) |
| **Control** | *How does the loop correct itself when reality disagrees?* | the gauntlet gates (evidence); the ConvergenceLedger + escape ledger (correction); the stillness control architecture (ADR-0120, ADR-0099) |

Together they compose a **charter for a capability of uncertain bound, enforced by a control loop** — a related lens over the three disciplines, not a claim that they are one object. Reading any one frame alone is the failure ADR-0122 warns about (an ARL-designed chart with a legal-register alarm guarantees neither).

### The four constitutional mechanisms, unified

| Constitutional element | Lives in |
|---|---|
| **Assumptions of record** | the ADR corpus — an ADR *is* a recorded assumption (ADR-0100 conformance; ADR-0044 principles make them executable) |
| **Authority boundaries** | `**Binds:** work \| factory \| both` (ADR-0123) — what the factory may change about *itself* |
| **Evidence requirements** | the gauntlet gates + the three assurance disciplines (ADR-0122) |
| **Correction mechanisms** | ConvergenceLedger, escape ledger (#10367), judge calibration (#10836), spec-intake (#10830/ADR-0131) |

### The load-bearing constraint: propose, do not commit

The single clause the whole cognitive-process epic depends on:

> **The harness may *propose* constructed intent, competing interpretations, experiments, and cognitive modes. The authority to *commit* stays governed.**

- Fragment intake (#11036) proposes a constructed intent; it does not enact one — the constructed intent is a proposal a human confirms or a recorded assumption backs.
- The interpretation fork (#11037) surfaces readings; it does not silently pick one.
- Minimal-distinction HITL (#11038) asks the *single distinguishing question*; it does not answer on the human's behalf — it is the mechanism that routes the commit *to* a human, so it is the clearest instance of this clause, not an exception to it.
- Experiment conversion (#11039) may *test*; committing on the evidence is a governed decision.
- Adaptive mode-selection (#11041) may switch how the factory reasons; every individual move stays bounded by authority, evidence, cost, time, and verification.

This is the line between *structuring* thought and *replacing* it. A harness that commits intent it was never given has stopped being a governor and become an author — the exact failure a constitution exists to prevent. **The harness never invents the intent; it constructs the scaffold and routes the commit back to a human or a recorded assumption.**

### The triad and the bounded-execution rule

> Human: "What kind of help do I need right now?" · Factory: "What kind of cognition does this problem need right now?" · Harness: "What cognition and action are permitted, grounded, observable, verifiable?"

The **problem** may be unbounded; the **execution** may not. Unbounded problem → bounded cognitive loops → bounded actions → evidence → model update → mode transition → resolution or escalation. Every dialectical loop carries **mandatory exit criteria** (contradiction resolved · confidence threshold · evidence stops changing the model · cost budget · reversible-enough to act · human-escalation) — the same discipline the stillness program (ADR-0120, #10819) and the give-up window (#10735) already enforce, because a dialectical loop with no exit is a hunting loop.

### Instrument the instruments — the obligation must extend to the harness itself

The correction mechanisms must also measure the harness's *own* meaning-construction and mode-selection — or the governor is un-governed. Today they do not (the mechanisms are #11041's, unbuilt); this is a stated obligation the children inherit, not a present capability. #11041's per-mode failure-mode detectors and exit criteria, and the calibration instruments turned on the harness's own proposals, are constitutional obligations, not features. A governor that does not instrument itself is asserting its own good faith — the one thing this constitution says is unavailable.

## Consequences

- **It adds no code; it makes an implicit constitution explicit.** The four mechanisms already exist; naming them as one frame lets the cognitive-process children (#11036–#11041) be judged against a stated charter rather than case-by-case taste. Contradicting this frame later requires a superseding ADR, not a quiet code change.
- **The leverage moves up; it does not democratize.** The harness that encodes the loop is designed by a loop-closer, and whoever writes the constitution the harness runs decides — for every user inside it — what gets remembered, retrieved, questioned, and acted on. That is why this is a constitutional question, not a UX one, and why the propose-vs-commit clause is non-negotiable: it is the only thing keeping "one author's judgment, encoded" from becoming "one author's judgment, imposed."
- **Honest scope.** This governs the factory HydraFlow *is* today (bounded tasks: issue → PR, fixed-phase convergence) and the adaptive-mode factory it is *not yet* (#11041, largely unbuilt, "can-a-company?" territory). The constitution is written now precisely so the unbuilt part is governed before it is built — the reverse order is how a governor becomes an author by accident.
- **The limit frame is load-bearing and easy to drop.** A constitution that assumes unbounded capability governs a fiction; one that assumes too little forbids what the model can do. The `Limit` frame keeps the charter honest about the capability it governs — it is the frame a human constitution never needs and this one cannot omit. Today it is carried by the *measurement* leg (live calibration, #10836/#10821); the *proof* leg (the kernel model-check, #10833) is unbuilt, so the frame is real but half-embodied — which is itself a finding, not a claim of completeness.

## What an implementer does differently once this is Accepted

The concrete payload is the **propose-vs-commit** clause. Anyone building #11036–#11041 has a stated test to build against and be judged by: *does this mechanism enact a commit the harness constructed, or route it to a human / a recorded assumption?* A fragment-intake PR that auto-files a constructed issue with no human confirmation and no backing ADR **violates the charter**; the same PR that files it as a *proposal* an operator confirms **satisfies** it. Before this ADR, that call was case-by-case taste; after it, it is adjudicable against one written clause. If nothing else here survives review, that clause is the decision worth recording.

## Alternatives considered

- **Leave it as essay (Book-3), not a decision record.** ADR-0122 deliberately *stopped* at deconflicting the vocabulary; the case that stopping there was correct — that "the sentence they compose" is thesis material, and a constitution for a capability the shipped factory does not yet exercise entrenches an untested frame — is real. Rejected for one reason: the meaning-construction children (#11036–#11041) are being *designed now*, and they need a charter to be judged against *before* they are built, not after. Writing the governor's limits after it exercises power is how a governor becomes an author by accident.
- **Rule only propose-vs-commit; cite the vault essay for the framing.** A leaner ADR — the propose-vs-commit clause as the sole decision, the three-frame stack demoted to a one-line pointer — would be harder to attack and carries the entire adjudication payload. This is a legitimate *amend*, offered for the owner: accept the full framing, or accept only the clause and keep the rest as narrative. The clause is the load-bearing part either way.
