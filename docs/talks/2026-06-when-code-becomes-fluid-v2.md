<!-- v2 — rubber-stamping rebuttal integrated: agent review sharpens; executable validation + the walls carry safety; scoped to legible/reversible software, with games conceded as the open case. VERIFY BEFORE STAGE: the DORA two-stability-metrics claim (Accelerate / Forsgren-Humble-Kim) and the Bacchelli-Bird Microsoft code-review finding are now load-bearing citations. Also reconcile "twelve sandbox scenarios" against the real count. Also confirm the Boris Cherny quote ("I don't prompt Claude anymore...") against a citable source before delivery; wording supplied from memory, source not yet pinned. -->

# When Code Becomes FLUID, Where Does the Engineer Go?

*HydraFlow as a live test of the FLUID principles — and four patterns that emerged from running it.*

---

## Code was identity, then AI arrived

A lot of the anxiety around AI-assisted development is being framed as a debate about productivity, cognition, or code quality. Underneath it is something much more human.

For decades, code was not just implementation. Code was identity. It was how engineers demonstrated competence, mastery, creativity, rigor, control, value. The ability to manually transform complexity into working systems became the center of engineering culture. Entire careers, status hierarchies, and senses of self formed around that capability.

Then AI arrived and destabilized the relationship between effort and implementation. The industry is now struggling to understand what engineering becomes when code itself stops being the primary bottleneck.

The reflexive fear is that the answer means letting go — less rigor, less structure, less craft, a system you no longer control. I've spent the last few months building on the opposite bet: that you only earn the right to let code become fluid by making everything underneath it more solid. What follows is a report from inside that bet — built, not theorized.

## The autocomplete frame is keeping us stuck

Most organizations are still mentally operating in the first phase of AI adoption. AI as autocomplete. AI as acceleration. AI as pair programming. In this model the workflow still belongs to the human: the engineer defines the task, decomposes the work, prompts the model, validates the output, coordinates delivery, manages architecture, merges the code. The AI just produces implementation faster. That's why the conversations still revolve around coding speed, feature throughput, prompt quality.

That framing is already outdated. The real transition begins when systems stop merely generating code and start participating in software delivery itself — planning, decomposition, implementation, testing, evaluation, observability, retry, recovery, pull request creation, merge validation, operational feedback loops. Code generation is the least interesting part. At that point the question is no longer "Can AI help humans write software?" It becomes "How do humans safely govern software that continuously rewrites itself?"

<!-- VERIFY BEFORE STAGE: confirm Boris Cherny said this verbatim, with a citable source (talk/post), before delivering publicly. Attribution currently unsourced. -->
Boris Cherny, who built Claude Code, put the shift in its bluntest form: *"I don't prompt Claude anymore. I have loops that are running. They're the ones prompting Claude and figuring out what to do. My job is to write loops."*

He names the mechanism exactly right: the loops are the ones prompting Claude now. The word I'd push on is "anymore." Prompting didn't disappear, it moved, and it got compiled. I still prompt once, at the top, when I hand the factory an issue that states intent, and the loops turn that single prompt into the ten thousand they fire at Claude on my behalf. What went away is the turn-by-turn steering that used to be the job, the "no, do it this way," "now write the test," "rebase onto staging" that ate the day. Writing a loop is writing those prompts ahead of time, once, as reviewed and tested code instead of typing them live and discarding them. So "I write loops" isn't a smaller job than prompting was. It's prompting moved up a level and made durable.

That is a very different engineering discipline, and it has a counterintuitive shape. Pour code fast with nothing underneath it and you don't get agility — you get a flood. The horror stories everyone cites, the leaked keys, the runaway bills, the database an agent drops because it misread the task, are all the same failure: fluid with no vessel to hold it. The lesson I keep relearning is the inverse of the fear. Fluidity isn't the absence of structure. It's what you get when the structure moves out of the code and becomes the container the code runs inside — and the more solid that container, the more recklessly fluid you can afford to be on top of it. How loose the code gets to be is set, precisely, by how sound the thing beneath it is.

## FLUID, written in March 2025 — and what was missing

In March 2025 I wrote down a set of principles I called FLUID. Flexible composition. Live prototypes. Unified context. Intent-driven structure. Dynamic refactorability. The argument was simple: SOLID was a design philosophy optimized for the era when humans wrote every line, when change was expensive, when the goal of structure was to protect a fragile human-only system from itself. AI-native development inverts those economics. Implementation becomes cheap. Code becomes mutable, disposable, co-authored. The new principles need to optimize for collaboration with machines, not protection from change.

FLUID's timing matters here. I wrote it about ten months before the named-framework wave for AI-era engineering formed — Shapiro's five-level (January 23, 2026), Yegge's Gas Town (January 1, 2026), Willison's documentation of StrongDM's L5 implementation (February 7, 2026), Junker's three-role framework (May 14, 2026). At the time, Karpathy had just coined *"vibe coding"* as a term; Yegge published *Revenge of the Junior Developer* the same month as FLUID — predictions, not frameworks. The thinking was in the air, in a small cohort. FLUID was the earliest *named alternative to SOLID* for the AI era — not commentary on AI coding, but a structured framework with axes you could argue, extend, or build against.

That was the philosophy. It turned out to be directionally right, but incomplete. FLUID described the fluid half — how the code should be created. It said nothing about the container that has to hold it: what engineering looks like once the code itself stops being the stable artifact. That missing half is what running HydraFlow taught me.

FLUID sat as philosophy for nearly a year. The trigger to actually build came from Steve Yegge — January 1, 2026, his post *"Welcome to Gas Town,"* showing a working orchestrator for parallel coding agents. Reading it, I thought: *I've been doing this nearly as long. Philosophy be damned. I can build one too.*

So I built HydraFlow, starting February 18, 2026 — seven weeks after Gas Town gave me the permission.

Months, not years.

HydraFlow is a multi-agent orchestration system — think Dark Factory — that treats software delivery itself as a programmable surface. You file a GitHub issue. Agents plan the work, implement changes, validate outcomes, and merge pull requests. **Humans provide intent and test.** That's it. The intent surface is specs, ADRs, conventions, the autonomy doctrine. The test surface is scenarios — Given-When-Then operating conditions the system has to honor. Everything between those two human surfaces — implementation, review, merge, recovery, observability — is the system's responsibility, not mine.

There's a methodology underneath this I've been calling **Vibe to Value (V2V)**: outcomes from intent via high-quality AI-assisted software built with what I've taken to calling *robots* — agents, loops, caretakers, the lot. FLUID describes the code shape. V2V is the methodology. HydraFlow is the operational system embodying both. The talk you're reading is, in one sense, a status report on V2V: here's what trying to operationalize it taught me about engineering in this regime.

V2V sits inside a broader tradition Jesse Vincent has been naming **agentic engineering**, and his framing belongs on the record because it's the cleanest articulation of the distinction I've heard:

> *The difference between vibe coding and agentic engineering is planning, architecture, and caring about the output.* — Jesse Vincent

His Superpowers framework — the brainstorming, spec, plan, TDD, sub-agent-driven implementation, and fresh-eyes review patterns I rely on daily — is the workflow substrate HydraFlow runs on. V2V is what agentic engineering looks like at autonomous-system scale. HydraFlow is one working instance of it.

First commit: February 18, 2026.

The interesting thing didn't happen at the demo stage. It happened within days of HydraFlow becoming functional: it started modifying its own codebase. Since then it has run hundreds of autonomous PR cycles against itself and a handful of foreign repos, with fifteen caretaker loops running in production.

I want to be precise about what those cycles are. Most are small — dependency bumps, ADR touchpoints, term proposals, regeneration passes, the bot-shape work that fills a real engineering org's queue. Substantial feature work goes through the system's own multi-pass review — subagent-driven spec-compliance checks, code-quality reviews, fresh-eyes audits without conversation context — typically three to five iterations. Those passes sharpen the artifact. What actually *authorizes* the merge is the executable barrier underneath them: the full `make quality` suite and the twelve sandbox scenarios, which pass or fail by execution no matter which agent wrote or read the code. Review converges the work toward the gates; the gates decide whether it lands.

*I don't review code.* The system does — but the system's review is not what I'm trusting, and that distinction is the whole argument of this piece. My role is to encode the two things that actually earn the trust: the executable validation that passes or fails by running, regardless of which model wrote or reviewed the code, and the walls that make a wrong merge cheap to undo. The conventions, the scenarios, the autonomy doctrine, the ADRs, the standards docs every agent reads on the way in are how I encode them. The system's own review passes sharpen the artifact toward those gates; they don't authorize the merge. The gates and the walls do. The goal HydraFlow is built toward is **dark factory mode**: lights-off operation, with the operator paged only for raging fires. The patterns in this talk are what makes dark factory mode survivable. They're also why my time goes into workflow encoding rather than line-by-line review — *that's the projection up a level* the rest of this piece is about.

