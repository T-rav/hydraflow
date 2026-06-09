# Talk Skeleton — When Code Becomes FLUID

*Companion to `2026-06-when-code-becomes-fluid.md`. Derived from the blog; not a transcript.*

- **Conference:** Accelerate Chicago 2026 · June 22–24 · Convene Willis Tower, Chicago
- **Conference tagline:** *"Craft software with confidence in 2026. You ship it, you own it, you maintain it."*
- **Conference pillars:** Foundations · AI as leverage · Build with confidence
- **Target duration:** 45 minutes content (full version runs ~51 min — see Talk Cuts at the end)
- **Audience:** ~300 mixed — team leads, managers, architects, developers. Practitioner-focused, not academic.
- **Adjacent speakers worth name-checking:** **Alistair Cockburn (Hexagonal Architecture inventor; Agile Manifesto co-author; BDD-adjacent lineage)** — this is the deepest alignment in the room. HydraFlow's core architecture *is* Cockburn's hex pattern; the dark factory contract *is* hex + BDD. Nathen Harvey (DORA Lead at Google Cloud) — conference name comes from the DORA "Accelerate" book; your new-metrics extension is on-mission for the whole event. Scott Hanselman (Microsoft/GitHub). Bret Fisher (Docker Captain) — your "container is solid, code is fluid" metaphor is literal container language. Where their work touches yours, be explicit about continuity, not replacement.
- **Source abstract:** *Self-Building Software: Lessons from the HydraFlow Experiment*
- **One-line takeaway:** *The durable artifact is no longer the code; it's the operating system that governs how the code evolves.*
- **T-shirt line:** *Autonomy without validation is just accelerated entropy.*
- **The asymmetry:** *The container is solid. The code inside it is fluid. The container is what makes fluidity safe.*
- **The container, named:** *Hex architecture (Cockburn 2005) + BDD scenarios (North 2003) = the dark factory contract.*
- **The operator's role:** *I don't review code. The system does. **Humans provide intent and test** — specs, ADRs, conventions, scenarios. Everything between those two surfaces is system-internal. Dark factory mode — lights-off operation — is the goal.*
- **The audience anchor:** *If you trust Cockburn, North, DORA, Vincent, Karpathy, Shapiro, Willison, Yegge, Junker, McKinney, or any of these authorities individually — this is where their lines collectively point. The talk isn't a prediction. It's a report from inside the intersection. HydraFlow is one of **a handful of published working instances** of it — and new aligned cases are surfacing month over month.*

---

## The argument chain (the spine you should always be able to recite)

1. AI is destabilizing engineering identity — and the autocomplete frame keeps us stuck.
2. FLUID describes the new code shape. V2V is the methodology. HydraFlow is the operational system embodying both.
3. Running HydraFlow surfaced four patterns: caretaker taxonomy, validation as engine, MockWorld as world-modeling, process as deliverable. They share one underlying move — *quality enforcement migrated from social to structural* — and collapse into one principle: *autonomy without validation is just accelerated entropy*.
4. SOLID didn't disappear in this regime — it migrated. The container around the code is SOLID-shaped (TDD, BDD, CI, disciplined boundaries). That's what makes the code inside it safely fluid.
5. These patterns sit on a five-step staircase. The *public discourse* is parked on step one; platform teams at Cursor, Sourcegraph, Anthropic, Cognition are working on the same steps internally. **The same operational shape is now emerging across a handful of published cases — HydraFlow, StrongDM's Attractor, Wes McKinney's factory, Yegge's Gas Town, and new aligned voices surfacing month over month — from different architectures, different teams, different domains, with no cross-reference. The pattern is in the field, not in any one implementation. The contribution isn't being first — it's being coherent. A working instance of a pattern emerging across the field, with the operational shape made legible.**
6. This isn't for all software — but the next experiment (games) tests whether there's a class where humans can step out of the mutation loop.
7. The engineers who thrive are the ones with the SOLID craft foundation underneath, because that's what builds the FLUID container. The leverage hierarchy is changing; the craft isn't disappearing — it's projecting up a level. *In HydraFlow's mode, that projection is literal: I don't review code; I encode the workflows the system reviews against. Dark factory mode — lights-off operation — is the goal the patterns are built toward.*

If you forget your slides, you can deliver this talk from those seven beats.

---

## Timing budget

| Movement | Time | Slides | Purpose |
|---|---|---|---|
| 1. Cold open + setup | 5 min | 4 | Destabilize the autocomplete frame, name what's actually happening |
| 2. FLUID / V2V / HydraFlow | 5 min | 4 | Establish the three-layer hierarchy; demo HydraFlow |
| 3. The compressed-cognition trap | 3 min | 2 | Engage Tornhill directly, sharpen to system-scale |
| 4. Craft foundation + social→structural + asymmetry | 5 min | 3 | Set up the reframe that unifies the patterns |
| 5. Four patterns + entropy summary + convergence | 20 min | 14 | The meat — four patterns, closing principle, parallel-evolution observation |
| 6. Staircase + SDLC breakdown | 5 min | 4 | Where value moved, what gap it fills |
| 7. V2V teams + peers + scope + games | 6 min | 4 | Team shape, where peers sit on the review axis, honest scope, the tighter hypothesis |
| 8. Containment + what breaks + where engineer goes | 5 min | 4 | How cascades are prevented, honesty about failure modes, then the personal arc |
| 9. Close | 1 min | 2 | The central shift, the next experiment |
| **Q&A** | **5–10 min** | — | Prep below |

**Total: 41 slides, ~55 min content + Q&A.** That's the comprehensive version. The Talk Cuts section at the end shows how to trim to 45 min. None of the V2V-teams, peers, containment, or what-breaks-next slides should be cut.

---

## Slide-by-slide spine

For each slide: **title** · *visual* · speaker beat (1–2 sentences, compressed). Adapt the wording; the structure is what's load-bearing.

### Movement 1 — Cold open + setup (5 min)

**S1 · Title slide** · *Title + your name + project URL hydraflow.ai* · Title card. Hold for 5 seconds. Don't speak yet.

**S2 · "Within days, it started modifying itself."** · *Single line of text, dark background. Small metadata strip below: "FLUID written: March 2025 · Gas Town trigger: Jan 1, 2026 · First commit: 2026-02-18 · ~2.5 months · 15 caretaker loops · hundreds of autonomous PR cycles."* · "I wrote FLUID — the principles behind this — fourteen months ago, in March 2025. It sat as philosophy for nearly a year. The trigger to actually build came from Steve Yegge — January 1 this year, his *Gas Town* piece showed me the operational thing was buildable. *(beat)* Seven weeks later I made the first commit on HydraFlow — February 18, 2026. *(beat)* Two and a half months ago. Within days of becoming functional, it started modifying its own codebase. Hundreds of autonomous PR cycles later, running fifteen caretaker loops across itself and other repositories, I'm here to tell you what that taught me — and why most of the industry is asking the wrong questions. This conference's tagline is *craft software with confidence — you ship it, you own it, you maintain it.* I want to take that seriously, because the part of that sentence that's changed the most under AI isn't *ship* or *own*. It's *maintain*. And once you understand how *maintain* has changed, the rest of the sentence has to change with it."

**S3 · Code was identity** · *List of identity signals: competence, mastery, creativity, rigor, control, value* · "For decades, code wasn't just implementation. It was identity. Then AI arrived and destabilized the relationship between effort and implementation. The anxiety in our industry isn't really about productivity. It's about that."

**S4 · The autocomplete frame is keeping us stuck** · *Two columns: "Autocomplete era" (coding speed, throughput, prompt quality) vs "What's actually happening" (planning, retry, recovery, merge validation, operational loops)* · "Most of the conversation about AI in engineering is parked at autocomplete. But the real shift isn't AI helping humans write software. It's AI participating in software delivery. That's a different engineering discipline."

