# Board feeder: generated intake from the team's intent surface

**Status:** proposal (2026-08-19). **Precedent:** `feeder-agents.md` (2026-07-26) — generated intake from inside the repo; this is the same species pointed outward. **Depends on:** the intake conventions and the triage gate; ADR-0103 (steering: the how/what boundary). **Kin:** `llm-gateway-session-tap.md` — together they complete the team-onboarding stack: board feeder governs intent-in, repo harness governs artifacts, the mint governs credentials, the gateway governs traffic.

## The gap

The feeder-agents proposal widened the funnel from inside the repository: survey the code for latent work, propose, let triage dispose. But a team's intent does not start in the repository. It starts on a task board — cards, tickets, a queue the humans actually groom — and today the path from card to factory intake is a human retyping intent into an issue. That path is the last hand-maintained list in the loop: whether the factory sees the team's work depends on someone remembering to transcribe it. Teams onboard with their board, or they do not onboard.

## Design

One **board feeder** per registered team: an agent whose only job is watching a designated task board and translating qualifying cards into factory issue proposals.

### The hard rule, inherited verbatim (decided)

**Scouts propose, triage disposes.** The feeder's write surface toward the factory is issue-proposal creation only — never merges, never label transitions past the front door, never edits to existing issues. Proposals wear the same distinct intake label as repo-feeder proposals, and the triage gate (with the human at whatever sampling rate trust has earned) decides what becomes work. A card on a board is a wish; triage is where it becomes intent the factory owns.

### The reverse channel: mirror, never hands (decided)

Factory→board is **status mirroring only**: a read-only reflection of repo truth onto the team's cards — linked issue state, PR merged, gate failed, parked-awaiting-clarification. The feeder never reprioritizes, splits, closes, or creates cards, and never comments except to attach its mirror link. The board is the humans' instrument for set-point discovery, and ADR-0103 reserves set-point discovery for humans; an agent that edits the board is steering the what, not the how. Intent flows in as proposals; truth flows out as telemetry; the valve stays human.

### Translation, not interpretation (decided)

A card becomes a proposal only when it clears a **readiness screen** mirroring what triage will ask: enough intent to act on, a target repo the factory is registered in, no open duplicate (dedupe against both open issues and prior proposals from the same card). Cards that fail the screen are left alone — the feeder files nothing and nags nobody; a card that never ripens is the team's business. The proposal body carries provenance: board, card link, card state at translation time, and the screen verdicts.

### Adapter faces (decided)

The board surface is an adapter interface with one reference implementation first (GitHub Projects — same auth domain as the factory), the interface shaped so Linear/Jira faces are additional adapters, not redesigns. The feeder core (screen, dedupe, provenance, mirror) is board-agnostic; only the face knows the board's API.

### Bounds (decided)

Kill switch and watchdog like every loop. A finding-rate budget — a generator without a budget is an intake flood. Read-only board access plus issue-create toward the factory, nothing else. The feeder itself is a governed principal: when the gateway's mint lands, it holds a minted key like any other loop — the intake machinery is not exempt from the governance it feeds.

### Territory precondition (decided)

A board feeder is only wired to a team whose repo has been through repo prep. Enforcement is territorial — gates, CI, labels are what the factory holds work against — and a feeder pointed at an uninstrumented repo generates intake nothing can govern. Board wiring is the *last* step of team onboarding, never the first.

## Acceptance

- Proposal acceptance rate at triage is the feeder's trust metric, tracked like the repo feeder's: mostly-declined proposals cut the budget, never raise the volume.
- Intake share by source (human-filed / repo-generated / board-generated) is visible, so the meter can say whether board intake pays.
- No board proposal reaches implementation except through the same triage gate as human-filed work.
- The mirror is provably read-only: the feeder's board credential cannot mutate cards, verified at the permission layer, not by promise.

## The one-line version

The board is where the team wishes; triage is where the factory decides; the feeder is the courier between them — carrying proposals in, mirroring truth out, holding no valve in either direction.