In practice right now: we co-build new conventions and loops together, the system runs through the night, I adjust in the morning if anything looks off. The core has bedded down — stable enough that my time goes into *extending* the factory with new operational primitives rather than rebuilding it. Recent threads of work have been operationalizing more concepts as living artifacts — pushing wikis and DDD ubiquitous language past static documentation into runtime objects the system maintains. That's where the curiosity lives now: how far can you push *concepts as runtime objects* before something breaks?

What it surfaced was a new class of engineering problem — not in the FLUID principles, but in the *operational regime* FLUID creates. The principles tell you how to write the code. They don't tell you how to keep a self-modifying system coherent, how to validate work no human authored, or how to know when to let the system act vs ask.

The rest of this post is what those problems looked like up close, and the operating patterns I had to invent in the gap between the philosophy and the running system.

## The trap I almost fell into — "compressed cognition" misses it

A common framing for the discomfort of AI-assisted work is *compressed cognition*. Adam Tornhill makes this argument well: agents collapse the natural pacing of manual coding — the debug cycles, the waits, the syntax checks — and force engineers to sustain meaningful decision-making at a density working memory can't hold. There's a study where developers using AI tools *felt* 20% faster but were measurably 19% *slower*. The mechanism is sound. Decision density really does outrun the human cognitive budget.

But operating HydraFlow taught me that compressed cognition, by itself, isn't the whole problem. It's the human-side symptom of a deeper systemic shift.

The deeper risk isn't that *I* think less. It's that the *system* evolves faster than understanding. Two different scales.

At the human scale: agents remove natural pauses, decision density rises, individual judgment fatigues. Real.

At the system scale: agents touch files I haven't seen in weeks, in a vocabulary I might not have written, against constraints I might not remember. Comprehension debt accumulates not because I'm tired but because the artifact is changing faster than any human-maintained mental model can track.

The pauses Tornhill identifies as missing aren't just rest periods. They're the windows where understanding gets compiled — the place where local changes congeal into a working mental model. Remove the pauses at the *system* scale, not just the human scale, and what erodes isn't velocity. It's coherence.

That distinction matters because the fix is different. Human-scale compressed cognition is addressed by ergonomic workflow design — pacing, batching, recovery breaks. System-scale comprehension debt is addressed by building the comprehension into the system itself, so it doesn't depend on a human holding it in their head.

That's where the patterns come from.

## The craft foundation that made this possible

A note before I get to the patterns: this experiment was only runnable because of the craft I inherited.

I keep meeting people who treat AI-assisted engineering as a break from prior practice. As if TDD, BDD, SOLID, CI are relics that AI makes obsolete. The opposite turned out to be true. Without that substrate, HydraFlow would have collapsed in week two.

TDD gave every change a regression test. Every agent-generated PR has to pass tests authored by a human who thought about what should never break. The discipline meant the test suite became the spec — the same spec the agents read when generating implementation. SOLID gave the system enough structural integrity that mutations don't cascade. When an agent refactors one collaborator, the boundaries hold. CI is what catches the gaps. Pre-commit hooks make the gates fast — agents wait for ruff, pyright, security scan before they can even commit. BDD turned out to be the entire MockWorld substrate; scenarios are the cognitive frame for autonomous behavior, and I'll come back to that.

These practices aren't dead. They're the load-bearing substrate underneath what HydraFlow appears to do. The talk you're about to read is "lessons from a self-modifying system." But the experiment was only runnable because forty years of accumulated engineering practice gave me a foundation safe enough to mutate from.

The craft also gave me a search shape. When the system did something I'd never seen before, I had a habit of asking: *what existing practice does this break, and what existing practice does it amplify?* Not "what new practice does AI need?" Just: *where in the body of craft does this experience belong?* That habit is most of what kept me oriented while the artifact under me was changing daily.

Engineering practices evolve. Some die. Some age into substrate. The craft is knowing which is which — and that knowing is itself a practice. Most of what follows is patterns that emerged when I asked old questions in this new regime.

## Quality went from social to structural

There's a sharper way to read what the craft foundation became — and it took me a while to see it.

In traditional engineering, quality enforcement was largely *social*. Senior reviewers held the line. Tribal knowledge carried the conventions. Manual process discipline kept the system coherent. Quality lived in humans, applied through review and rework.

In a system that mutates daily, social enforcement doesn't scale. There aren't enough senior reviewers. Tribal knowledge can't keep pace with the change. Manual discipline misses the third instance of a pattern before it's been codified.

What HydraFlow does isn't lower the quality bar. It moves the bar *into the system itself*:

- Validation became continuous.
- Governance became executable.
- Process became encoded.
- Regression protection became systemic.
- Scenarios became authoritative.
- Recovery became automated.
- Semantic drift became detectable.

That's the underlying move. **Quality enforcement migrated from social to structural.** The four patterns you're about to read are all instances of it. Caretaker taxonomy is social oversight made structural. Validation as engine is the executable safety net made structural and self-sharpening — the part of the old review process that actually caught defects, turned into running code rather than a meeting. MockWorld is social knowledge of edge cases made structural and composable. Process as deliverable is social discipline made structural and inheritable.

If you hear *FLUID* and think *lower quality standards*, you've got it exactly backwards. FLUID systems only work because quality enforcement migrated up a level. The substrate didn't get lighter. It got encoded.

This is also why most of the *AI code is garbage* discourse misses what's actually happening. That critique measures **generation quality** — was the first draft elegant? The patterns measure something else entirely: **convergence quality under governed mutation** — does the operating system reliably push artifacts toward correctness over three to five iterations of validation? And to be exact about what "validation" means there: each iteration re-runs the deterministic gates — the test suite, the type checker, the scenarios, the quality bar — not a reviewer's approval. The agent passes propose corrections; the gates, which can't be charmed by a plausible diff, decide whether convergence actually happened. Those are different questions. The first is mostly irrelevant if the second works.

Quality-going-structural isn't free. Most of HydraFlow's engineering effort, in the early months, went into the structural container itself — the validation pyramid, MockWorld, the ubiquitous-language extractor, the autonomy doctrine, the repo-wiki regeneration. The factory output didn't start paying back until the container could carry it. There's a J-curve here that's worth naming: adopting V2V looks slower than not adopting it for some number of weeks or months, because you're investing in infrastructure that doesn't produce features yet. The crossover comes when the infrastructure starts compounding — each new feature ships against the validation layer the previous features built, against the scenarios the previous features authored, against the context the previous features encoded. Before crossover, the marginal feature is more expensive. After crossover, it's significantly cheaper than it would have been in the SOLID-only regime. The question for anyone weighing this work isn't "is it worth it?" The question is "how much runway do I have to ride the J-curve, and what's the minimum infrastructure investment that crosses over fastest?"

And this is what FLUID actually requires from SOLID — why the two aren't opposed. SOLID foundations don't disappear in a FLUID regime. They migrate. The properties SOLID describes — well-bounded components, single responsibilities, open-closed boundaries, dependency inversion, interface segregation — stop being properties of *the code itself* and become properties of the *container around the code*. TDD, BDD, SOLID design discipline, CI — all the cheap, accessible engineering practices we've spent forty years getting good at — are the substrate that makes the structural container possible. **The container is solid. The code inside the container is fluid. The container is what makes fluidity safe.** And the container is two concrete things, not an abstraction: executable validation that passes or fails by running — immune to a persuasive diff because it never reads one — and a walled blast radius where being wrong is cheap to undo. Notice what isn't on that list: a reviewer, human or agent, reading the code and judging it. The container's safety has never lived there.

Said another way: code becomes fluid *because* the operational system around it became more SOLID, not less. The fluidity is the consequence of a sturdier container, not the absence of structure. If you try to build a FLUID system without the SOLID container — without rigorous testing, without continuous integration, without disciplined boundaries — you don't get fluidity. You get chaos. Your craft as a SOLID-era engineer is more valuable now, not less. It's just operating on a different layer. You're not unlearning the craft. You're projecting it up a level.

To be specific about what that container actually *is*: **HydraFlow's core architecture is Hexagonal — Alistair Cockburn's pattern from 2005. Every external dependency goes through a typed Port. Every Port has a Fake adapter the conformance tests keep in sync with the real one. BDD scenarios drive behavior at the port boundary.** That combination — hex architecture with BDD-defined contracts at every port — *is* the dark factory contract. It's what makes MockWorld possible (you swap the adapter, not the code). It's what makes the validation pyramid layered (unit inside the hex, MockWorld at the port boundary, sandbox crossing the whole stack). It's what makes substantial features replaceable without cascading damage (the Port contract is stable; what's behind it can mutate). None of this is new architecture. It's *Cockburn's* hex plus *North's* BDD, run at autonomous-system scale.

---

## Four patterns that emerged

What follows is one pattern per dimension of the FLUID operating regime that HydraFlow forced into focus. None of these were in the original FLUID principles. All of them sit in the gap between writing code that can mutate and running a *system* that mutates.

### Pattern 1: Caretaker loops form a taxonomy

