# Plan Review — Adversarial Panel

Run an adversarial panel of three senior reviewers over a **plan, spec, or design** *before* it is implemented, then pass the corrections back so the plan is revised first. This is a read-only review — it does not modify the plan; it produces the corrections to fold in.

Use this at the gate between "plan written" (`superpowers:writing-plans` / a spec / a design issue) and "implement." It is the plan-stage complement to the code-stage advisor pattern (ADR-0059): multiple independent perspectives, before any code exists, when a design flaw is cheapest to fix.

## When to Use

- Before implementing a substantial feature (a new loop, a new runner, a spec → multi-task build)
- After a spec or phase-plan is written but before the first task is dispatched
- Whenever a design touches a load-bearing invariant (crash-safety, an Accepted ADR, factory-wide behaviour) — the higher the blast radius, the more a panel earns its keep

Skip it for mechanical or single-file changes; the overhead isn't worth it there.

## Instructions

1. **Assemble the plan under review into one brief file.** The panel must review the *real artifact*, not a paraphrase. Gather into a single scratchpad file:
   - the spec/plan/design doc itself (or the GitHub issue body + comments if that's the plan-of-record),
   - the ADR(s) it implements or touches,
   - any relevant already-landed scaffolding (so reviewers can check the plan matches what exists).

   ```bash
   {
     echo "# PLAN UNDER REVIEW — <title>"
     cat docs/superpowers/specs/<the-spec>.md    # or: gh issue view <N> --json title,body,comments --jq ...
     echo "## ADRs it touches"; sed -n '1,80p' docs/adr/<relevant>.md
   } > "$SCRATCH/plan-brief.md"
   ```

2. **Run the panel as a Workflow.** Three reviewers in parallel on a mid-tier model (Sonnet — plan critique is judgment-dense but not the hardest reasoning, and three of them should be cheap), then a synthesis pass on the main model (it holds the plan context and must adjudicate conflicts). The reviewers are **adversarial**: each is told to find what's *wrong*, not to bless it. The three lenses are deliberately non-overlapping — diversity is the whole point.

   - **Principal Engineer** — is the abstraction right, and will it actually work? Correctness, the load-bearing invariant, is there a simpler design, does the mechanism buy what it claims.
   - **VP Engineering** — should we build this, now, this way? Blast radius, sequencing, smallest de-risking increment, reversibility, opportunity cost, what existing behaviour it puts at risk.
   - **Staff SRE / Reliability** — how does it fail unattended at 3am? Crash/resume, observability, rollback, preemption, backpressure, the on-call signal when it wedges.

   Give every reviewer the project's real constraints as the attention lens (for HydraFlow: labels-as-truth / ADR-0002, lights-off operation, the six-phase pipeline, worker-per-phase concurrency). Have each return **structured findings** — `{concern, severity: blocking|major|minor, rationale, fix}` plus a one-line `overall_verdict` and `biggest_risk`. Barrier on all three (synthesis needs the full set), then synthesize.

   The panel script lives at `scripts/workflows/adversarial-plan-review.js` in this repo if present; otherwise author it inline following the shape above. Pass the brief path via `args.briefPath`.

3. **Verify the load-bearing claims in source before trusting them.** A reviewer's most valuable finding is also its most dangerous if hallucinated. In the synthesis prompt, require the synthesizer to **check the crux claims against the actual code/ADRs on `origin/staging`** (does the cited ADR really say that? is the primitive it names really non-atomic?) and to mark each as verified or unverified. Spot-check the single most important finding yourself before passing it on.

4. **Produce the synthesis** for the plan's author to act on. It must contain:
   - **Verdict** — ship-with-corrections / rework-before-implementing / do-not-build. Weigh the three; don't average.
   - **Blocking corrections** — merged across reviewers, with duplicates noted (2+ reviewers independently hitting the same thing is the strongest signal). Each in imperative form: the exact change to make.
   - **Cross-reviewer conflicts** — where fixes pull in opposite directions, and the adjudication.
   - **Major (non-blocking) improvements.**
   - **The one thing** — if the author fixes only one item, which and why.

5. **Pass it along.** Post the synthesis as a comment on the plan's issue/PR (or write it beside the spec), framed as an adversarial-panel review with the source-verification note, so the plan is revised **before** implementation begins. Do not start implementing until the blocking corrections are resolved.

## Notes

- **This gates, it doesn't rubber-stamp.** If the panel returns "rework-before-implementing," the plan changes first. A panel whose output nobody acts on is wasted tokens.
- **Cost:** ~3 Sonnet reviewers + 1 synthesis. Scale the panel to the stakes — three lenses for a normal feature; add a red-team/security lens for anything handling untrusted input or credentials.
- **Personas are swappable.** Principal / VP / SRE is the default. For a data-migration plan, swap SRE for a "data-integrity / irreversibility" lens; for a user-facing feature, add a product-skeptic lens. The value is in non-overlapping, adversarial coverage — not these exact three titles.
