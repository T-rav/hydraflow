// Reusable adversarial plan-review panel — the engine behind hf.plan-review.
//
// Runs three non-overlapping senior reviewers (Principal Engineer, VP Eng,
// Staff SRE) over a plan in parallel on Sonnet, each told to FIND WHAT IS WRONG
// rather than bless it, then a synthesis pass on the main model that verifies
// the crux claims against source before ranking the corrections.
//
// Input: args.briefPath — a single file containing the plan/spec/issue under
// review PLUS the ADRs and already-landed scaffolding it touches, so reviewers
// can check the plan against what actually exists. Optionally args.context — a
// short string of project-specific invariants to use as the attention lens
// (defaults to HydraFlow's).
//
// Returns { reviews: [...structured findings per lens], synthesis: "..." }.
export const meta = {
  name: 'adversarial-plan-review',
  description: 'Three adversarial senior reviewers (Principal, VP Eng, Staff SRE) critique a plan on Sonnet, then a synthesis pass (main model) verifies crux claims in source and ranks the corrections to fold in before implementation',
  phases: [
    { title: 'Review', detail: 'Principal / VP Eng / Staff SRE attack the plan in parallel (Sonnet)' },
    { title: 'Synthesize', detail: 'verify crux claims in source, merge, rank, surface conflicts, go/no-go' },
  ],
}

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    lens: { type: 'string', description: 'which persona' },
    overall_verdict: {
      type: 'string',
      enum: ['ship-the-plan', 'ship-with-corrections', 'rework-before-implementing', 'do-not-build'],
    },
    biggest_risk: { type: 'string', description: 'the single most important thing this plan gets wrong or omits, one sentence' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          concern: { type: 'string', description: 'the specific defect/gap/risk in the plan' },
          severity: { type: 'string', enum: ['blocking', 'major', 'minor'] },
          rationale: { type: 'string', description: 'why it matters, grounded in the plan text or the codebase' },
          fix: { type: 'string', description: 'the concrete correction to make to the plan before implementing' },
        },
        required: ['concern', 'severity', 'fix'],
      },
    },
  },
  required: ['lens', 'overall_verdict', 'biggest_risk', 'findings'],
}

const brief = args.briefPath
const context =
  args.context ||
  `This is a HydraFlow plan. HydraFlow is a LIGHTS-OFF autonomous software factory. Its crash-safety rests on ADR-0002 (GitHub labels are the sole source of truth) — kill the process at any point and the labels tell the next boot exactly where every issue stands. It runs six pipeline phases with worker-per-phase concurrency (ADR-0001). Weigh any plan against those invariants.`

const COMMON = `Read the plan at ${brief} in full — it is a real, not-yet-implemented design, together with the ADRs and existing scaffolding it touches.

Project reality you must weigh every finding against:
${context}

You are an ADVERSARIAL reviewer. Your job is to find what is WRONG, missing, under-specified, or risky — NOT to bless it. Default to skepticism. A finding that names a concrete defect with a concrete fix is worth more than praise. Where the plan cites an ADR, a file, or a primitive, check whether it actually says/does what the plan claims. If the plan is genuinely sound on some axis, say so briefly, but spend your effort on what would bite us in production.`

async function review(lens, charter) {
  return agent(
    `${COMMON}\n\n${charter}\n\nReturn structured findings, each grounded in the plan text or the codebase. Severity: 'blocking' = must fix or the plan is unsafe to implement; 'major' = will cause real pain/rework; 'minor' = worth noting.`,
    { label: `review:${lens}`, phase: 'Review', model: 'sonnet', schema: FINDINGS_SCHEMA }
  )
}

const reviews = (await parallel([
  () => review('principal-engineer', `YOU ARE A SENIOR PRINCIPAL ENGINEER. Your lens: is the ABSTRACTION right and will it actually WORK?
- Is this the correct decomposition, or complexity for its own sake? Is there a materially simpler design that gets the same outcome?
- Does the core mechanism actually buy what the plan claims it does? Trace it — where does the claimed benefit come from, and does it survive the details?
- Does the plan preserve the load-bearing invariants of the system, or quietly weaken one? Is that preservation stated as a hard constraint and demonstrated, or merely asserted?
- Does the plan match the code/state that already exists? Cite the file where it doesn't.`),

  () => review('vp-engineering', `YOU ARE A VP OF ENGINEERING. Your lens: should we build THIS, NOW, this WAY?
- Blast radius: what does this change for everything already running? Is any "safe default / prove it first" migration story credible, or a fig leaf over a rewrite?
- Sequencing: is this the right next step, or is there a missing intermediate (a spec, a shadow/canary mode, a metric) before it?
- Scope: is this one plan or three? What is the smallest increment that de-risks the rest?
- Reversibility & opportunity cost: if this is wrong, how expensive is it to unwind vs today? What existing behaviour does it put at risk?`),

  () => review('staff-sre', `YOU ARE A STAFF SRE / RELIABILITY ENGINEER. Your lens: how does this FAIL, unattended, at 3am?
- Crash & resume: what happens if the process dies mid-operation? Does the plan define the recovery path, or hand-wave it? Does its state model actually cover every mid-operation point, or only the tidy boundaries?
- State divergence: if two sources of truth can disagree, how does the next boot reconcile them, and what is the failure mode when they don't?
- Preemption & backpressure: what throttles the expensive work? Can high-priority work jump ahead, or does it wait behind something long-running with no bound?
- Observability & rollback: what is the on-call signal when this wedges? Can an operator see progress and roll back without a deploy?`),
])).filter(Boolean)

log(`Collected ${reviews.length}/3 reviews`)

phase('Synthesize')

const synthesis = await agent(
  `You are the staff+ engineer synthesizing an adversarial plan review before we commit to implementing it. Read the plan at ${brief} for context.

Three senior reviewers attacked it independently. Their structured findings:

${JSON.stringify(reviews, null, 2)}

FIRST, verify the crux claims against source. Before trusting any blocking finding, check it against the actual code/ADRs on origin/staging — does the cited ADR really say that? is the named primitive really non-atomic / really absent? Mark each crux claim verified or unverified; a confidently-wrong finding is worse than none. Use the repo tools to check.

THEN produce a synthesis for the plan's author to act on BEFORE writing/finishing the implementation plan:

1. **Verdict** — one line: ship-with-corrections / rework-before-implementing / do-not-build. Weigh the three verdicts; don't just average them.
2. **Blocking corrections** — the findings that MUST be resolved in the plan first. Merge duplicates across reviewers (note where 2+ reviewers independently hit the same thing — that convergence is the strongest signal). Each in imperative form: the exact change to make.
3. **Cross-reviewer conflicts** — where reviewers disagree or their fixes pull in opposite directions, and your adjudication.
4. **Major (non-blocking) improvements** — worth doing, not gating.
5. **The one thing** — if the author fixes only a single item, which one and why.

Be concrete and terse. This feeds directly back into the plan; it is not a status report. Do not soften findings to be diplomatic — the point of the panel is to catch what a single author misses.`,
  { label: 'synthesis', phase: 'Synthesize' }
)

return { reviews, synthesis }
