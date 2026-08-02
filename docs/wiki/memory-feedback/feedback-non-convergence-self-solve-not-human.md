---
source: feedback_non_convergence_self_solve_not_human.md
name: feedback_non_convergence_self_solve_not_human
description: Non-convergence / thrash / give-up routes to MACHINE self-solve (ADR-0105 decompose-to-converge, or auto-agent diagnose), NEVER reflexively to human-required. Human is the last resort, only for genuine mission/'should-this-exist' calls. Routing convergence-solvable work to a human is HITL scatter.
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-07-27'
---

**Directive (Travis, 2026-07-27, verbatim energy):** "fuck the human-required, this is a classic convergence to self-solve issue." Said after I reflexively parked a thrashing sampled-audit issue (#10731) to `human-required` when its plan↔plan-review loop wouldn't converge.

**The rule.** When a unit can't converge (thrash, retry/give-up-window exhaustion, blocking-findings loop), the machine's move is to **change strategy, not offload to a person**:
1. retry within the window (common cause);
2. exhausted → **auto-decompose** (ADR-0105 decompose-to-converge: split the non-convergent issue into convergent children) OR **auto-agent diagnose** (resolve-or-dismiss-with-evidence);
3. **human = last resort ONLY** — reached when self-solve itself exhausts, or the finding is a genuine mission/"should this exist" call.

**Two axes, easy to conflate — this is the whole insight:**
- *Non-convergence* is a **mechanism** problem → machine self-solves (retry→decompose→diagnose). Beamlet's `ChildGaveUp → model`, not human.
- *Mission ambiguity* ("what should the system become", ADR/contract change, spend authorization) is a **judgment** problem → human apex.
The give-up window belongs to the FIRST axis. Only the second reaches a person. Routing axis-1 work to `human-required` is **HITL scatter** — an anti-pattern, not stewardship.

**How to apply.** Audit findings (sampled-audit, escape-ledger), thrashing plans, retry-exhausted builds → `hydraflow-find` / decompose / diagnose, not `human-required`. When building give-up/escalation logic, the exhaustion target is decompose/diagnose, not a human label. Emit `human-required` rarely and log it as a break.

Related: [[project_credit_diagnose_hitl_scatter_10536]] (credit-starved diagnose fabricating human-required — same anti-pattern, narrower cause) · the two-tier supervisor + give-up window work (gh#10733/#10735) · book-3 note "Factory supervision — the OTP two-tier model".