### Movement 2 — FLUID / V2V / HydraFlow (5 min)

**S5 · FLUID** · *Five principles: Flexible composition · Live prototypes · Unified context · Intent-driven structure · Dynamic refactorability. Below in smaller type, a timing strip: "Written March 2025 — ~10 months before the named-framework wave (Shapiro Jan '26 · Gas Town Jan '26 · StrongDM Feb '26 · Junker May '26)."* · "Fourteen months ago — March 2025 — I wrote down a set of principles I call FLUID. The argument was that SOLID was optimized for the era when humans wrote every line. AI-native development inverts those economics. FLUID describes what code should look like when machines and humans co-author it. The timing matters: I wrote FLUID about ten months before the named-framework wave for AI-era engineering formed — Shapiro's five-level, Yegge's Gas Town, StrongDM's case, Junker's three roles, all between January and May 2026. At the time, Karpathy had just coined *vibe coding* as a term; Yegge published *Revenge of the Junior Developer* the same month as FLUID. The thinking was in the air, in a small cohort. **FLUID was the earliest *named alternative to SOLID* for the AI era.**"

**S6 · Three-layer hierarchy** · *Diagram: V2V (methodology) → FLUID (code shape) → HydraFlow (operational system). Below, small attribution strip: "V2V sits in Jesse Vincent's agentic engineering tradition · Superpowers framework is the workflow substrate."* · "There's a methodology underneath this I call Vibe to Value. Outcomes from intent, via high-quality AI-assisted software built with robots. FLUID is the code-shape philosophy. V2V is the methodology. HydraFlow is the operational system embodying both. V2V sits inside what Jesse Vincent has been calling *agentic engineering* — and I want his framing on the record because it's the cleanest articulation of the distinction I've heard: *'The difference between vibe coding and agentic engineering is planning, architecture, and caring about the output.'* His Superpowers framework — brainstorming, spec, plan, TDD, sub-agent-driven implementation, fresh-eyes review — is the workflow substrate HydraFlow runs on. This talk is a status report on V2V."

**S7 · HydraFlow in one diagram** · *Flow: GitHub issue → agents plan / implement / validate → subagent review (multi-pass) → PR → MERGE. Two human surfaces feed the system from outside the PR path: **INTENT** (specs · ADRs · conventions · autonomy doctrine) and **TEST** (scenarios · Given-When-Then operating conditions). Everything between those two surfaces is system-internal.* · "HydraFlow is multi-agent orchestration that treats delivery itself as programmable. Issue in, PR out — agents handle decomposition, implementation, validation, recovery, and *merge*. **Humans provide intent and test.** That's it. The intent surface is specs, ADRs, conventions, the autonomy doctrine. The test surface is scenarios — Given-When-Then operating conditions the system has to honor. Everything between those two surfaces is the system's responsibility, not mine. To be precise: most cycles are small — dependency bumps, term proposals, regen passes. Substantial features go through the system's own multi-pass review — subagent-driven spec-compliance checks, code-quality reviews, fresh-eyes audits. *I don't review code.* The system does. My role is co-building with the system on the intent and test surfaces. The goal HydraFlow is built toward is **dark factory mode** — lights-off operation, operator paged only for raging fires. In practice right now: we co-build new conventions and loops together, the system runs through the night, I adjust in the morning if anything looks off. The core has bedded down. My time goes into *extending* the factory with new operational primitives — operationalizing more concepts as living artifacts."

**S8 · DEMO: HydraFlow taking an issue (pre-recorded, 60–90s)** · *Sped-up screencap of an actual autonomous cycle — issue filed, agent claims it, branch created, PR opened, tests run, label updates* · "Here's what that looks like. I'll let it run." Stay silent during the demo. Cut back to slides immediately at end.

### Movement 3 — The compressed-cognition trap (3 min)

**S9 · The 19% slower paradox** · *Single stat: "Engineers using AI tools felt 20% faster. They were 19% slower."* · "Adam Tornhill's framing is that AI compresses decision density past what working memory can hold. Engineers feel faster, are actually slower. The mechanism is real."

**S10 · System scale vs human scale** · *Two-column: "Human scale: pacing, fatigue" vs "System scale: comprehension debt, drift"* · "But operating HydraFlow taught me this is only the human-scale symptom. The deeper risk is system-scale: the artifact changes faster than any human-maintained mental model can track. The pauses we lost weren't rest periods. They were where understanding got compiled."

### Movement 4 — Craft foundation + social→structural + asymmetry (5 min)

**S11 · TDD · BDD · SOLID · CI: the substrate, not the relic** · *Four pillars holding up a platform labeled "FLUID system"* · "Before I go further — this experiment was only runnable because of forty years of accumulated engineering practice. TDD gave every change a regression test. BDD became the entire MockWorld substrate, you'll see. SOLID gave the system enough structural integrity that mutations don't cascade. CI catches the gaps. The talk you're about to hear is 'lessons from a self-modifying system.' But the system was only safe to mutate because the craft underneath held."

**S12 · Quality migrated from social to structural** · *Title across top. Two columns. Left ("Was — social"): senior reviewers · tribal knowledge · manual discipline · review by memory. Right ("Now — structural"): validation continuous · governance executable · process encoded · regression systemic · scenarios authoritative · recovery automated · semantic drift detectable.* · "Quality enforcement used to be social — senior reviewers, tribal knowledge, manual discipline. In a system that mutates daily, that doesn't scale. HydraFlow doesn't lower the quality bar. It moves the bar *into* the system. The four patterns are all instances of one move: quality migrated from social to structural. If you hear 'FLUID' and think 'lower standards,' you've got it exactly backwards. And it isn't free — there's a J-curve. Most of HydraFlow's early engineering went into the structural container itself. The factory output didn't start paying back until the container could carry it."

**S13 · Solid container, fluid contents** · *Diagram: outer **hexagonal** frame labeled "Hex architecture + BDD scenarios = the dark factory contract" surrounding inner area labeled "FLUID contents — agent-authored code, regenerating." Small subtitle below: "Cockburn 2005 + North 2003. Not new. Run at autonomous-system scale."* · "Here's what FLUID actually requires from SOLID. SOLID doesn't disappear. It migrates — from being properties of the code itself to being properties of the container around the code. **The container is solid. The code inside it is fluid. The container is what makes fluidity safe.** And to be specific about what that container *is*: HydraFlow's core architecture is Hexagonal — Cockburn's pattern from 2005. Every external dependency goes through a typed Port. Every Port has a Fake adapter the conformance tests keep in sync. BDD scenarios drive behavior at the port boundary. *That combination — hex architecture with BDD-defined contracts at every port — is the dark factory contract.* It's what makes MockWorld possible. It's what makes substantial features replaceable without cascading damage. None of this is new architecture. It's Cockburn's hex plus North's BDD, run at autonomous-system scale. Your craft as a SOLID-era engineer is more valuable here, not less. It's projected up a level."

### Movement 5 — Four patterns + entropy summary + convergence (20 min)

#### Pattern 1 — Caretaker loops form a taxonomy (4.5 min)

**S14 · "15 loops. I designed 2. Categories almost name themselves."** · *Photo of a busy control panel or 15 small icons arranged loosely* · "HydraFlow runs fifteen caretaker loops. I designed the first two up front. The other thirteen accreted, one at a time, each in response to a recurring operational concern I noticed across multiple incidents. Two decades of engineering practice clearly shaped *which* loops I built — but the *categories* weren't in my original sketch. They emerged. Looking at the set now, the categories almost name themselves."

