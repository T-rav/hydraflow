# Keeping the core factory dark (no humans in the loop)

Lessons distilled from the 2026-06-13 → 2026-06-18 incident arc, where the HITL
queue repeatedly filled to 30–40 issues. The pattern across every incident: the
factory was **working correctly** but a small number of *systemic* gaps turned
transient conditions into human-intervention pile-ups. "Dark" doesn't mean "no
HITL" — it means **HITL contains only work a human genuinely must do**, and the
factory never escalates work it could have handled itself.

This is the operating companion to [`docs/wiki/dark-factory.md`](../wiki/dark-factory.md).

## The dominant failure mode: unrecognized billing-limit messages

A single unrecognized subscription-cap string is the #1 dark-factory killer.
When an agent's output isn't classified as credit exhaustion, the runner scores
it as a normal failure: attempts are **burned**, in-flight PRs are **closed**,
and the issues are **dumped to HITL** en masse.

- **2026-06-13** — `"You've hit your session limit · resets 5:50am"` not matched
  ("session" between "hit your" and "limit") → ~8 PRs closed, queue flooded
  (PR #9529).
- **2026-06-17** — `"You've hit your weekly limit · resets Jun 18 at 5pm"` — the
  *same class*, recurred for the weekly cap; one issue logged 492 billing-message
  comments before anyone noticed (PR #9589).

**Invariants:**
1. Detect the **entire** `hit your <period> limit` family with one regex, not
   per-phrase substrings — a new cap type (daily/monthly) must not need a code
   change to be caught. Word-boundary anchor it so prose can't false-positive.
2. Parse **every** reset format (`5pm`, `5:50am`, `Jun 18 at 5pm`,
   `Wednesday at 5pm`, ISO-UTC). When unparseable, fall back to a short default
   pause and re-evaluate — never idle for a year, never resume in seconds.
3. On detection: **pause all loops + refund the attempt.** Detection is
   load-bearing precisely because it drives the refund — that's what stops the
   HITL escalation. (Refund logic already existed; only detection was broken.)
4. The moment a new limit wording is observed in the wild, add it the same day.

## Run current code, verify against origin

- A **stale local checkout** (15 commits behind `origin/main`) meant merged
  fixes never took effect *and* grepping the working copy produced wrong
  "not fixed" conclusions (two issues were misjudged as over-closed).
- **Invariants:** run the factory from an isolated workspace that hard-syncs to
  base each launch (`make factory`, PR #9538); always check fix-state with
  `git show origin/main:<file>`, never the working copy.

## Don't pollute the checkout you run from

Loops mutate `repo_root`; PRs are built in ephemeral worktrees that never clean
the originals → perpetual dirt and **uncommitted knowledge** (248 wiki entries
stranded). Untrack pure runtime caches (PR #9537); generate inside the worktree,
never `repo_root` (proposal #9539); isolated workspace is the catch-all.

## Auditors must dispose, not escalate

Over-eager auditors manufacture false-positive HITL: ADR-drift on shared /
high-churn modules, fake-coverage re-fires. Right-size at the source
(shared-infra exclusion + symbol-qualified citations, PR #9530). An auto-resolver
that can't "fix" an in-scope/false-positive finding must be able to **close it as
a no-op** — looping to HITL forever is the anti-pattern.

## Don't bulk-requeue un-auto-resolvable work

Requeuing 39 stuck issues re-escalated 21 of them: work that genuinely needs a
human (provision infra) or exceeds the agent belongs in HITL, and requeuing only
delays the inevitable while burning cost. **Triage before requeue; only unstick
genuinely-bounded, auto-doable fixes.** HITL filling with real human tasks is the
system working — not a bug to paper over.

## Verify factory-core changes adversarially before merge

An adversarial review caught a **data-loss bug in a one-line safety guard** (a
relative `HYDRAFLOW_FACTORY_WORKSPACE` bypassed an in-place check, so a
hard-reset could wipe the dev checkout). Invariants: run a diff through
adversarial review before merging anything that mutates the repo or git state;
canonicalize paths before equality guards.

## Tell graceful-stop from crash

A clean `"Stop requested — terminating active processes"` shutdown is not a
crash — don't auto-restart it (it may be intentional). Surface the state and the
exit cause; don't assume.

## The scoreboard that matters

Not "HITL count = 0" but: **(a)** zero attempts burned on billing pauses,
**(b)** zero PRs closed by transient conditions, **(c)** HITL contains only
genuine human tasks, **(d)** the running factory is on current code. When those
hold, the queue self-drains and humans only see what truly needs them.