HydraFlow currently runs fifteen caretaker loops. I designed the first two up front. The other thirteen accreted, one at a time, each in response to a recurring operational concern I noticed across multiple incidents. Two decades of engineering practice clearly shaped *which* loops I built — but the *categories* weren't in my original sketch. They emerged. Looking at the set now, the categories almost name themselves.

- **Maintainers** keep system-internal state fresh against drift. `RepoWikiLoop` rewrites the wiki from live events. `DiagramLoop` regenerates architecture artifacts every four hours. `GitHubCacheLoop` keeps the local cache aligned with upstream. `PricingRefreshLoop` pulls LiteLLM pricing nightly. These run quietly. You only notice them when they stop.
- **Proposers** grow new state from observation. `TermProposerLoop` auto-extracts vocabulary from code and ADRs and opens a bot PR proposing new glossary entries. `EdgeProposerLoop` proposes relationships between terms. `EntryEvidenceLoop` proposes backlinks between terms and wiki entries. Each is auto-merging unless a human objects. Proposers grow the system; they don't replace it.
- **Pruners** remove stale state. `TermPrunerLoop` deprecates vocabulary nobody refers to anymore. There's a symmetry with proposers — if growth has no compensating shrinkage, the system bloats.
- **Auditors** verify invariants. `PrinciplesAuditLoop` checks the codebase against ADR-0044 principles on a weekly tick. `AdrTouchpointAuditorLoop` checks that PRs touching ADR-relevant surfaces actually update or reference the ADR. Auditors don't fix anything. They surface drift.
- **Repairers** fix when broken. `SandboxFailureFixerLoop` dispatches when nightly sandbox scenarios fail and gets up to three auto-agent attempts before escalating. `AutoAgentPreflightLoop` intercepts `hitl-escalation` issues and attempts autonomous resolution before a human sees them. Repairers are the system's first responders.
- **Watchers** escalate or budget. `HealthMonitorLoop` watches loop liveness. `CostBudgetWatcherLoop` watches daily spend against caps. Watchers don't act — they signal.
- **Promoters** move state through tiers. `StagingPromotionLoop` cuts an auto-promoted `rc/YYYY-MM-DD-HHMM` PR from staging to main every four hours, gated by all twelve sandbox scenarios passing. The promoter is the only loop with authority to move work past the validation barrier.
- **Provocateurs** challenge the system's own assumptions. `CorpusLearningLoop` reads `skill-escape` issues — moments where a skill failed or was bypassed — and synthesizes adversarial corpus cases that test the system against its own past failures. `SkillPromptEvalLoop` runs that adversarial corpus weekly against the built-in skills. The advisor pattern (PreFlightAdvisor + post-verify advisors wired into PR review, ADR review, and the visual gate) plays the same role at decision points. Provocateurs are the loops that ask *"where would the system break if we pushed harder?"* and then push there. They're what keeps the validation engine honest — the same way fresh-eyes subagent review keeps implementation review honest at the per-PR level.

Eight categories from the working fleet. None of them were in my original sketch. Each emerged as I noticed I was building another instance of a kind I'd seen before. Now that the categories are visible, new loops slot into them naturally. A drift problem? That's a maintainer or an auditor. A growth problem? Proposer plus pruner. An escalation gap? Watcher or repairer.

The cross-cutting concerns are universal across the taxonomy. Every loop has an ADR-0049 in-body kill-switch at the top of `_do_work`. Every loop has a static config gate for deploy-time disable. Every loop propagates `CreditExhaustedError` past the generic retry. Every loop's wiring touches the same five checkpoints (config + service registry + orchestrator + UI constants + scenario catalog), enforced by an auto-discovery test that fails if any are missed. These aren't per-category disciplines. They're the operating contract.

**The operating principle this taught me:** *In a FLUID system, the durable architecture isn't the application — it's the loop taxonomy and the cross-cutting contract every loop honors.* The application code regenerates. The loop categories don't. You don't design them up front; you let them emerge, then make them legible enough that the next instance slots into the taxonomy rather than re-inventing it.

This is also the answer to "what does engineering look like when the code mutates daily?" You shift from designing components to *recognizing taxonomic patterns* as the system runs, then codifying them into structural enforcement so the next agent that adds a loop gets the discipline by default.

There's a deeper consequence of this taxonomy I want to surface, because it's the strongest answer I have to one of the loudest critiques of AI-assisted engineering. Three of the categories — Maintainers, Proposers, Pruners — are doing something traditional software engineering never quite managed at scale: *keeping conceptual artifacts alive without human maintenance.* Wikis, glossaries, ADR cross-references, ubiquitous-language extractions, knowledge graphs — in traditional engineering these decay the moment they're written, because humans manually update them and humans don't. The result is documentation that's stale within months. **Static slop.**

There's a critique of AI-assisted engineering that says it generates "slop" — sloppy code, hallucinated functions, dead documentation. That critique misses where slop actually comes from. Slop comes from static artifacts humans can't keep current at the rate the code mutates. In a HydraFlow-class system, the wiki regenerates from live events. The glossary auto-extracts from code, ADRs, and PRs. The drift detector breaks the build when names diverge. The ADR cross-reference is regenerated every PR. These aren't sloppy. They're the *opposite* of slop — **living artifacts**, maintained by the system itself, kept current at the rate the code changes. That's the conceptual layer of the system becoming as runtime as the code is. It's also where most of my exploratory work goes now that the core has bedded down: pushing more concepts — DDD ubiquitous language, architectural intent, scenario libraries — into the living-artifact category.

### Pattern 2: Validation became an engine

In a SOLID world, validation is a gate. Something runs after a developer thinks they're done. It says yes or no. The developer fixes things, runs it again. Yes or no.

In HydraFlow, validation stopped behaving like that within months. What it became, instead, is an *engine* — an active force that pushes the system into shapes it wouldn't have taken otherwise.

The clearest example: PR #8460, May 2nd 2026, 21:43 UTC. A code-cleanup pass that removed redundant `getattr(self, "_X", None)` defensiveness at sites where the attribute is unconditionally set in `__init__`. Seven sites, four files. Two hundred and eleven unit tests passed. Pyright clean. Ruff clean. Merged.

Forty-two minutes later, main was red.

Seven tests broken in two files the implementer hadn't run. The cleanup was correct for production code paths. What it missed was test scaffolding that bypasses `__init__` via `cls.__new__(cls)` and only sets a curated subset of attrs. The defensive `getattr` had been silently absorbing that. PR #8463, the hotfix, landed 42 minutes after the original.

Read that incident as a validation failure and you miss the point. The validation worked exactly as designed — `make quality` ran the full suite, surfaced the regression, the system noticed within an hour, the hotfix landed. And read it as a *review* failure and you miss the bigger one. The review passes were clean: pyright clean, ruff clean, two hundred and eleven tests green, merged. If review were the safety mechanism, the bug ships and stays. It didn't, because review was never the safety mechanism here. The deterministic suite caught what review couldn't see, and a cheap revert bounded the cost to forty-two minutes of red `main`. That is both halves of the real safety story in one incident: validation catches what review misses, and reversibility makes the miss survivable. The validation didn't gate the wrong code out. The validation *exposed a class of usage* (test scaffolding bypassing `__init__`) that the cleanup hadn't accounted for. The cleanup became *more correct* because validation pushed it there.

That's the engine. Each correction encodes back. The conformance tests in `tests/scenarios/fakes/test_port_conformance.py` exist because at some point a fake drifted from a real port and an `AsyncMock(pr).remove_labels(...)` typo passed in test and crashed in production. The drift detection between term anchors and code (ADR-0053) exists because at some point a name in the wiki diverged from the name in the source. The architecture tests that fail on stale generated docs exist because at some point someone merged a feature without `make arch-regen`. None of these were designed up front. Each was added in response to a class of bug surfacing, and each became permanent infrastructure that lifts the entire system's floor.

This is the encode-corrections loop Tori Huang names. Every correction becomes part of the validation. The system gets sharper at catching the class of bug you just got bit by, automatically, the next time. Validation isn't a brake. It's a sharpener.

Annegret Junker captures the same dynamic from a different angle, writing about DDD-driven design with agents: *"A wrong-but-specific draft is faster to evaluate, edit, or reject than a blank page."* The agent's first pass doesn't have to be right. It has to be *specific enough* that the validation layer can push it toward right. And what does the pushing is an execution, not a second opinion — a test, a type check, a scenario, a quality gate that runs the same way whoever wrote it. That's the part the "agents just agree with each other" worry misses: two models can share a taste-level blind spot and still both fail the same red test, because the test doesn't consult their taste. Determinism is the firewall against correlated judgment. That's why the convergence count exists at all — three to five iterations isn't waste, it's the shape of how rightness emerges when wrongness is fast and cheap.