**S15 · The taxonomy** · *8-cell grid: Maintainers (RepoWiki, Diagram, GitHubCache, PricingRefresh) · Proposers (TermProposer, EdgeProposer, EntryEvidence) · Pruners (TermPruner) · Auditors (PrinciplesAudit, AdrTouchpoint) · Repairers (SandboxFailureFixer, AutoAgentPreflight) · Watchers (HealthMonitor, CostBudgetWatcher) · Promoters (StagingPromotion) · **Provocateurs (CorpusLearning, SkillPromptEval, + advisor pattern)**. Subtitle below the grid: "Three categories (Maintainers · Proposers · Pruners) keep concepts alive without human maintenance — living artifacts, not static slop. Provocateurs keep the validation engine honest by attacking the system on purpose."* · Walk the grid quickly: "Maintainers keep state fresh. Proposers grow new state. Pruners shrink stale state. Auditors verify invariants. Repairers fix when broken. Watchers escalate or budget. Promoters move state through tiers. **Provocateurs challenge the system's own assumptions — `CorpusLearningLoop` synthesizes adversarial cases from past skill failures, `SkillPromptEvalLoop` runs them weekly against the built-in skills, and the advisor pattern wires preflight and post-verify provocations into PR review, ADR review, and the visual gate.** Eight categories from the working fleet. None were in my original sketch." Then lift to the deeper point: "There's a critique of AI-assisted engineering that says it generates *slop* — sloppy code, hallucinated functions, dead documentation. That critique misses where slop actually comes from. Slop comes from static artifacts humans can't keep current at the rate the code mutates. In a HydraFlow-class system, the wiki regenerates from live events, the glossary auto-extracts from code, the drift detector breaks the build when names diverge. These aren't sloppy. They're the *opposite* of slop — *living artifacts*, maintained by the system itself, kept current at the rate the code changes. That's the conceptual layer becoming as runtime as the code is."

**S16 · The cross-cutting contract** · *Five bullets: ADR-0049 kill switch · Static config gate · Credit-aware budgets · Five-checkpoint wiring · Auto-discovery test* · "The cross-cutting concerns ARE the operating contract. Every loop, no exceptions. The durable architecture isn't the application code. It's the loop taxonomy and the contract every loop honors. The takeaway: you don't design these up front. You let them emerge, then make them legible enough that the next instance slots in rather than re-inventing."

#### Pattern 2 — Validation became an engine (4.5 min)

**S17 · PR #8460 → #8463 in 42 minutes** · *Timeline graphic: "21:43 — merge, 211 tests passed" → "22:25 — hotfix lands"* · "Code-cleanup PR last May. Removed redundant defensive `getattr` checks. 211 unit tests passed. Pyright clean. Merged. Forty-two minutes later, main was red. Tests broken in two files the implementer hadn't run. The hotfix landed 42 minutes after that."

**S18 · The validation didn't gate. It pushed.** · *Animated: "wrong code" → big red X (gate framing) struck through · "right code → sharper code" (engine framing) replacing it. Below in smaller type, an attributed pullquote: "A wrong-but-specific draft is faster to evaluate, edit, or reject than a blank page. — Annegret Junker"* · "Read that incident as a validation failure and you miss the point. The validation worked. It exposed a class of usage the cleanup hadn't accounted for. Each correction encodes back. Annegret Junker captures the dynamic from a different angle: *'A wrong-but-specific draft is faster to evaluate, edit, or reject than a blank page.'* The agent's first pass doesn't have to be right — it has to be specific enough that validation can push it toward right. That's why the convergence count exists at all: three to five iterations isn't waste, it's the shape of how rightness emerges when wrongness is fast and cheap. The 'AI code is garbage' discourse is measuring the wrong thing — it evaluates *generation* quality. The patterns measure *convergence* quality under governed mutation. Different question."

**S19 · The convergence count** · *Bar chart: Trust-fleet PR #8390 = 5 subagent passes · Auto-Agent #8439 = 3 subagent passes · "Substantial features converge in 3–5 iterations — all system-driven"* · "Three to five iterations of validation for substantial features — all run by subagents, none by me. That isn't waste. That's where the design actually happens. Convergence is the design completing itself, and the operator is free to be elsewhere while it converges. This is what 'I don't review code' actually means operationally — the *system* reviews, the *system* converges. My time goes upstream, into the conventions the subagents review against."

#### Pattern 3 — MockWorld is BDD as environment substitution (5 min) **[the bold claim — give it room]**

**S20 · The three-layer pyramid** · *The actual pyramid diagram from docs/standards/testing/README.md — Unit (ms) / MockWorld (sec) / Sandbox (min)* · "HydraFlow ships every load-bearing feature through three layers. Unit at the bottom. Sandbox e2e at the top. MockWorld in the middle. The middle is the novel piece."

**S21 · Mocks vs MockWorld** · *Split panel: "Traditional mock: input → output, one call" vs "MockWorld: a coherent world with state, time, and failure modes"* · "Traditional mocks simulate responses. MockWorld simulates conditions. The world has state. The world has time. The world has failure modes you can program. Given the API is degraded, given auth is flaky, given the operator has a budget cap..."

**S22 · "Given-When-Then was always pointing at the world."** · *The line as the slide, dark background, large type. Below in smaller type: "MockWorld = Cockburn's hex + North's BDD, run at autonomous-system scale."* · "That's not mocking. That's BDD pushed all the way. The 'Given' expands past user flows to include the whole operating environment. And this works structurally because the core architecture is Hexagonal — Cockburn's pattern. External dependencies all go through typed Ports. MockWorld swaps Fake adapters at the port boundary while the system code inside the hexagon runs unchanged. The Port↔Fake conformance tests keep them honest. *Given* the GitHub Port returns a credit-exhausted error, *when* the loop ticks, *then* the system yields its attempt budget. The whole machine is two well-known patterns composed — Cockburn's ports plus North's behavior-driven scenarios. Together they form the dark factory contract. It's continuity with twenty-plus years of behavior-driven and architectural thinking, not a replacement. It just took autonomous systems to make these patterns urgent."

#### Pattern 4 — The process became the deliverable (4 min)

**S23 · "The factory isn't its code. It's the contract its loops operate inside."** · *Single line, dark background* · "Here's the pattern I find hardest to articulate, and the one that mattered most. What HydraFlow runs on isn't its code. The code regenerates. The architecture mutates. The models roll over every few months. What persists is the process discipline."

**S24 · The contract** · *Flow diagram: Brainstorm → Spec → Plan → TDD → 3-pass review → make quality → arch-regen → merge → auto-promote to main* · "This is the process. Every step has a checklist. Every checklist has a discoverability surface. The process isn't in a slide deck. It's in the repo. Agents inherit it by reading."

**S25 · "I didn't invent these conventions. I accumulated them."** · *Quote-card with that line · subtitle: "First time: a bug. Second time: a pattern. Third time: a discipline codified into the repo so it survives every future agent."* · "Every discipline in HydraFlow is the response to a class of failure that bit me. The code is the artifact in the conventional sense. But the process discipline is what makes the code possible in a FLUID regime."

#### Pattern summary + convergence (2 min)

**S26 · "Autonomy without validation is just accelerated entropy."** · *Bare quote card, dark background, large type. The line and nothing else.* · Hold the slide in silence for 5–10 seconds before speaking. Then: "Read the four patterns together — they collapse into one principle. HydraFlow doesn't work because the agents are clever. It works because the system has structural answers to *what happens when a clever agent is wrong.* That's the talk's t-shirt."

**S27 · The pattern is in the field** · *Four working-instance boxes (chronologically ordered) around a center node labeled "Same operational rules emerging across the field — and the list is growing":*
> · **Gas Town** (Jan 1, 2026) — Go + tmux + Beads + MEOW stack — *Steve Yegge* — earliest published
> · **StrongDM Attractor** (Feb 7, 2026) — DOT-graph pipelines + coding-agent library — *McCarthy / Taylor / Chauhan*
> · **HydraFlow** (Feb 18, 2026) — hex + BDD + caretaker loops — *Travis Frisinger, solo*
> · **McKinney's factory** (May 12, 2026 reveal) — parallel agents + RoboRev background reviewer — *Wes McKinney*

*Below the center node, four convergent rules listed:* `No human code review · Scenarios drive behavior · Port-isolation at I/O · Human-as-spec-author` *and a smaller line:* `Convergence depth — three independent sources of the same number: HydraFlow 3–5 passes · McKinney 4–5 minimum · Yegge cites Emanuel's "Rule of Five"`

· "Here's where the talk stops being about HydraFlow. And this is the part that matters most for you, the audience. **None of what I'm arguing requires you to trust me. It requires you to recognize where the people you already trust on these topics are each pointing.** Cockburn's hex (2005) builds the container. North's BDD (2003) tells you what should happen at each port. DORA tells you how to measure when delivery is working. Vincent's Superpowers encodes workflow as discipline agents inherit. Karpathy says context engineering is the new prompt engineering. Shapiro's five-level framework, January, names the trajectory. **Yegge launches Gas Town on January 1 — an orchestrator for 10–30 parallel Claude Code instances, explicit 'dark factory' framing, role-based worker taxonomy.** Willison documents StrongDM's L5 implementation, February. Junker maps three agent roles — Drafter, Validator, Provocateur — last week. McKinney reveals his factory days ago. **Independent voices, different sub-domains, no coordination. All pointing at the same place:** software delivery as a programmable surface, agents do the work, humans provide intent and test, validation runs continuously, the operational system — not the code — is the durable artifact. That's the future they're collectively describing. *I'm not asking you to take any of this on my authority. I'm asking you to draw the lines between theirs.* I have **a handful of published working instances of the same operational shape now**, sitting at the intersection of those lines — and new aligned cases are surfacing month over month. In chronological order of publication: **Yegge's Gas Town** — January 1, the earliest. **StrongDM's Attractor** — Willison documented their L5 implementation on February 7. **HydraFlow** — what I've just walked you through, first commit February 18. **Wes McKinney's factory** — pandas creator, parallel agents with a RoboRev background reviewer, revealed days ago. One precision worth naming honestly: Gas Town wasn't independent for me — it was the *catalyst*. Yegge's piece showed me the operational thing was buildable, and I started seven weeks later, with FLUID already in hand from over a year before. **StrongDM, McKinney, Junker — those are genuinely independent**; I didn't know about any of them until well after my first commit. Different teams. Different architectures. Different domains — orchestration in Go-plus-tmux, DOT-graph pipelines for enterprise access management, hex-plus-BDD caretaker loops, parallel data-science factories. And the language is converging at the commercial layer too — **Factory.ai has been selling *'Your software Factory powered by Droid'* as a product positioning since 2024.** When a commercial vendor with capital and customers names their offering *software factory*, you're not arguing for a future. You're describing one that already has a market. And here's the empirical kicker that lands hardest for me: **the convergence-pass count keeps surfacing as the same number.** McKinney's *'four or five times minimum.'* My *'three to five iterations.'* Yegge cites Jeffrey Emanuel's *'Rule of Five'* review-pass discipline as a load-bearing principle. Three independent voices, the same number. That's not coincidence."

### Movement 6 — Staircase + SDLC breakdown (5 min)

**S28 · The staircase** · *Literal 5-step diagram, each step labeled: Code generation → Validation systems → Semantic governance → Operational knowledge graphs → Autonomous mutation governance* · "The four patterns converge on a staircase. The public discourse is still parked on step one. HydraFlow is showing what four and five look like operationally — though platform teams are working on these steps too. Each step is necessary for the next. Karpathy has a useful line here — *context engineering is the new prompt engineering* — that points at steps three and four from a different angle. His writing about self-documenting repos is the *what*. HydraFlow's RepoWikiLoop and ubiquitous-language extractor are one instance of the *how*."

**S29 · "The marketing layer hasn't caught up to the platform layer."** · *The line as the slide, large type* · "If you're a leader trying to figure out where to invest, the AI-coding-assistant *market* is still all step one — but the platform teams building those tools are already past step one internally. The durable leverage is upstairs, and it's already being built. It's just being built quietly."

**S30 · The SDLC frame stopped covering this** · *Two-column: "SDLC assumed..." (tickets, phases, sequential delivery, change boards) vs "...continuous mutation breaks it" (scenarios, iterating loops, probabilistic delivery, runtime governance)* · "The patterns sit in a space the old SDLC frame stopped covering. The size of that gap is most of why this work matters."

**S31 · Six things that break** · *6 bullets, animated in: Ticket boundaries weaken · Implementation phases blur · QA shifts left AND right · Architecture becomes runtime-governed · Documentation continuously synthesized · Delivery becomes probabilistic* · "Most of the strain I see in engineering orgs adopting AI comes from running V2V-shaped work through SDLC-shaped governance. Standups reporting ticket-by-ticket on work the agents decomposed into something else. Architecture reviews ratifying decisions the architecture tests already enforce. The vocabulary mismatch isn't cosmetic. It actively prevents the organization from seeing what its system is doing. The unit of work in this regime isn't ticket-to-code. It's intent-to-outcome. That's V2V's territory."

### Movement 7 — V2V teams + peers + scope + games (6 min)

**S32 · How V2V teams operate** · *Five specialty roles across the top: Scenario authors · Validation engineers · Context engineers · Autonomy designers · Operators. Below: small caption "Standups → fleet status · Reviews → validation upgrades · Architecture meetings → rare". Bottom strip: a gradient line from "Human-in-review" on the left to "Dark factory" on the right, with a marker showing where HydraFlow currently sits (far right).* · "What does a team of twelve do under V2V? The roles change more than the headcount. Five specialty roles around the staircase. Scenario authors own operating-condition libraries — highest-leverage role. Validation engineers garden the test pyramid. Context engineers make the system legible to itself. Autonomy designers own the doctrine. Operators watch the fleet. Workflow changes too: standups become fleet status, reviews become validation upgrades. The hardest part is what stops getting measured. If you've been following DORA for the last decade, you know the canonical four — deployment frequency, lead time, change failure rate, MTTR. Those aren't being replaced. They're getting a new layer above them: drift rate, recovery time, scenario coverage, validation-pyramid completeness, knowledge-bug count. The DORA four measure how fast and safely a system *runs*. The new metrics measure how coherent it stays as it *mutates itself*. There's also a gradient within V2V. Some teams keep humans in the PR-review loop for intent alignment. HydraFlow itself is further along — *I don't review individual PRs*. The system handles review through subagents; my role is pure workflow encoding. That's dark factory mode in practice. It's the direction the patterns push toward, not the only valid stop on the way."

**S33 · The field is converging, where peers placed their bet** · *Reuse S32's "Human-in-review to Dark factory" gradient, now populated with markers along it: Addy Osmani (human stays the verifier), Boris Cherny (human judgment gate on output), Steve Yegge (babysits the fleet), Peter Steinberger (ships on green tests, unread), HydraFlow (structural walls, no human in the routine loop, far right). Header strip: "June 2026: 'loop engineering' is now consensus, Steinberger / Cherny / Osmani."* · "S27 showed the field converging on the same operational shape. This is that same convergence read on one axis: how much human review stays inside the loop. As of this month the thesis is consensus. Steinberger and Cherny both say stop prompting and design loops that prompt your agents; Osmani named it *loop engineering*. Where we differ is what holds the line once human review leaves it. Steinberger ships on green tests without reading the code. Yegge built my kind of machine, Gas Town, twenty or thirty agents over a memory system, a fleet, and his answer is to babysit it. He literally retitled himself *AI babysitter* and gates it on staying vigilant. Mine is to move the watching into the structure so it doesn't lean on me staying sharp. Deliver this as peers, not foils: same machine, different bets on one question, what holds when the human steps back? Then hand off, every one of us is working where failure is *legible*, and that's the assumption the next slides break."