The convergence-loop data is the empirical signal. Trust-fleet (PR #8390): five iterations of the validate-correct loop — each pass re-runs the deterministic gates and encodes the corrections back — before the next pass found nothing material. Auto-Agent wiring (PR #8439): three. These aren't rounds of one agent approving another; they're rounds of an artifact getting re-tested against an executable bar until the bar stops moving. Substantial features converge in three-to-five of those iterations — all run by the system, none by me. One honest caveat on the number: a stable stopping point tells you the loop *converged*, not that it converged on *correct*. What tells you that is the gates themselves and the post-merge escape rate — does the converged artifact fail less in the sandbox and nightly than an unconverged one? The count is the necessary signal, not the sufficient one. That isn't waste — that's where the design actually happens. The first implementation is a probe. Validation pushes it into shape. Convergence is the design completing itself, and the operator is free to be elsewhere while it converges.

This is also why FLUID's "deferred rigor" works in practice rather than just on paper. Rigor isn't skipped — it's relocated. It happens at validation time, on running code, against real conditions, instead of at write time against an imagined future. The convergence loop is what that relocation looks like operationally.

**The operating principle this taught me:** *In a FLUID system, validation isn't a check on design — validation IS the design process. Keep two roles separate inside that loop: the agent review passes sharpen the artifact toward correctness; the deterministic gates — tests, types, scenarios, quality bar — decide whether it is allowed to land. Sharpening is a correctness job. Deciding is the safety job. Conflate them and you have reinvented the thing people call rubber-stamping. Each iteration sharpens the artifact toward what the system actually needs. The discipline isn't writing more tests; it's letting each correction encode back into infrastructure that lifts the floor for everything that follows.*

### Pattern 3: MockWorld is BDD as environment substitution

The three-layer test pyramid HydraFlow ships against looks like this. Unit tests at the bottom: pure functions, mocks everywhere, runs in milliseconds. Sandbox e2e at the top: the full orchestrator booted inside docker-compose, Playwright driving the UI, runs in minutes. In the middle, a layer called MockWorld: real loop code, fake adapters at the I/O boundary, runs in seconds.

MockWorld is the most novel piece. It's also the one that took me longest to understand what it actually was.

Traditional mocks simulate *responses*. When the code calls `pr.merge()`, the mock returns a `MergeResult`. Input goes in, output comes out. The mock is a stub for one call.

MockWorld simulates *conditions*. When the code calls into `world.github`, it gets a `FakeGitHub` that holds a coherent model of the world — repos, issues, PRs, labels, state machines, CI runs, branches, ref updates. The fake remembers what happened. The next call sees the consequences of the previous call. The world has *state*. The world has *time*. The world has *failure modes*. You can tell the world to be flaky. You can tell the world that auth is degraded. You can tell the world that the CI failed on a specific scenario. The world holds all of that, coherently, across the lifetime of a scenario.

That isn't mocking. That's BDD.

Behavior-driven development's premise is that scenarios are the unit of behavior specification. Given a condition, when an action happens, then an outcome should follow. The scenario *describes the operating reality*, not just an input-output pair. BDD treats the world as something you set up and observe through.

MockWorld is what BDD looks like when you push it all the way. The "Given" expands to include the entire operating environment the autonomous system runs inside. Given the API is degraded. Given the auth provider is flaky. Given the CI scenario `s07_promotion_gate` is currently failing. Given the operator has a $50 daily budget. Given there's an unresolved `hitl-escalation` from three hours ago. When the orchestrator ticks. Then the system should... whatever it should.

The implication is bigger than the test infrastructure. Unit tests can't capture *"the loop behaves correctly when credit is exhausted and the operator is asleep."* The conditions don't fit in a function-call boundary. Sandbox e2e can capture it, but at three minutes per scenario you can't iterate on the spec — sandbox is final validation, not a design space. MockWorld is the middle layer that makes the impossible scenarios tractable. It runs in seconds. You can write hundreds. You can compose them. You can fuzz them. You can replay them.

The deeper move is that MockWorld lets you *replace environments*. For a long time the answer to "how do we test what happens in production?" was "spin up a staging environment." Staging is expensive, slow, and never quite real. MockWorld inverts the question: *what if the environment is itself a programmable object you compose in code?* Then "production-like" stops being a place and starts being a configuration. You don't need a server farm to test against degraded environments. You need a fake that knows how to *be* a degraded environment.

That's what BDD becomes when you apply it at the system level rather than the user-flow level. Given-when-then was always pointing at the world. MockWorld just makes that explicit by making the world programmable.

This works structurally because the core architecture is Hexagonal — Cockburn's pattern. External dependencies all go through typed Ports. MockWorld swaps fake adapters at the port boundary while the system code inside the hexagon runs unchanged. The Port↔Fake conformance tests are what keep them honest. That's why MockWorld can simulate degraded APIs, exhausted credits, ongoing escalations — the I/O boundary is *programmable* because hex made it so. BDD scenarios then drive behavior at each port: *Given* this Port returns a credit-exhausted error, *when* the loop ticks, *then* the system should yield its attempt budget. The whole machine is two well-known patterns composed.

**The operating principle this taught me:** *In a FLUID system, the right unit of test is the operating scenario, not the function call. MockWorld is what BDD looks like when you push it past user flows into world-modeling. Environments stop being places you provision and become objects you compose.*

This is, incidentally, the cleanest example I have of a FLUID-era practice that absorbs and extends SOLID-era patterns rather than replacing them. Cockburn's ports are what makes the adapter swap work at all. North's *Given-When-Then* is what describes what should happen at each port. Together they form **the dark factory contract** — the typed, behavior-defined surface that makes autonomous mutation safe. It's continuity with twenty-plus years of behavior-driven and architectural thinking, not a replacement. It just took autonomous systems to make these patterns urgent.

### Pattern 4: The process became the deliverable

Here is the pattern I find hardest to articulate, and the one that turned out to matter most.

What HydraFlow runs on, fundamentally, isn't its code. The code regenerates. The architecture mutates. The agents change models. Model versions roll over every few months. What persists, what lets the experiment keep running across all of that, is the *process discipline* — the steps by which mutations happen and the conditions under which they're allowed to land.

The process looks like this. Brainstorming when an idea is still ambiguous. Spec when the idea is clear but the implementation isn't. Plan when the implementation needs to fit a sequence of safe steps. TDD execution — red, green, refactor — for every step. Per-task review during implementation by a subagent that doesn't see the conversation context. *Subagent-driven* fresh-eyes review iterations after implementation; plan for three passes; expect convergence around the third. The human isn't in any of these loops as the reviewer — the human is in them as the workflow encoder, the one who wrote the conventions the subagents review *against*. `make quality` as the smoke test, not file-targeted subsets. `make arch-regen` to keep generated artifacts current. Merge to staging. Auto-promotion to main via a four-hour-cadence RC PR gated by twelve sandbox scenarios.

That's the process. Every step has a checklist. Every checklist has a discoverability surface — `CLAUDE.md`, `docs/wiki/`, `docs/standards/`. Every discoverability surface is read by every agent that touches the repo. The process isn't in a slide deck. It's in the repo. Agents inherit it by reading.

The same is true at the loop level. Every new caretaker loop has to touch five wiring checkpoints — `config.py`, `service_registry.py`, `orchestrator.py`, `src/ui/src/constants.js`, `tests/scenarios/catalog/loop_registrations.py`. An auto-discovery test fails if any are missed. A scaffold script generates the boilerplate with all five checkpoints correct. The process isn't a guideline. It's structural enforcement.

Same for trust. The factory autonomy doctrine is a typed permission table: tractable + reversible (act and report), high blast radius (confirm first), authorial/scope (brainstorm → spec → plan). Same for ADRs: every architectural decision is numbered, indexed, versioned, and cross-referenced from generated docs. Same for the kill-switch convention: every loop, no exceptions. Same for credit propagation: every subprocess runner calls `reraise_on_credit_or_bug`. Same for subagent verification: every DONE claim verified with `git status --porcelain` and `git log -1 --stat`.

I didn't invent these conventions. I *accumulated* them, one fresh-eyes review iteration at a time. Each was a response to a class of failure that had bitten me. The first time something failed it was a bug. The second time was a pattern. The third time was a discipline being codified into the repo so it would survive every future agent that touched the code.

This is what I mean by "the process became the deliverable." The code is the artifact in the conventional sense — it's what runs. But the *process discipline* is what makes the code possible in a FLUID regime. Without it the system would have collapsed under the weight of its own mutation rate within weeks.

This is also where the craft foundation pays off most. TDD is what gives the process its ground truth — every claimed change has a test that proves it. BDD is what gives the process its scenario coverage — every claimed feature has a world-shaped test. SOLID is what gives the process its decomposability — every claimed component has boundaries that hold under mutation. CI is what makes the process fast enough to be tolerable. None of this is new. What's new is that I'm asking these old practices to constrain a system that mutates itself daily, instead of a team of humans that ships weekly. They held.

**The operating principle this taught me:** *In a FLUID system, the most durable artifact isn't the code or the architecture — it's the process discipline that constrains how mutation happens. The factory isn't its loops; it's the contract its loops operate inside. That contract has to live in the repo, in code-shaped form, so every agent inherits it by reading.*

Read the four patterns together and they collapse into one principle: **autonomy without validation is just accelerated entropy.** HydraFlow doesn't work because the agents are clever. It works because the system has structural answers to "what happens when a clever agent is wrong."

This is the moment to take the objection head-on, because it's the one I get every time: *agents reviewing agents is just correlated rubber-stamping — two instances of the same model nodding at each other's blind spots.* The objection is right about agents and wrong about what it's measuring. It assumes verification means a reviewer reading the code and judging it. In this system no one is, human or agent, and nothing load-bearing ever was. The safety is two things that don't read code at all.

First, validation is an execution, not a judgment. A test, a type check, a scenario, a quality gate runs the same way regardless of which model wrote or reviewed the code; it can't be charmed by a plausible diff and it can't share a reviewer's taste, because it never consults one. Two correlated agents can agree all day and still both hit the same red gate. That's PR #8460 exactly: review was spotless, and the deterministic suite caught the regression review couldn't see.

Second — the part the objection never reaches — safety doesn't actually depend on catching every defect. A revert only fires on a defect you detect, and detection is bounded by what validation expresses, so the residual risk is the subtly-wrong artifact no check covers and nobody flags. The claim isn't that those never happen. It's about what such an artifact is permitted to *do*. Everything the factory can do is walled — non-destructive, in-budget, reversible by construction (the "container going fluid" section below lays those walls out). So an undetected wrong merge degrades to quality erosion accumulating inside the walls, which I can find and re-tighten, not a fire I can't put out. "Never detected" can't become "silent catastrophe" when the worst available action is bounded.

That's why the agent review passes can be as correlated as you like and nothing breaks: they sharpen, they don't certify. Calling that rubber-stamping is a category error imported from human review — it's only rubber-stamping if someone was supposed to be the gate by reading. Here the gate is execution, and the floor under the gate is the wall.

And this is the part that matters most for you, the reader. **None of this argument requires you to trust me. It requires you to recognize where the people you already trust on these topics are each pointing.** Cockburn's hex (2005) builds the container. North's BDD (2003) describes what should happen at each port. DORA tells you how to measure when delivery is working. Vincent's Superpowers encodes workflow as discipline agents inherit. Karpathy says context engineering is the new prompt engineering. Shapiro's five-level framework (January) names the trajectory toward Level 5 — Dark Software Factory. **Yegge launches Gas Town on January 1 — an orchestrator for 10–30 parallel Claude Code instances, with explicit "dark factory" framing and a role-based worker taxonomy.** Willison documents StrongDM's L5 implementation (February). Junker maps three agent roles — Drafter, Validator, Provocateur (May 14). McKinney reveals his factory (May 12).

Independent voices, different sub-domains, no coordination. All pointing at the same place: software delivery as a programmable surface, agents do the work, humans provide intent and test, validation runs continuously, the operational system — not the code — is the durable artifact. That's the future they're collectively describing.

*I'm not asking you to take any of this on my authority. I'm asking you to draw the lines between theirs.*

At the intersection of those lines, there are now **a handful of published working instances** — and new aligned cases are surfacing month over month. The most prominent, in chronological order of publication:

The first is **Steve Yegge's Gas Town** (January 1, 2026) — a Go-based orchestrator managing 10–30 Claude Code instances in parallel via tmux, with Beads (his Git-backed issue tracker) as the state backbone. Yegge uses the term *"dark factory"* explicitly — confirming the framing is converging in the language, not just in mine. His worker taxonomy (Mayor, Polecats, Refinery, Witness, Deacon, Dogs, Crew) is Mad Max themed but structurally identical to HydraFlow's caretaker categories. His MEOW stack (Beads / Epics / Molecules / Protomolecules / Formulas) is the declarative intent surface; his Nondeterministic Idempotence (NDI) is the workflow-survives-crashes discipline. He's positioning Gas Town as the orchestration layer Claude Code and competitors are missing.

The second is **StrongDM**, whose work Simon Willison documented on February 7, 2026 — eleven days before HydraFlow's first commit. StrongDM has open-sourced their intent surface as a repo called *Attractor*: three Natural Language Specs, no code, with the README's instruction *"Implement Attractor as described by [this URL]"*. Their operational shape matches HydraFlow's almost line for line — no human code review, scenario-driven testing, port-isolation at I/O boundaries, humans as spec authors. Their *architecture* doesn't match HydraFlow's at all: they run on DOT-graph pipeline runners and a programmable coding-agent library; HydraFlow runs on hex + BDD + caretaker loops.

The third is **HydraFlow** (February 18, 2026) — what I've just walked through.

The fourth is **Wes McKinney's factory**, revealed in Hugo Bowne-Anderson's piece on May 12, 2026. McKinney — pandas creator — describes parallel agents working with a *RoboRev* background reviewer. His mantra: *"I almost don't read code now... the code has all been read by agents four or five times minimum."* Different architecture again. Same operational rules.

And the language is converging at the commercial layer too. **Factory.ai** (Matan Grinberg, founded 2024) has been selling *"Your software Factory powered by Droid"* as a product positioning for two years. When a commercial vendor with capital and customers names their offering *software factory*, you're not arguing for a future. You're describing one that already has a market. Practitioners run it. Vendors sell it. The framing is mainstream — not in conference talks like this one, but in the *real economy*.

The empirical kicker that I find hardest to dismiss is the convergence-pass count. McKinney's number is *"four or five times minimum."* My number for substantial features is *"three to five iterations."* Yegge cites Jeffrey Emanuel's *"Rule of Five"* review-pass discipline as a load-bearing principle of Gas Town. **Three independent voices, the same number.** Not a similar number. The same one. Three independent measurements landing on the same convergence depth is not coincidence — it's the work itself revealing what it takes to converge a substantial feature under governed mutation.

**Independent designs. Different architectures. Different domains. And the list is growing.** A precision worth making explicit: Gas Town wasn't parallel arrival for me — it was the *catalyst*. Yegge's January piece showed me the operational thing was buildable, and I started seven weeks later, with FLUID already in hand from over a year before. **StrongDM, McKinney, Junker — those are genuinely independent.** I didn't know about StrongDM until well after my first commit. McKinney's reveal came in May. Junker published just last week. The structural convergences with them — MockWorld matching StrongDM's Digital Twin Universe, my caretaker categories matching Junker's three roles, the *Rule of Five* (from Yegge citing Emanuel) matching McKinney's "four or five" and my own "three to five" — those are parallel arrivals, not influence. That parallel evolution — independent implementations converging on the same operational rules without contact, from different starting points and different problem spaces — is the strongest single piece of evidence I have that the operational patterns aren't artifacts of any one implementation. They're what the work demands. What I'm presenting isn't *my system*. It's a working instance of a pattern emerging across the field, at the intersection of where the people you trust on these topics are each pointing.

---

## Where engineering value moved — the staircase

The four patterns converge on a staircase. Most of the industry is parked on the first step. HydraFlow is showing what steps four and five actually look like.

1. **Code generation.** What current AI conversation centers on. Necessary, but the least durable level — the artifact regenerates.
2. **Validation systems.** Three-layer pyramid. Conformance tests. The encode-corrections loop. Validation isn't infrastructure; it's the design process making itself permanent.
3. **Semantic governance.** Ubiquitous language extraction. Drift detection between term anchors and code. Semantic linting. The discipline that protects conceptual integrity from agents that haven't read the conventions.
4. **Operational knowledge graphs.** ADRs, wiki pages, architecture docs, repository structures, service ownership, operational dependencies — compiled into a navigable, queryable structure. Karpathy has been writing about repos becoming self-documenting knowledge systems — and his line that *context engineering is the new prompt engineering* points at the same shape from a different angle. HydraFlow's `RepoWikiLoop` and ubiquitous-language extractor are what that looks like *operationalized*: the system rewrites its own wiki from live events, extracts terminology continuously, treats drift between term anchors and live code as a build failure. The repo evolves from "a pile of code" into "a continuously maintained operational knowledge model." Agents need structured situational understanding, not just files. Karpathy points at the *what*. HydraFlow's loops are one instance of the *how*.
5. **Autonomous mutation governance.** Tool access. Mutation permissions. Deployment authority. Escalation rules. Rollback policies. Blast-radius constraints. Plus the observability and recovery that makes autonomy survivable — traces, behavioral telemetry, eval scoring, drift detection, operational replay, rollback automation. Autonomy without recovery is just accelerated failure.

Each step is necessary for the next. You can't get to semantic governance without validation that exposes drift. You can't get to operational knowledge graphs without semantic governance keeping terminology consistent across the structure. You can't get to autonomous mutation governance without the knowledge graph the agent reads to decide what's safe to change.

A flat list of practices misses the ordering. The staircase makes it visible. It's also the part of the picture most engineering leaders aren't seeing yet — most planning conversations are still entirely about step 1.

A few practices don't sit on a single step — they operate across the staircase as a whole. **Scenario design** feeds both validation and semantic governance: the scenario is what the system measures itself against and how it knows the terminology landed. **World-modeling** (the discipline MockWorld is one instance of) is how validation gets sharper at higher steps — you can't validate autonomous mutation against a static fixture. **Context engineering** is the substrate semantic governance and operational knowledge graphs both rest on. These cross-cutting practices are the connective tissue of the staircase, not a separate level.

There's also a supply-side counterpart Adam Jacobs has been writing about: the unit of value in software factories isn't the application — it's the *adaptive primitive*, the building block that conforms to user context rather than forcing the user to conform to it. HydraFlow's loops are adaptive primitives. So is MockWorld. So is the autonomy doctrine. *What* you build matters as much as *how*, and adaptive primitives is the right shape for that artifact in a V2V regime.

## Why traditional SDLC abstractions break down

The patterns sit in a space the old SDLC frame stopped covering — and the size of that gap is most of why this work matters.

The SDLC was built around assumptions about how software gets made. Work decomposes into tickets. Tickets become implementation phases. Phases get tested, then deployed, then maintained. Architecture is a thing you decide up front and review through change boards. Documentation is a separable artifact someone writes after the code is done. Delivery is sequential — design before code, code before test, test before deploy.

Once a system mutates continuously, none of those assumptions hold:

- **Ticket boundaries weaken.** Work doesn't decompose into tickets when an agent does the decomposition. The unit becomes a scenario, not a ticket — and scenarios cross what used to be ticket boundaries because the system optimizes for the outcome, not the JIRA grain.
- **Implementation phases blur.** Design happens at validation time (Pattern 2), not before code. The first implementation is a probe. Validation pushes it into shape. "Implementation" and "review" stop being sequential phases and become a single iterating loop that converges over three to five passes.
- **QA shifts left and right simultaneously.** Earlier — scenarios authored before any code, as the design surface. Later — continuous validation as engine, sharpening after every merge. "QA" stops existing as a discrete stage; quality is encoded into the system's running behavior.
- **Architecture becomes runtime-governed.** Architecture tests are what enforce it, not a one-time review. Drift between code and diagram is a build failure. The architecture stops being a snapshot and becomes a live constraint the system enforces against itself on every PR.
- **Documentation becomes continuously synthesized.** The wiki regenerates from live events. ADRs cross-reference automatically. The system map rebuilds every PR. Documentation stops being something someone writes after the code is done and becomes something the system produces while running.
- **Delivery becomes probabilistic rather than sequential.** RC promotion gates statistically — the four-hour cadence either passes twelve sandbox scenarios or it doesn't. Delivery is no longer "we deployed on Thursday." It's "the system promoted itself 5 of 6 cycles this week, here's why one failed and how it recovered."

These aren't tweaks to the existing SDLC. They're a different operating frame, and the old vocabulary actively misleads when applied to it.

Most of the strain I see in engineering organizations adopting AI-assisted development comes from running V2V-shaped work through SDLC-shaped governance. Standups still report ticket-by-ticket progress on work the agents decomposed into something else. Architecture reviews still meet quarterly to ratify decisions the architecture tests already enforce. Documentation teams still chase deltas the wiki already regenerated. The vocabulary mismatch isn't cosmetic — it actively prevents the organization from seeing what its system is doing.

The space this creates is what the four patterns occupy. Caretaker taxonomy fills what "ticket workflow" used to. Validation as engine fills what "QA phase" used to. MockWorld fills what "staging environment" used to. Process as deliverable fills what "change management" used to. The patterns aren't replacing the SDLC piece by piece — they're the shape of the frame that fits the new operating reality, which is why no patchwork of SDLC tools quite gets there. The unit of work in this regime isn't ticket-to-code. It's intent-to-outcome. That's V2V's territory.

## How V2V teams operate

I keep getting this question, and it's the fair one. *You're describing what one engineer can do with HydraFlow. What does a team of twelve do under V2V?*

The honest answer is the role shape changes more than the headcount does. Generalist engineers become specialists around the staircase:

- **Scenario authors** own the operating-condition library. They write Given-When-Then specs for the *world*, not just user flows. Highest-leverage role, because the scenario is the durable artifact — the implementation will be regenerated, the scenario won't.
- **Validation engineers** own the test pyramid, the conformance tests, the drift detectors, the encode-corrections loop. They're the gardeners of the validation layer. Most of their day is upgrading the validation infrastructure after each class of bug surfaces.
- **Context engineers** own ubiquitous language, the repo wiki, knowledge graph compilation. They make the system legible to itself. This is the role that didn't exist five years ago and is suddenly load-bearing.
- **Autonomy designers** own the doctrine, kill-switches, blast-radius classification. They decide what the agents are allowed to do and where the boundaries are. The closest analogue is platform security engineering, but with a softer mandate.
- **Operators (SRE-shaped engineers)** own the dashboard, the cost loops, the escalation queue, the fleet observability. They watch the system run.

A team of twelve operating V2V might look like three scenario authors, three validation engineers, two context engineers, two autonomy designers, two operators. Not a great match for current org charts. That's the point — the org chart needs to change.

The workflow changes too. Standups are no longer "what tickets are you on?" — they're "what did the fleet do overnight, what did it catch, what escalated, what needs human judgment?" PR reviews invert, and the inversion is sharper than it looks: code-line gatekeeping wasn't where safety lived even when humans did it — safety lived in the executable scenario layer and in reversibility. So most PRs being agent-authored doesn't move the safety boundary at all. It frees the human review that remains to do the job reading was always actually good at: *intent alignment* (does this match the scenario?) and *validation upgrade* (what scenario would have caught this without me?). That's sharpening the spec, not guarding the merge. The merge was never guarded by a reader. Architecture meetings shrink — architecture is runtime-governed, the tests enforce it, the remaining meetings are about *new* architectural decisions, not ratifying existing ones.

The hardest cultural shift is what stops being measured. Lines of code stop mattering. PR throughput stops mattering. Story-point velocity stops mattering. What starts mattering is harder: drift rate, recovery time, scenario coverage, validation-pyramid completeness, knowledge-bug count. If you've been following DORA for the last decade, you know the canonical four — deployment frequency, lead time, change failure rate, MTTR. Notice what was never on that list: "percentage of diffs a senior engineer read," or review thoroughness. Two of the four — change-failure-rate and time-to-restore — define a healthy delivery system entirely around the *cost and recoverability of being wrong*, not around a gate that prevents wrongness by inspection. The industry already converged on "be wrong cheaply and recover fast" as its safety model; it just doesn't say so out loud. And the research on human review itself — Bacchelli and Bird's study of review at Microsoft is the one I'd cite — found its real value was knowledge sharing and design feedback, while finding deep functional defects was the weak spot reviewers routinely missed. So human review was never the safety layer either. Tests, CI, staging, and revert were. Fluid code doesn't remove a safety layer; it removes the layer that was never carrying the safety, and turns the layer that was into the engine. The agent review passes inherited the job human reading actually did — sharpening the artifact toward the spec. Validation-plus-revert inherited the job it actually did — bounding the blast radius. Those aren't being replaced. They're getting a new layer above them. The DORA four measure how fast and safely a system *runs*. The new metrics measure how coherent it stays as it *mutates itself*. Both still matter; together they describe the full picture of a V2V system's health. These don't fit current performance-review templates. That's a real organizational design problem, and most companies haven't solved it. I haven't either — I'm running HydraFlow mostly solo, so the team question is one I'm watching others answer.

One distinction worth naming: even within V2V teams, there's a gradient. Some teams keep humans in the PR-review loop for intent alignment. HydraFlow itself is operating further along that gradient — the human (me) doesn't review individual PRs. The system handles the *sharpening* through subagent-driven spec-compliance checks, code-quality passes, and fresh-eyes audits. But what makes pulling the human out of review safe isn't that those passes substitute for me as the gate. It's that the gate was never a reader: the deterministic checks and the bounded, reversible blast radius authorize a merge, and they run whether or not anyone — me or an agent — looked. The audits sharpen; the gates and the walls decide. My role is pure workflow encoding: writing the conventions, scenarios, ADRs, and autonomy doctrine the system reads. That's dark factory mode in practice. It's the direction the patterns push toward; it's not the only stop on the gradient. Most teams will land somewhere between human-in-review and human-out-of-review, and both ends are valid V2V — the patterns work the same way.

## This isn't for all software — and games are next

I should be specific about what HydraFlow is and isn't. HydraFlow is software that does software-shaped work: orchestration, infrastructure, dev tools, factory automation. Its outputs are commits and PRs. Its successes are observable through traces and tests. Its failures are reversible through reverts — and that last property isn't just what scopes HydraFlow-class software. It's half of why autonomous merge is safe at all: the walled, reversible blast radius is what makes the cost of being wrong bounded and recoverable, which means the whole rubber-stamping rebuttal is *conditional* on it. The answer holds for legible-output software with revertible side effects. The class I want to try next — games HydraFlow releases and maintains itself — breaks the condition at both ends. Aesthetic correctness has no executable gate, so nothing detects a wrong artifact; a shipped balance change or a level a player already experienced has no clean revert, so the side effect escaped the walls the moment it reached a human. There, evaluation-by-judgment isn't a category error to dissolve — it's the actual required mechanism, and the rubber-stamping objection genuinely applies until a real anchor exists: player telemetry, retention curves, held-out human playtesters wired into the validation chain. StrongDM's held-out scenarios are the version of that discipline I haven't built yet. So I'm not claiming the rebuttal generalizes past this domain. I'm claiming it holds where the walls hold, and naming the seam where they don't.

That's a specific class of software. It's not most software. And the question I actually want to answer next isn't "do the patterns generalize?" — it's something tighter:

> *Is there a class of software where autonomous mutation plus self-validation can sustain ongoing value with humans operating mostly at governance boundaries?*

Note what that question isn't asking. It isn't asking whether humans can be removed entirely. They can't, and I'm not trying to. The interesting question is whether there are domains where the human time per unit of delivered value drops far enough to change the economics of building and maintaining software — humans staying in the loop on intent, scope, and judgment, but stepping out of the day-to-day mutation cycle.

The four patterns — caretaker taxonomy, validation as engine, MockWorld as world-modeling, process as deliverable — work cleanly for HydraFlow-class software because its failure modes are mostly *legible*. A bad commit is detectable. A failing test is observable. A drift in vocabulary is auditable. The validation layer has something concrete to be sharper about, and the encode-corrections loop has clear signals to encode from.

Where it gets interesting is software whose validation isn't legible the same way. Software where success is aesthetic or experiential rather than functional. Software where the right answer is "this is fun" or "this feels right" rather than "the tests pass."

That's what I want to try next. Games — projects HydraFlow releases and maintains itself. If the four patterns hold there, you've crossed into a class of software that produces ongoing value with most of the human time pulled out of the mutation loop.

Games are a good stress test because they break the legibility assumption deliberately. Aesthetic validation doesn't pass through a unit test. Content (art, music, levels) is generated, not implemented. Player experience is the success metric, and it's variable across players. Continuous release exists — patches, balance updates — but with an entirely different feedback loop than a software service.

The interesting questions:

- What does a caretaker loop look like when the invariant it's checking is "is this fun"? Does the taxonomy survive — maintainers, proposers, auditors, repairers — or do new categories emerge?
- What's the encode-corrections loop for aesthetic feedback? Player retention curves? Tagged playtest sessions? Sentiment from reviews?
- Can MockWorld simulate *players*? Behavior trees? Skill distributions? Difficulty curves? Or does the play loop need real humans somewhere in the validation chain?
- How does process discipline change when the iteration unit is "does this feel right" instead of "do the tests pass"?

I don't have answers. That's why it's the experiment. The hypothesis is that the four patterns are general enough to survive the move with modifications — that the failure modes change but the *shape* of the discipline doesn't. If it works, you have a category of software that releases and maintains itself in a domain that has historically been the most hand-crafted.

If it doesn't work, I'll have learned which of the patterns are universal and which were specific to legible-output software. Either way, the experiment surfaces something worth knowing.

## What I expect to break next

I've spent this piece describing what's working. I should be specific about what I'm watching for, because the parts I haven't hit yet are where the next learning comes from.

Five failure modes I think are most likely to surface, in roughly the order I expect to hit them:

**Drift from operator intent.** The validation infrastructure measures what it can measure. The encode-corrections loop sharpens against detectable failures. Both of those are good. Both of those leave room for the system to optimize for *legible* validation while wandering from what I actually wanted. The scenario is the bulwark — if the scenario captures real intent, the system stays aligned. If the scenario captures *proxy* intent, the system drifts toward the proxy. I haven't hit this yet. I will.

**Loop equilibria getting weird.** Each caretaker loop's contract is local. Cross-loop interactions are emergent. I can imagine combinations where two loops settle into a stable but bad equilibrium — a proposer keeps proposing what a pruner keeps deleting, or two auditors disagree about an invariant and correct each other's corrections. I haven't seen this at fifteen loops. I expect to see it before fifty.

**The autonomy doctrine getting stale.** The doctrine is a typed permission table. It's load-bearing right now because the agents respect it. The cases I'm watching are the ones the doctrine doesn't anticipate — actions that fall in seams between classifications, or actions whose blast radius depends on context the doctrine doesn't encode. The discipline is to update the doctrine each time it gaps. The risk is the gaps accumulate faster than I notice them.

**Process bankruptcy.** The process discipline is the deliverable, per Pattern 4. If the discipline rots — if conventions stop getting codified, if the third-instance-then-codify rule slips, if fresh-eyes reviews stop happening — the whole regime degrades silently. Process discipline doesn't fail loudly. It fails by becoming less and less worth following until nobody remembers why a rule was there. That's the failure mode I'd find hardest to detect early.

**The container going fluid.** This is the one that worries me most, because it's structural rather than operational, and because the routine path has no human in it. I'm pulled in for high-impact actions, and I verify the system's direction at some point — but I don't review the work that lands day to day; another agent approves it. Read in isolation that sounds like the rubber stamp the whole objection warns about, so let me be exact: the agent's approval is not the safety guarantee, and I don't treat it as one. The deterministic gates that run regardless of the approval, and the irreversibility wall the factory can't edit, are. The approval is the system telling itself the artifact looks done; the gates and the wall are what make "looks done" safe to act on. HydraFlow modifies HydraFlow, including the machinery that decides what's allowed to land, and softening a gate doesn't read as high-impact. It reads as a routine change to a test or a config, exactly what the autonomous path is built to approve on its own. So nothing in the loop that runs each day stops the factory from loosening its own gates and then approving the loosening. So I assume the gates *will* drift — a threshold lowered, a skip added, each change individually defensible, each one approved against standards the same drift is relaxing. What keeps that from turning catastrophic isn't a veto, and — this is the second leg of the rubber-stamping rebuttal, so I'll be blunt — it isn't the agent review either. It's that the gates are habits, but the blast radius is a wall. This is why the safety claim earlier rests on the wall and not on validation-sharpening: validation does correctness work and *is* erodable, exactly as I'm describing here; the wall does safety work and isn't, because it lives outside the code the factory may edit. The factory can rewrite what it checks; it cannot take an action it can't take back. Destructive operations are intercepted by hooks. It cannot raise its own credit ceiling. It cannot reach in and adjust persisted state. Everything it *can* do is reversible, in-budget, and non-destructive by construction — so the worst case of a softened gate is quality erosion I can detect and re-tighten, not a fire I can't put out. The vessel stays solid because the walls live outside the code the factory is allowed to edit. The day one of those walls becomes just another file in the repo, the floor turns back into a habit, and that's the line I have to keep on the far side of the factory's reach.

None of these are reasons not to do this work. They're the next experiments. The shape of FLUID-system engineering is partly *deciding which failure mode you're about to hit and building the infrastructure that catches it* — and partly knowing the one piece of infrastructure you must never let the system rebuild for you.

## Where the engineer goes

Historically, engineering mastery was expressed through implementation. Writing elegant code. Mastering frameworks. Manually solving complexity. Optimizing systems directly. The signals of mastery were the same signals across most of a career.

In a FLUID regime, the signals shift. The strongest moments I've had with HydraFlow aren't moments when I'm writing code. They're moments when I'm naming a domain crisply enough that the system uses the name back. Writing a contract so unambiguous the agent reading it can act on it. Designing a scenario that exposes a class of failure no one had thought to test. Noticing a third instance of the same kind of caretaker and codifying the category before the fourth one drifts.

In concrete form: with HydraFlow bedded down enough that it runs through the night, my days have a different shape than when I was building it. We co-build new caretaker loops — me sketching the intent, the system writing the wiring against the five-checkpoint convention. I write the ADR. The principles audit reviews it. Subagents do the implementation review. By morning the new loop is in staging, the dashboards show it ticking, and I'm adjusting only if something looks off. The work that fills my days is *extending* the factory with new operational primitives — turning concepts that used to be static documentation into living artifacts. That's the new mastery in concrete form. Not "human writes code, AI helps." Not "human reviews what AI generated." It's *"human encodes the conventions, the system manifests them, the conventions get sharper through use."*

The craft becomes:

- shaping constraints
- designing validation systems
- world-modeling for autonomous behavior
- preserving coherence under mutation
- recognizing taxonomic patterns as they emerge
- writing process discipline into the repo so the next agent inherits it

That can feel destabilizing because the old mastery signals weaken. Writing code fast doesn't matter the same way when the system writes code fast. Memorizing the codebase doesn't matter the same way when the codebase regenerates. The fear isn't about typing less. The fear is loss of relevance, loss of differentiation, loss of mastery, loss of identity, uncertainty about where value now lives.

Some of that disruption is real.

But the engineers most likely to thrive are the ones who already had a craft foundation — TDD, BDD, SOLID, CI — and the habit of asking "where in the body of craft does this experience belong?" when they meet something new. Because once implementation becomes abundant, judgment becomes scarce. And judgment has always been the hardest part of engineering anyway.

There's a particular kind of engineer who, when I describe what HydraFlow does, asks two questions:

> *What does the system do when it disagrees with itself?*
> *How do you know the validation is actually validating?*

That engineer is going to be fine. That engineer is the one I'm hiring. The discipline they're pointing at — coherence under self-modification, validation as a learning system — is exactly the new mastery. And the practices that prepared them for those questions are the same craft foundation that prepared me to run this experiment in the first place.

The leverage hierarchy is changing. But it isn't disappearing. The old craft is being subsumed into a larger one.

## The central shift

The old engineering question was: *"Can you build the system?"*

The emerging engineering question is: *"Can you govern systems that continuously build and evolve themselves safely?"*

Most of the industry is still evaluating engineers using assumptions from the autocomplete era. But the center of engineering value is already moving upward into validation, governance, coherence, orchestration, context engineering, semantic alignment, operational reasoning, adaptive systems management.

I wrote FLUID in March 2025 to describe what code should look like when machines and humans co-author it. Running HydraFlow taught me the principles were necessary but not sufficient. The principles describe the artifact. They don't describe the *operating regime* the artifact creates.

The four patterns — caretaker taxonomy, validation as engine, MockWorld as world-modeling, process as deliverable — are that operating regime. They emerged. They weren't designed up front. They're what HydraFlow's running surface taught me about engineering in this new shape, and the discipline that turns FLUID code into a FLUID system that can run without breaking.

And under all of them, the craft foundation — TDD, BDD, SOLID, CI — held. Not in opposition to FLUID. As the substrate that made FLUID safe to operate. Pour code fast with nothing beneath it and you get a flood; the container is what turns that same speed into fluidity. We got solid enough underneath that the code could finally become liquid without spilling.

Code is no longer the stable artifact. The operational system is. And that fundamentally changes where engineering cognition, craftsmanship, and value now live.

And HydraFlow isn't a one-off. There's a handful of published cases now — Yegge's Gas Town (Jan 1), StrongDM's Attractor (Feb 7), HydraFlow (Feb 18), McKinney's factory (May 12) — with new aligned voices surfacing month over month, all arriving independently at the same operational rules from completely different architectures and domains. **Independent designs. Different starting points. One operational shape.** That's what tells me the patterns aren't mine, or theirs. They're what the work demands. The essay you've just read isn't a personal manifesto. It's a working instance of a pattern emerging across the field — at the intersection of where the people you trust on these topics are each pointing.

The next experiment is whether the same patterns let a game release and maintain itself — and whether dark factory mode survives a domain where the validation problem isn't legible.

I'll let you know.

---

## Further reading

**On the five-level framework and "dark factory" terminology:**

- Dan Shapiro — *The Five Levels: From Spicy Autocomplete to the Software Factory* (Jan 23, 2026) — <https://www.danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/> — the originating framework. HydraFlow operates at Shapiro's Level 4; Level 5 is the explicit goal.
- Simon Willison — *The Five Levels* (Jan 28, 2026) — <https://simonwillison.net/2026/Jan/28/the-five-levels/> — commentary on Shapiro's framework with the L5 team-shape markers.
- Simon Willison — *How StrongDM's AI team build serious software without even looking at the code* (Feb 7, 2026) — <https://simonwillison.net/2026/Feb/7/software-factory/> — the closest published L5 case. StrongDM's *Digital Twin Universe* is structurally the same pattern as HydraFlow's MockWorld + Port↔Fake conformance; their held-out scenarios are the discipline I haven't built yet. We arrived at the convergent patterns without contact — HydraFlow's first commit landed 11 days after this post.
- StrongDM — *Attractor* (open-source NLSpecs, no code) — <https://github.com/strongdm/attractor> — StrongDM's published intent surface: three Natural Language Specs (`attractor-spec.md` / `coding-agent-loop-spec.md` / `unified-llm-spec.md`). The repo's instruction — *"Implement Attractor as described by [this URL]"* — is the working illustration of "humans provide intent, the system implements against it." Architectural divergence from HydraFlow (DOT-graph pipelines vs hex + BDD + caretaker loops); convergent in purpose.
- Hugo Bowne-Anderson (with Wes McKinney, Jeremiah Lowin, Randy Olson) — *Agentic Engineering and the Lost Art of Verification* (May 12, 2026) — <https://hugobowne.substack.com/p/agentic-engineering-and-the-lost> — third independent convergence case. McKinney (creator of pandas) describes a software factory of parallel agents with a "RoboRev" background reviewer: *"I almost don't read code now... the code has all been read by agents four or five times minimum."* The four-to-five-passes detail matches HydraFlow's convergence-count data exactly. McKinney doesn't reference Shapiro, Willison, or StrongDM — independent arrival.
- Factory.ai — <https://factory.ai/> — agent-native software development platform (Matan Grinberg, founded 2024). Tagline: *"Your software Factory powered by Droid."* The most commercially visible vendor using *software factory* terminology — a market signal that the framing is converging at the commercial layer, not just in practitioner case studies.
- Steve Yegge — *Welcome to Gas Town* (January 1, 2026) — <https://steve-yegge.medium.com/welcome-to-gas-town-4f25ee16dd04> — the earliest published working instance. Go-based orchestrator for 10–30 parallel Claude Code instances via tmux, with Beads (his Git-backed issue tracker) as the state backbone. Explicit *dark factory* framing, role-based worker taxonomy (Mayor / Polecats / Refinery / Witness / Deacon / Dogs / Crew — Mad Max themed, structurally analogous to HydraFlow's caretaker categories). The MEOW stack (Beads / Epics / Molecules / Protomolecules / Formulas) is the declarative intent surface. Nondeterministic Idempotence: workflows persist across agent crashes. Cites *Jeffrey Emanuel's Rule of Five* — a third independent source of the same convergence-pass count that surfaces in HydraFlow and McKinney's factory.
- Cow-Shed — *Dark Factories: Five Levels of AI Automation Transforming Audit, Banking, Legal* — <https://www.cow-shed.com/blog/dark-factories-five-levels-ai-automation-transform-audit-banking-legal> — a domain adaptation of Shapiro's framework with a stricter L5 marker (held-out evaluation scenarios).

**On the patterns this essay engages with:**

- Adam Tornhill — *Compressed Cognition: The Hidden Cost* — <https://adamtornhill.substack.com/p/compressed-cognition-the-hidden-cost> — the 19%-slower study and decision-density mechanism.
- Tori Huang — *Claude Code: Do My Job Faster* — <https://bytorihuang.com/writing/2026/04/claude-code-do-my-job-faster/> — process-vs-knowledge bugs and the encode-corrections loop.
- Adam Jacobs — *Adaptive Building Blocks* — <https://www.adamhjk.com/blog/adaptive-building-blocks/> — adaptive primitives as the supply-side counterpart.

**Heritage references (the substrate FLUID rests on):**

- Alistair Cockburn — *Hexagonal Architecture* (2005) — the architectural pattern HydraFlow's core is built on; every external dependency goes through a typed Port.
- Dan North — *Introducing BDD* (2006) — the behavior-driven discipline MockWorld extends from user flows to operating conditions.
- Forsgren, Humble & Kim — *Accelerate: The Science of Lean Software and DevOps* — the DORA research book; the metrics layer above which HydraFlow's coherence-under-mutation metrics live.
- Jesse Vincent — *Superpowers* framework — the workflow substrate for agentic engineering. The brainstorming / spec / plan / TDD / sub-agent-driven implementation / fresh-eyes review patterns HydraFlow's workflow runs on. Vincent's framing: *"The difference between vibe coding and agentic engineering is planning, architecture, and caring about the output."* The same substrate Wes McKinney's factory uses; the operational architectures around it (caretaker loops vs RoboRev + Agents View + Middleman + Kata) are independently designed.
- Annegret Junker — *AI as a Design Partner: Drafter, Validator, Provocateur* (codecentric, May 14, 2026) — <https://www.codecentric.de/en/knowledge-hub/blog/ai-as-a-design-partner-drafter-validator-provocateur> — names three roles AI plays in DDD-driven design: Drafter (produces first-pass artifacts), Validator (checks consistency), Provocateur (surfaces assumptions and edge cases). Maps cleanly onto HydraFlow's caretaker categories — her Drafter ≈ our Proposers, her Validator ≈ our Auditors, her Provocateur ≈ our adversarial corpus and advisor loops. Quote worth keeping: *"A wrong-but-specific draft is faster to evaluate, edit, or reject than a blank page."* Another convergent voice in the DDD lineage.

**My prior writing on FLUID and the post-SOLID regime:**

- *Mutable by Design: The FLUID Software Philosophy* — <https://aibuddy.software/mutable-by-design-the-fluid-software-philosophy/>
- *The Post-SOLID Era: When Code Becomes Fluid* — <https://aibuddy.software/the-post-solid-era-when-code-becomes-fluid/>

**The project and the talk:**

- HydraFlow — <https://hydraflow.ai/>
- Accelerate Chicago 2026 (June 22–24, Convene Willis Tower) — <https://gotochgo.com/accelerate-chicago-2026>