**S34 · This isn't for all software** · *Title on one half · "What HydraFlow does well: software-shaped work — observable failures, reversible commits" on the other* · "Be honest about what this is. HydraFlow does software-shaped work. Its outputs are commits, its failures are reversible, its successes are legible through traces and tests. That's a class of software, not all software."

**S35 · The next experiment — where can humans step out?** · *Large headline: "Is there a class of software where autonomous mutation + self-validation can sustain value with humans at governance boundaries?" Below: four supporting sub-questions in smaller type — caretaker for fun? · encode-corrections for aesthetics? · simulate players? · process under aesthetic iteration?* · "My next experiment isn't 'do the patterns generalize?' — it's tighter. Is there a class of software where autonomous mutation plus self-validation sustains value with humans mostly at governance boundaries? Not removing humans entirely — they can't be, and I'm not trying to. The question is whether there are domains where human time per unit of delivered value drops far enough to change the economics. Games are the proving ground, because they break every legibility assumption HydraFlow currently relies on. If the patterns hold there, you've crossed into a class of software that produces ongoing value with most of the human time pulled out of the mutation loop."

### Movement 8 — Containment + what breaks + where the engineer goes (5 min)

**S36 · Why it can't run away, containment by construction** · *Three nested rings (or three columns). **Per loop:** attempt budget · idempotent five-checkpoint contract · static-config kill switch · credit-aware yield. **Across loops:** label state machine (one owner per work item) · dedup · escalation · watcher loops (HealthMonitor, CostBudgetWatcher). **Hard walls, outside the code the factory may edit:** destructive ops blocked by hooks · cannot raise its own credit ceiling · cannot touch persisted state · everything reversible by construction.* · "A system that edits the system that runs it can, in principle, spin forever or cascade one loop's change through all the others. The answer is containment by construction, in three rings. Per loop: every loop has an attempt budget, an idempotent contract on the five-checkpoint wiring, a static-config kill switch, and it yields the moment credit is exhausted, so no single loop runs away. Across loops: the label state machine gives each work item exactly one owner, dedup stops loops re-triggering each other, and watcher loops escalate on cost and health, so a local change can't snowball into a storm. And the hard walls, which live outside the code the factory is allowed to edit: destructive operations are intercepted by hooks, it cannot raise its own credit ceiling, it cannot reach into persisted state. The point isn't that loops never misbehave. It's that misbehavior is bounded, reversible, and in-budget by construction. Which sets up the one failure that gets past all of this."

**S37 · What I expect to break next** · *Title at top. Four failure modes as a list: Drift from operator intent · Loop equilibria getting weird · Autonomy doctrine getting stale · Process bankruptcy* · "Quick honesty break. I've described what's working. I should be specific about what I'm watching for. Four failure modes I think are most likely, in roughly the order I expect them. Drift from operator intent — the system optimizing for legible validation while wandering from what I actually wanted. Loop equilibria getting weird — emergent bad equilibria as the count grows. Autonomy doctrine getting stale — gaps accumulating faster than I notice them. Process bankruptcy — the discipline rotting silently. None of these are reasons not to do this work. They're the next experiments. The shape of FLUID engineering is partly deciding which failure mode you're about to hit and building the infrastructure that catches it."

**S38 · The new mastery signals** · *Bulleted list: shaping constraints · designing validation systems · world-modeling · preserving coherence · recognizing taxonomic patterns · writing process discipline into the repo. Below, in smaller type, a day-in-the-life caption: "co-build loop with system · ADR · principles audit · subagent review · staging by morning · extend, don't review."* · "The strongest moments I have with HydraFlow aren't when I'm writing code. They're when I'm naming a domain crisply enough that the system uses the name back. Or noticing a third instance of the same kind of caretaker and codifying the category before the fourth one drifts. In concrete form: HydraFlow runs through the night. By morning I'm not reviewing what it did — I'm *extending* what it can do. We co-build new caretaker loops together. I write the ADR; principles audit reviews it; subagents do the implementation review; by morning the new loop is in staging. The new mastery isn't 'human writes code, AI helps,' or 'human reviews what AI generated.' It's *human encodes the conventions, the system manifests them, the conventions get sharper through use*. The craft is moving — but it isn't disappearing."

**S39 · "The two questions that tell me who to hire"** · *Single panel with both questions* ·
> *What does the system do when it disagrees with itself?*
> *How do you know the validation is actually validating?*

· "These are the questions a great engineer asks me when I describe what HydraFlow does. That engineer is going to be fine. The discipline they're pointing at is exactly the new mastery."

### Movement 9 — Close (1 min)

**S40 · The central shift** · *Two lines, top-and-bottom of slide, large type:*
> Old: "Can you build the system?"
> New: "Can you govern systems that continuously build and evolve themselves safely?"

· "I wrote FLUID fourteen months ago — March 2025 — to describe what code should look like when machines and humans co-author it. Running HydraFlow taught me the principles were necessary but not sufficient. The four patterns are the operating regime. They share one move — quality migrated from social to structural. They collapse into one principle — autonomy without validation is just accelerated entropy. And under all of them, the SOLID craft foundation held. The container is solid; the code inside it is fluid; the container is what makes fluidity safe. I don't review code anymore. The system does. I co-build with the system on intent and test — specs, conventions, scenarios — and the goal is dark factory mode. **And HydraFlow isn't a one-off. There's a handful of published cases now — Yegge's Gas Town (Jan 1), StrongDM's Attractor (Feb 7), HydraFlow (Feb 18), McKinney's factory (May 12) — with new aligned ones surfacing month over month, all arriving independently at the same operational rules from completely different architectures and domains. And the convergence-count number — three to five review passes — keeps appearing independently across them (Yegge cites Emanuel's Rule of Five, McKinney says four or five minimum, mine is three to five iterations). Independent designs. Different starting points. One operational shape, one convergence number. That's what tells me the patterns aren't mine, or theirs. They're what the work demands. The talk you've heard isn't a personal manifesto. It's a working instance of a pattern emerging across the field — at the intersection of where the people you trust on these topics are each pointing.** Most of what I've shown you isn't novel in pieces. What this talk has offered is a coherent integration — a working instance with its operational shape made legible. The contribution isn't being first. It's being whole. The next experiment is whether the same patterns let a game release and maintain itself — and whether dark factory mode survives a domain where the validation problem isn't legible. I'll let you know."

**S41 · Thank you + contact** · *hydraflow.ai, your handle, blog/talk link* · "Questions."

---

## Demo beats

**One demo, kept tight. Embedded as S8.**

- **Format:** 60–90 second pre-recorded screencap at 2–4× real-time. Do NOT do this live.
- **What it shows:** real autonomous PR cycle — issue filed → label change → branch created → PR opened with green checks → label transitions visible
- **Why pre-recorded:** live demos fail. The recording is the same evidence, with zero risk of demoware fragility eating your timing.
- **Where you stand during it:** silent, slightly stage right, hands off the clicker. Let the system be the protagonist.

**Backup options if you want a second demo:**

- *The Atlas knowledge graph view* (the recent merged feature, ADR-0059/0060) makes a compelling visual for the "operational knowledge graph" step of the staircase. 30 seconds, between S28 and S29.
- *MockWorld scenario running* — could be 20 seconds of a scenario test executing in seconds against a fake degraded API. Reinforces Pattern 3.

Resist the temptation to demo more than one thing. One demo lands; three demos blur.

---

## Q&A prep

The most likely high-leverage questions, with anchor answers:

**1. "Isn't MockWorld just integration testing with extra steps?"**

No. Integration tests assert input → output across a real-ish stack. MockWorld scenarios assert *behavior under operating conditions* — flaky deps, exhausted credits, ongoing escalations, budget caps. The unit is the world, not the call. You can compose scenarios. You can fuzz them. You can replay them. Integration tests can't carry that load.

**2. "How much does this cost to run?"**

Currently HydraFlow has a `CostBudgetWatcherLoop` enforcing daily caps per source. Spend is observable per-loop per-runner. The dashboard breaks out cost by attribution. We've spent more on getting validation/governance right than on inference itself.

**3. "What happens when it makes a really bad decision?"**

Three things. (a) The autonomy doctrine constrains what each agent is allowed to decide — high-blast-radius actions require human confirmation. (b) The kill-switch convention lets operators flip any loop off in one UI click without redeploy. (c) The two-tier branch model means agents can only land work on staging; promotion to main is a separate gated step. The combination means a bad decision is observable, contained, and reversible.

**4. "Will this work on legacy code?"**

Less well. The craft foundation matters. SOLID gives the system enough decomposability to mutate safely; legacy code without clean boundaries makes everything harder. The honest answer is: the same TDD/CI investment that makes legacy code merge-able by humans is the precondition for it being merge-able by agents.

**5. "Can you do this without GitHub?"**

The PRs-and-labels surface is load-bearing — labels are HydraFlow's state machine. You could swap GitHub for any system that exposes the equivalent primitives. But the labels-as-state-machine pattern (ADR-0002) is the conceptual core, not GitHub itself.

**6. "What's the most important thing you got wrong?"**

The first implementation underestimated how much load-bearing work would go into context engineering and ubiquitous language. I built validation infrastructure assuming the system would understand its own vocabulary. It didn't. The repo-wiki and ubiquitous-language loops came later, and in retrospect they should have been week-one work.

**7. "How do non-technical stakeholders engage with a V2V system?"**

By writing scenarios. The Given-When-Then form is the interface. Non-technical stakeholders are surprisingly good at it once they have examples — it's closer to acceptance criteria they already write. The discipline is to make scenarios authoritative: if it's not in a scenario, the system doesn't have to do it.

**8. "What's the elevator pitch difference between V2V and other agentic frameworks?"**

V2V isn't a framework — it's a methodology. Other tools target "AI codes faster." V2V targets "intent reliably becomes value through high-quality software the agents and the operator co-evolve." The patterns in HydraFlow are what makes that reliable rather than aspirational.

**9. "If quality went 'from social to structural,' aren't you just gatekeeping behind tooling?"**

The opposite. Social enforcement gatekeeps by who-knows-what — tribal knowledge, who's senior, who reviewed last. Structural enforcement is *legible*. Every rule is in the repo. Every check is reproducible. Every contract is inheritable by the next agent or human. The friction moves from "did the right person catch this?" to "did the system catch this?" — and the system is auditable in a way social review never was.

**10. "What's the actual ROI? When does the J-curve pay back?"**

I don't have a clean dollar number to share. Directionally: most of the early engineering went into the container (validation pyramid, MockWorld, ubiquitous-language extraction, autonomy doctrine, repo wiki). That investment didn't produce features in the first few months. After the container could carry load, each new feature shipped against compounding infrastructure — every scenario written, every conformance test added, every drift detector deployed lifts the floor for everything that follows. The crossover for me was somewhere around the third substantial feature. Your mileage depends on craft baseline and how aggressively you invest in the container up front.

**11. "How does this map to the Shapiro / Willison five-level framework? Isn't this just StrongDM?"**

Two parts. On the framework: HydraFlow operates at **Shapiro's Level 4** — autonomous spec-to-code, human reviews outcomes not process. Same level Shapiro places himself at. Willison's Level 5 markers from his January 28 post — *"no human code review, focus on testing/tooling, humans design systems enabling agent effectiveness"* — apply to HydraFlow. The cow-shed adaptation's stricter L5 marker — *held-out evaluation scenarios stored separately so the system can't optimize against them* — doesn't yet. That's on the next-experiment list, alongside games. And StrongDM is one of a handful of published L4/L5 examples; the list is growing month over month as more practitioners surface their work.

On StrongDM: I didn't know about their work when I started building HydraFlow. First commit was February 18, 2026 — 11 days after Willison's StrongDM piece dropped. We arrived at structurally similar patterns independently. **HydraFlow's MockWorld + Port↔Fake conformance is the same shape as their Digital Twin Universe + reference-SDK compatibility targets.** Subagent-driven review matches their "no human reviews code" rule. Where we differ: they're a team of three engineers; I'm solo. They have held-out scenarios; mine live in `tests/`. They enforce *"no human writes code"*; I co-build conventions and let the system implement against them. Architecturally: their Attractor is DOT-graph pipelines plus a programmable coding-agent library; HydraFlow is hex + BDD + caretaker loops. **Different execution, same operational shape — agents do the work, humans provide intent and test.** That parallel evolution — independent designs converging on the same operational shape without contact — is the strongest evidence I have that the patterns are intrinsic to the problem, not idiosyncratic to either of us.

**12. "How does this relate to DORA metrics / Agile / BDD / Hex heritage?"**

Continuity with that lineage, not replacement. To be very specific: *HydraFlow's core architecture is Hexagonal — Cockburn's pattern.* Every external dependency goes through a typed Port. BDD scenarios drive behavior at every port. That combination — hex + BDD — *is* the dark factory contract. The patterns I've described aren't novel architecture. They're Cockburn's hex and North's BDD run at autonomous-system scale. Similarly, DORA's four metrics still apply at the system-running layer; the new metrics (drift rate, recovery time, scenario coverage, knowledge-bug count) live above DORA and measure coherence under self-modification. The Agile Manifesto's emphasis on responding to change is *literally* what FLUID systems operationalize at machine scale. If your team has TDD/CI/BDD/DORA/hex muscle already, you have the substrate. The patterns are what you build on top of that craft, not in place of it.

**13. "Do you personally review every PR?"**

No. That's the whole point. The system reviews — subagent-driven spec-compliance checks, code-quality passes, fresh-eyes audits without conversation context, the validation pyramid, the convergence loops, the auto-discovery tests, the principles audit loop. My role isn't reviewing code. It's co-building with the system to encode the workflows — conventions, scenarios, autonomy doctrine, ADRs, standards — that make the system's own review trustworthy. The goal is dark factory mode: lights-off operation, operator paged only for raging fires. Reviewing code by hand would be doing the exact job the system was built to remove me from. That's not "AI did it"; it's "I projected my craft up a level — from reviewing instances to encoding the workflows that review instances."

---

## Talk Cuts — How to trim 51 min → 45 min

Apply these in order. Stop when you hit the time target.

### Don't cut these (load-bearing)

- **S12 (social→structural)** — unifying frame for the patterns
- **S13 (solid container, fluid contents)** — the asymmetry; the single most quotable visual in the talk
- **S26 (entropy quote card)** — t-shirt line; visual pause is the point
- **S32 (V2V teams)** — answers the "what does my team do?" question; biggest gap in the original deck
- **S36 (containment by construction)** — delivers the abstract's "preventing runaway loops and cascades" bullet; sets up S37
- **S37 (what breaks next)** — credibility moment; without it the talk reads as a sales pitch

### Cuts in order

1. **Backup demo (between S26–27 or post-S21)** — already not in the spine. Don't add it back under time pressure.
2. **S29 ("Most engineering leaders don't see…")** — the staircase slide itself carries the argument. The leader-framing line can be folded into the spoken text on S28.
3. **S25 (Pattern 4 third slide)** — fold "first time a bug, second a pattern, third a discipline" into the spoken text on S24.
4. **S27 (entropy quote card)** — fold the line into the spoken text at the start of S28 (staircase). Loses the visual pause but saves ~30 seconds. Only cut this if you're genuinely tight; the visual pause is what makes the line land.
5. **S16 (cross-cutting contract slide)** — speak the list off S15 instead of giving the contract its own slide.
6. **Reduce S35 (games) to a single question** — keep the headline hypothesis, drop the four supporting sub-questions. Keeps the forward arc, sheds bullets.

If you're really behind, you can also collapse Pattern 1 from 3 slides to 2 (merge S15 and S16). Don't collapse Pattern 3 — it's the bold claim that earns the talk a memorable line.

Two beats were added after the original spine: peers (S33, ~2 min) and containment (S36, ~1.5 min), so the full version is now ~55 min. Both overlap existing material, which is where you claw the time back. Containment overlaps S16, so cut #5 (fold S16 into S15) becomes mandatory rather than optional, ~1 min. Peers overlaps S27, the heaviest slide in the deck and now covered three times over (S33 on the review axis, S40 on field convergence), so trim S27 hard to its chronology plus the convergence-number kicker, ~2 min. Cuts 1–6 (~5 min, includes #5) plus the hard S27 trim (~2 min) bring ~55 down to ~48. Honest read: with both abstract-aligned beats in, 45 is tight, so plan for ~47–48 unless you also thin one pattern's spoken detail. Note S33 is news-pegged to June 2026, so for any later delivery it's the first cut. Treat S36 (containment), the validation slides, and S33 (trust calibration) as load-bearing, since they deliver the four bullets you sold, so cut convergence enumeration and pattern color before any of them.

---

## What NOT to do on stage

- **Don't open with the 19% slower stat.** That's the trap section, not the cold open. Opening with it tips your hand toward a "limitations of AI" talk, which this isn't.
- **Don't read the SDLC breakdown bullets verbatim.** Speak them with pauses. The audience needs time to flinch at each one.
- **Don't apologize for "vibe to value" being a soft-sounding name.** Own it. The defense is "it names the actual unit of work."
- **Don't take the bait if someone in Q&A wants to make this a debate about whether AI will replace engineers.** The talk's framing — *engineering value is migrating upward into governance of adaptive systems* — is your answer. Restate it once and move on.
- **Don't demo more than once.** One landing is a punctuation mark. Three landings is a slideshow.
- **Don't rush S26 (entropy quote card).** The line needs the silent pause. If you fill it with explanation, the line stops being a callback hook for the rest of the talk.
- **Don't soft-pedal S37 (what breaks next).** This is the credibility slide. Deliver it with conviction, not hedging. The audience will trust the rest of the talk more after you've admitted what you don't know.

---

## After the talk

When someone asks for follow-up materials, point them at:

- The blog post (this file's sibling).
- `hydraflow.ai` for the project.
- `docs/adr/` in the repo if they want to chase any specific ADR cited in a pattern.

Have a one-page handout with: the staircase, the four patterns, the seven beats, and the failure-mode list from S37. People who liked the talk will want to take that home; people who didn't like it still want to argue with you about it.

**On the handout, put the t-shirt line at the top:**

> *Autonomy without validation is just accelerated entropy.*

And put the asymmetry line right below it:

> *The container is solid. The code inside it is fluid. The container is what makes fluidity safe.*

Those are the two lines people will remember and quote. Make sure they take them home with the right wording.

---

## References / Sources

### Engaged directly in the talk

- **Adam Tornhill** — *Compressed Cognition: The Hidden Cost* — <https://adamtornhill.substack.com/p/compressed-cognition-the-hidden-cost> — engaged in §"The trap I almost fell into"; the 19%-slower / 24%-perceived-speed-gain study; decision-density mechanism.
- **Tori Huang** — *Claude Code: Do My Job Faster* — <https://bytorihuang.com/writing/2026/04/claude-code-do-my-job-faster/> — process-vs-knowledge bugs (Pattern 1); the encode-corrections loop (Pattern 2).
- **Adam Jacobs** — *Adaptive Building Blocks* — <https://www.adamhjk.com/blog/adaptive-building-blocks/> — adaptive primitives as the supply-side counterpart (§"Where engineering value moved").
- **Travis Frisinger** — *Mutable by Design: The FLUID Software Philosophy* — <https://aibuddy.software/mutable-by-design-the-fluid-software-philosophy/> — prior writing on FLUID.
- **Travis Frisinger** — *The Post-SOLID Era: When Code Becomes Fluid* — <https://aibuddy.software/the-post-solid-era-when-code-becomes-fluid/> — prior writing on the operational regime.

### The "Five Levels" / Dark Factory framework — attribution chain

The five-level framework is **Dan Shapiro's** (January 2026), modeled on NHTSA's vehicle-automation scale. Willison commented on it; Business Insider popularized it; cow-shed adapted it to audit/banking/legal. Cite Shapiro as the originator if you reference any level.

- **Dan Shapiro** — *The Five Levels: From Spicy Autocomplete to the Software Factory* (January 23, 2026) — <https://www.danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/> — **the originating framework.** L0 manual → L1 assisted tasks → L2 collaborative pairing → L3 human-in-loop manager → L4 autonomous spec-to-code → L5 *dark software factory* ("humans neither needed nor welcome," Fanuc reference). **Shapiro places himself at L4.** That's the same operational mode HydraFlow is in.
- **Simon Willison** — *The Five Levels* (January 28, 2026) — <https://simonwillison.net/2026/Jan/28/the-five-levels/> — commentary on Shapiro's framework. Adds an empirical observation: L5 teams have *"no human code review; focus on testing/tooling to prove system viability; humans design systems enabling agent effectiveness."* That third marker is structurally what you do.
- **Factory.ai** — <https://factory.ai/> — agent-native software development platform (Matan Grinberg, founded 2024). Positioning: *"Your software Factory powered by Droid."* CLI + desktop product. **The most commercially visible vendor using *software factory* terminology** — different category from the practitioner working-instance cases below (Gas Town, StrongDM, HydraFlow, McKinney), but a market signal that the framing is converging at the commercial layer. Predates the recent practitioner wave; been publicly visible since 2024. Useful evidence that "software factory" is going mainstream as terminology, not just inside HydraFlow's wiki.
- **Steve Yegge** — *Welcome to Gas Town* (January 1, 2026) — <https://steve-yegge.medium.com/welcome-to-gas-town-4f25ee16dd04> — **the earliest published working instance.** Go-based orchestrator managing 10–30 Claude Code instances in parallel via tmux, with Beads (his Git-backed issue tracker) as the state backbone. **Explicit "dark factory" framing** — confirms the term is converging in the language, not just yours. Role-based worker taxonomy — Mayor / Polecats / Refinery / Witness / Deacon / Dogs / Crew — Mad Max themed but structurally identical to HydraFlow's caretaker categories. **MEOW stack** (Beads / Epics / Molecules / Protomolecules / Formulas) is the declarative intent surface. **Nondeterministic Idempotence (NDI)** — workflows persist across agent crashes. Cites **Jeffrey Emanuel's "Rule of Five"** review-pass discipline — *a third independent source of the 3–5 / 4–5 / 5 convergence-count number* alongside HydraFlow and McKinney. Yegge frames Gas Town as the orchestration layer Claude Code and competitors are missing. **Predates StrongDM by ~5 weeks and HydraFlow by ~7 weeks.** Yegge's earlier piece *Revenge of the Junior Developer* (March 2025) predicted agent orchestration.
- **Simon Willison** — *How StrongDM's AI team build serious software without even looking at the code* (February 7, 2026) — <https://simonwillison.net/2026/Feb/7/software-factory/> — **the most relevant adjacent case.** Documents StrongDM's actual L5 implementation. Their rules: *"Code must not be written by humans. Code must not be reviewed by humans."* Their **Digital Twin Universe (DTU)** generates AI clones of third-party services (Okta, Jira, Slack) and uses reference SDK client libraries as compatibility targets — structurally the same pattern as HydraFlow's **MockWorld + Port↔Fake conformance.** Their scenarios are held out (external to codebase, probabilistic satisfaction) — the strict L5 marker. Team of three (McCarthy, Taylor, Chauhan, formed July 2025). Token cost reported at $1,000+ per engineer per day. **Independent convergence:** HydraFlow's first commit was February 18, 2026 — 11 days after this post, but you arrived at the structurally similar patterns without contact. That parallel evolution is stronger evidence than borrowed influence would be.
- **StrongDM** — *Attractor* (GitHub) — <https://github.com/strongdm/attractor> — **StrongDM's open-sourced intent surface.** Three NLSpecs (Natural Language Specs), no code: `attractor-spec.md` (DOT-graph pipeline runner), `coding-agent-loop-spec.md` (programmable coding-agent library, provider-aligned), `unified-llm-spec.md` (unified LLM client across providers). The README's instruction: *"Implement Attractor as described by https://github.com/strongdm/attractor"* — give that prompt to a coding agent and let it build the system. **This is what "humans provide intent" looks like as a published artifact.** Different shape from HydraFlow's intent surface (62+ ADRs + 240+ wiki entries + standards docs) but the same role. Architectural divergence: Attractor uses DOT-graph pipelines + programmable agent library; HydraFlow uses hex + BDD + caretaker loops. Convergent in purpose, different in execution.
- **Hugo Bowne-Anderson** *(with Wes McKinney, Jeremiah Lowin, Randy Olson)* — *Agentic Engineering and the Lost Art of Verification* (May 12, 2026) — <https://hugobowne.substack.com/p/agentic-engineering-and-the-lost> — **third independent convergence case.** McKinney (creator of pandas) describes his own software factory of parallel agents with a *RoboRev* background reviewer: *"I almost don't read code now... the mantra is: Roborev reads every line of code that is generated... the code has all been read by agents four or five times minimum."* **The four-to-five-passes detail matches HydraFlow's convergence-count data exactly.** McKinney doesn't reference Shapiro, Willison, or StrongDM — another independent arrival. **The pattern now has three published examples in addition to HydraFlow:** StrongDM/Attractor (DOT-graph pipelines + agent library), Wes McKinney's factory (parallel agents + RoboRev), and the broader practitioner community Bowne-Anderson is documenting. Different architectures, same operational rules: agents read the code, humans don't.
- **Simon Willison via Business Insider** — *Dark Factory AI* — <https://www.businessinsider.com/simon-willison-dark-factory-ai-2026-4> — popular-press coverage of the same framing; useful as a reference to gauge what the audience may have heard about "dark factory."
- **Cow-Shed** — *Dark Factories: Five Levels of AI Automation Transforming Audit, Banking, Legal* — <https://www.cow-shed.com/blog/dark-factories-five-levels-ai-automation-transform-audit-banking-legal> — **domain adaptation** of Shapiro's framework to regulated industries. Adds a stricter L5 marker: *"evaluation scenarios stored separately so the AI cannot optimise for passing them."* HydraFlow has analogous defenses (Port↔Fake conformance, fresh-eyes subagents, sandbox gating) but not the strict hidden-eval discipline. **Be ready for Q&A on this distinction.**

**Where HydraFlow lands on Shapiro's scale:**

- **Past Levels 0–3.** No human writes code, no human reviews each PR, the operator does not function as a reviewer.
- **At Level 4 (Shapiro's own location).** Co-build specs and conventions; system runs unattended; adjust in the morning if anything looks off.
- **Approaching Level 5 by Willison's markers** ("no human code review; humans design systems enabling agents") — these apply.
- **Below cow-shed's strict L5** — no hidden-evaluation discipline yet. That's on the next-experiment list, alongside games.

When you say "Dark Factory" in the talk, **you mean lights-off operations** (from manufacturing's lights-out factories and your own `dark-factory.md` doctrine — *"operator paged only for raging fires"*). That's distinct from Shapiro's strict L5 ("humans neither needed nor welcome"). Both senses of the term are in circulation. Be ready to bridge them in Q&A.

### Heritage references (continuity, not citation in narrow sense)

- **Alistair Cockburn** — *Hexagonal Architecture* (2005) — foundational ports-and-adapters pattern. **HydraFlow's core architecture.**
- **Dan North** — *Introducing BDD* (2006) — behavior-driven development; MockWorld's substrate.
- **Forsgren, Humble, Kim** — *Accelerate: The Science of Lean Software and DevOps* — the DORA research book. Source of the conference's name and the metrics the talk's "what stops getting measured" section extends.
- **Andrej Karpathy** — context engineering / self-documenting repos discussion — cited at staircase step 4 (operational knowledge graphs).
- **Jesse Vincent** — *Superpowers* framework — the workflow substrate for agentic engineering: brainstorming → spec → plan → TDD → sub-agent-driven implementation → fresh-eyes review. **HydraFlow's workflow runs on Superpowers.** Vincent's framing belongs on stage: *"The difference between vibe coding and agentic engineering is planning, architecture, and caring about the output."* The same workflow substrate Wes McKinney's factory uses — *shared substrate, independent operational architectures* (caretaker loops vs RoboRev + Agents View + Middleman + Kata). When citing convergence with McKinney, acknowledge this shared substrate; the convergence is at the operational layer, not the workflow layer.
- **Annegret Junker** — *AI as a Design Partner: Drafter, Validator, Provocateur* (codecentric, May 14, 2026) — <https://www.codecentric.de/en/knowledge-hub/blog/ai-as-a-design-partner-drafter-validator-provocateur> — names three roles AI plays in DDD-driven design. **Maps onto HydraFlow's caretaker taxonomy:** her Drafter ≈ our Proposers; her Validator ≈ our Auditors; her Provocateur ≈ our CorpusLearningLoop + SkillPromptEvalLoop + advisor pattern. The published-the-same-week (May 14) convergence on role-based decomposition keeps emerging. Quote on stage at S18: *"A wrong-but-specific draft is faster to evaluate, edit, or reject than a blank page."* Another convergent voice in the DDD lineage alongside Cockburn and North.

### HydraFlow ADRs cited in the talk

- ADR-0001 (five concurrent async loops) · ADR-0002 (label state machine) · ADR-0029 (caretaker loop pattern) · ADR-0032 (per-repo wiki knowledge base) · ADR-0042 (two-tier branch / release promotion) · ADR-0044 (HydraFlow principles) · ADR-0045 (trust architecture hardening) · ADR-0049 (kill-switch convention) · ADR-0050 (auto-agent HITL preflight) · ADR-0051 (iterative production readiness review) · ADR-0052 (sandbox tier scenarios) · ADR-0053 (ubiquitous language as living artifact) · ADR-0054 (term proposer loop) · ADR-0059/0060/0061/0062 (atlas knowledge graph + entry evidence)

### Project

- **HydraFlow** — <https://hydraflow.ai/>
- **Long-form companion essay** (this skeleton's sibling file): `docs/talks/2026-06-when-code-becomes-fluid.md`
- **Published short-form essay**: <https://aibuddy.software/p/d342f892-21e9-44f8-8ea0-ac5cf111286b/>
- **Talk venue:** Accelerate Chicago 2026 · June 22–24 · Convene Willis Tower, Chicago — <https://gotochgo.com/accelerate-chicago-2026>
