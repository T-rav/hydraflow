---
marp: true
theme: default
paginate: true
---

<!--
Speaker deck for "When Code Becomes Fluid." Story-driven, not a patterns dump.
Slides are deliberately sparse; the narrative lives in the speaker notes.
Default Marp theme — brand visuals to be layered later.

ARCHITECTURE (v3): provocation cold open → three-stage motive arc → ending shot.
The motive matures across the talk: (1) need — maintain what I vibed; (2) question —
Gas Town: how much human can you pull out, and what breaks; (3) meaning — her.
Act 2 is the answer to motive 2. The ending shot is motive 3.

PRODUCTION NOTES:
- Daughter appears as "Z" (initial only) on slides and stage — full name stays out (minor, public stage).
- Numbers verified 2026-06-09: 47 loops (docs/arch/generated/loops.md), 1,644 merged PRs
  (gh search), first commit 2026-02-18. REFRESH BOTH before the stage — the loop registry
  is public on hydraflow.ai and the room will check.
- Quality metrics verified 2026-06-09: 12,898 test functions / 839 test files; coverage
  fail-under 70 (pyproject + ci.yml); 478 scenario tests (tests/scenarios); 61 sandbox e2e
  files; 176 regression tests; 314 wiki json:entry blocks; 41 term files; 91 ADRs; hero
  quote verbatim at tests/test_gates_activation.py:148; gates-drift.yml = watcher-for-the-
  watchers receipt; PR #8460 21:43:31Z → #8463 created 22:07:51, merged 22:25:14 (42 min
  break-to-fixed total).
- The her-and-Claude ritual has NOT run yet. Keep it future tense on stage. The close is
  "I'll let you know," and that only stays true if nothing earlier pretends it already happened.
- InsightMesh chronology VERIFIED from git (2026-06-09):
  · v1 → v2 rewrite began 2025-08-28 (v2 repo first commit: "ported slackbot from insightmesh").
  · v1 was Cursor-built, ~no human review, no guardrails — died. v2: still all vibe-coded, still
    ~no review, but WITH guardrails — alive today. The walls-over-vigilance bet predates the factory.
  · HydraFlow born inside InsightMesh at dx/hydra/ on 2026-02-18, commit 542dcd6a
    "feat: Add Hydra — parallel Claude Code issue processor". Standalone repo init same day
    08:57; orchestrator lands 2026-02-19 00:33; CI 00:38; quality hooks 00:40 (walls up in
    ten minutes); self-issue-fixing PRs #53–60 merged by ~17:00 Feb 19. InsightMesh then
    vendored hydraflow content back (subtree squashes FROM hydraflow commits) until fully
    removed 2026-05-21 (#722). Cold open uses "three days later, it left" (author's call);
    the day-two self-PR detail stays available as optional spoken escalation.
-->

# Self-Building Software

## Lessons from the HydraFlow Experiment

#### When code becomes fluid, where does the engineer go?

Accelerate Chicago 2026

<!--
Title card carries the submitted talk title — it must match the program attendees picked the session from — with the essay/series title as the subtitle question. The card does double duty: the program title says what the talk is, the subtitle plants the question the close slide answers ("Into the printer").

Open with a SMALL intro over this card — no silent hold (dead air reads wrong live), but keep it to ~15–20 seconds and don't spend any later beats (no TDD, no daughter — those have slides waiting):

"Thanks, [emcee]. I'm Travis Frisinger — I've been building software for twenty-some years, and for the next forty-five minutes I'm going to tell you the story of the strangest thing I've ever built. (beat) It starts four months ago, with a folder."

Advance to the next slide ON "a folder" — the birth scene lands as the sentence completes. The intro's only jobs: name, warmth, and the promise of a story. Everything else waits.
-->

---

## Four months ago, I made a folder inside another repo.

# Three days later, it left.

<!--
Say it slow, like you're still slightly unsettled by it — picking up directly from the intro's "...with a folder": "The folder lived inside an internal platform I'd vibe-coded. It was called dx/hydra. (beat) Three days later, what was in that folder left — into its own repository. (beat) It has been building itself ever since." Eerie, not boastful. Optional escalation texture, all receipt-backed if you want to layer it in: within ten minutes of its orchestrator landing in the new repo it had CI and pre-push quality gates — the walls went up before the machine turned on — and it was fixing its own issues and merging its own pull requests by the next afternoon (PRs #53–60, ~17:00 Feb 19). Receipts: born at dx/hydra Feb 18 (commit 542dcd6a, "feat: Add Hydra — parallel Claude Code issue processor"); standalone repo init Feb 18 08:57; orchestrator Feb 19 00:33; CI 00:38; quality hooks 00:40. (Option: put a commit line on the slide as documentary texture.) Don't explain yet. Let the room want the chronology.
-->

---

## It has been building itself ever since.

# 47 loops. 1,600+ merged PRs.

#### I have never reviewed its code. No human has.

<!--
Stage the numbers one at a time, like evidence at trial, not a LinkedIn cadence. "Forty-seven autonomous loops. (beat) More than sixteen hundred merged pull requests. (beat) Four months. (beat) And I have never reviewed its code. No human has." Then, if you want the deepest cut, the handover curve: "Two out of every three commits in the factory were authored by the factory. In the first two weeks, I out-committed my agents. Last month, they out-committed me three to one. The git log shows the handover happening." (Receipts: 1,227 of 1,790 non-merge commits by agent identities; first two weeks Travis 328 vs agents ~244; last 30 days agents 305 vs Travis 116. STRONG CANDIDATE for a slide visual — monthly stacked bar, human vs agent commits, the flip is the picture of 'self-building'.) REFRESH NUMBERS before stage — loops from docs/arch/generated/loops.md, PR count from gh. The claim must match the public registry exactly, because someone in row three will pull it up.
-->

---

## I know what that sentence does to a room like this.

# Code was identity.

#### I taught TDD to hundreds of engineers. Red, green, refactor was how I proved I was good.

<!--
The empathy beat — it MUST land within a minute of the claim, or the next forty minutes read as a flex. And it's testimony, not observation: "I taught test-driven development to hundreds of engineers. I still run tddbuddy.com — katas, TDD concepts, the whole discipline. Code, and the craft around it, was my identity. So when I tell you no human reviews this system's code, understand: that sentence cost ME first." The anxiety in our industry isn't about productivity; it's about identity. Then the pivot that frames the talk: "This is the story of pulling the human out of the loop — how far it goes, what holds the line instead, and what I found at the bottom of it. Which is not what I expected." (Bonus: this plants the payoff for the hero-artifact slide — the TDD teacher's factory writes tests that defend themselves.)
-->

---

## It started as a maintenance problem.

An internal platform, AI-built. Agents, retrieval, scheduled tasks, observability. No guardrails.

# August 28, 2025: v1 died. I started over — and kept the lessons.

<!--
Motive one — the relatable one, a confession, and secretly the origin of the whole thesis. InsightMesh: a real internal sales-enablement platform, built the way most of this room is building right now — Cursor, fast, thrilling, barely any review, no strong guardrails. (Stack stays a spoken aside at most — "LangGraph agents, Langfuse traces, the stack you'd expect." Real, not a toy.) "And v1 collapsed under its own weight. I couldn't maintain what I'd made. So on August 28, 2025 — the date's in the git history — I did what every engineer in this room has done at least once: threw it away and started over." Then the beat that carries the talk in miniature, slow: "Here's the fork in the road. The obvious fix was to put the human back in the loop — review everything, slow down. I did the opposite. v2 — the version alive today — is still entirely AI-written. Still almost no human review. What changed was the guardrails: standards, tests, CI walls. The version with less structure died. The version with more structure lives." The bet — walls over vigilance — was made HERE, ten months before the factory. The lessons rolled forward — that's roll number one, and it won't be the last time you hear that phrase tonight. This conference's tagline is "you ship it, you own it, you maintain it" — and the word AI changed most isn't ship or own. It's maintain. Vibe to Value — the methodology name is this journey, compressed to three characters.
-->

---

## Then Steve Yegge published *Gas Town*.

#### January 1, 2026.

# How much of the human can you pull out — and what breaks?

<!--
Motive two — the question. Be honest: Gas Town was the catalyst, not a parallel discovery. Steve showed the operational thing was buildable — a fleet of agents, an orchestrator, a human babysitting the swarm. I couldn't put the question down. Seven weeks later: first commit, February 18 — inside the InsightMesh repo, because it was born as a maintenance helper for the thing I'd vibed, carrying v2's guardrail lessons with it. Roll number two, and you can see it in the log: within ten minutes of the orchestrator arriving in the new repo, it had CI and quality gates. The walls went up first. Three days later it outgrew its host and moved into its own repo — and InsightMesh carried a vendored copy of its offspring for three more months before the umbilical was fully cut in May. Then the plant, one line, move on: "And somewhere in the four months since, the reason I was building changed. I'll get there."
-->

---

## So I didn't hire help.

# I built a factory.

#### Intent in. Software out.

<!--
Name HydraFlow here — not as a product, as the answer to the question. You file intent. The system plans, implements, tests, reviews, and merges. Humans provide exactly two things: intent and tests — specs, conventions, scenarios. Everything between those two surfaces is the system's job, not mine. The goal is dark factory mode — lights-off, in the manufacturing sense: I get paged for fires, not for reviews.
-->

---

## DEMO

#### One autonomous cycle. 90 seconds.

<!--
Pre-recorded screencap at 2–4× speed: issue filed → agent claims it → branch → PR opens → checks go green → labels transition → merge. Stand stage right, hands off the clicker, say "I'll let it run" and then SILENCE until it ends. The demo is the non-defensive answer to "is it real?" — evidence beats assertion, and a recording can't demoware-fail you. Cut back to slides immediately.
-->

---

# The container is solid.
# The code inside it is fluid.

#### The container is what makes fluidity safe.

<!--
The thesis. Let the slide sit in silence for a few seconds first. Pour code fast with nothing underneath and you don't get agility — you get the flood: leaked keys, runaway bills, dropped databases. Fluidity is not the absence of structure; it's what you get when the structure moves out of the code and becomes the vessel the code runs inside. And name the heritage, because the man is in the room: the container is Alistair Cockburn's hexagon from 2005 plus Dan North's BDD from 2003, run at autonomous-system scale. Nothing here is new architecture. "Your craft isn't the casualty of this shift. It's the material."
-->

---

# I hold the walls, not the keyboard.

#### No human approval in the routine loop.

<!--
This is the lean-back line — say it plainly and let it cost something. What got pulled out: code review, PR approval, the planning of routine work. Every approval in the day-to-day pipeline is made by another agent. I'm pulled in for high-blast-radius decisions, and I verify direction on a pass — not line by line. My job is to author the conventions the system reviews against, and to hold the boundary it cannot cross. So the obvious question: if not me — who? Next slide.
-->

---

## Forty-seven of what, exactly?

**Maintainers** keep state fresh · **Proposers** grow it · **Pruners** shrink it
**Auditors** verify invariants · **Repairers** fix what broke · **Watchers** budget & escalate
**Promoters** move work through tiers · **Provocateurs** attack the system on purpose

<!--
Pay off the cold-open number — this is the factory's workforce. Walk the categories fast, one breath each; don't lecture the grid. Then the two beats that matter. First: "I designed the first couple up front. The rest accreted, one at a time, each answering a recurring operational problem — and the categories weren't in my sketch. They emerged." VERIFIED from file history: the first two loop files (base_background_loop, pr_unsticker_loop) land Feb 24 — day six. The rest accrete in ones, twos, and threes across four months; the newest entered the registry June 4. Spoken texture option: "The newest loop in that registry is three weeks old. The taxonomy is still growing while I'm standing here." (Caveat: file-date method doesn't follow renames — an Apr 24 ten-file burst is likely a refactor, so keep the claim soft: 'the rest accreted over four months.') Second, land on the provocateurs, because they're the ones that make the room sit up: the factory employs agents whose whole job is to attack it — synthesize adversarial cases from past failures, run them against the system weekly, challenge its own assumptions before reality does. A workforce that maintains, proposes, prunes, audits, repairs, watches, promotes — and red-teams itself. That's who does the work. The next slides are what keeps that workforce honest.
-->

---

## Quality moved from **social** to **structural**.

12,898 tests · 70% coverage floor, CI-enforced · 478 world-scenario tests · 176 regression tests

#### The gates are habits. The blast radius is a wall.

<!--
Senior reviewers and tribal knowledge don't scale to a system that mutates daily — so quality got encoded, and the encoding has a size: nearly thirteen thousand test functions, a seventy-percent coverage floor CI fails below, four hundred seventy-eight scenario tests that exercise the system inside simulated worlds, and a hundred seventy-six regression tests — every bug that ever bit lands with one, so it can never bite twice. (Numbers verified 2026-06-09; refresh with the others.) If you hear "fluid" and think "lower standards," it's exactly backwards: the bar didn't drop, it moved INTO the system. Distinguish the two layers now, because the next slide depends on it: the gates are habits — code the factory can edit. The walls are not.
-->

---

## Why it can't run away

**Per loop:** attempt budgets · kill switches · credit-aware yield
**Across loops:** one owner per work item · dedup · watchers
**Beyond its reach:** destructive ops blocked by hooks · can't raise its own budget · can't touch persisted state

<!--
Containment by construction, three rings — this is the "preventing runaway loops and cascades" promise from the abstract, delivered. Per loop: budgets and kill switches mean no single loop spins forever. Across loops: the label state machine gives every work item exactly one owner, so a local change can't snowball into a storm. And the hard walls live OUTSIDE the code the factory is allowed to edit: it cannot take an action it can't take back. The point isn't that loops never misbehave. It's that misbehavior is bounded, reversible, and in-budget — by construction.
-->

---

## The test chamber

# Given-When-Then was always pointing at the world.

<!--
The boldest claim — give it room. Traditional mocks simulate responses; MockWorld simulates CONDITIONS. The world has state, time, and failure modes you can program: given the API is degraded, given auth is flaky, given the operator has a budget cap — when the loop ticks, then the system yields. Before anything the factory builds reaches reality, it gets exercised in a hostile simulated world. That's not mocking. That's BDD pushed all the way — the "Given" was always pointing past user flows at the whole operating environment. It just took autonomous systems to make that urgent.
-->

---

## Merged at 21:43. Hotfix open by 22:07. Merged 22:25.

# Broken to fixed: 42 minutes.

#### No human in that story.

<!--
A real scene, not a pattern citation — timestamps verified against the PRs (#8460 merged 2026-05-02 21:43:31Z; hotfix #8463 created 22:07:51, merged 22:25:14). Cleanup PR: removed redundant defensive checks, 211 tests green, types clean, merged. Main went red — two test files the change hadn't accounted for. Twenty-four minutes later the hotfix PR was open; eighteen minutes after that it was merged. The entire incident, break to fix, lasted forty-two minutes — while I was doing something else. Read it as a failure and you miss it: the validation didn't gate, it PUSHED. The wrong-but-specific first pass got driven toward right. That's how rightness emerges when wrongness is fast, cheap, and contained.
-->

---

## The artifact I trust most

> *"activate it in gates.toml rather than deleting this test"*

#### A test written to resist the system's own future laziness.

<!-- (quote verified verbatim: tests/test_gates_activation.py:148 — option: cite file:line on the slide as documentary texture) -->

<!--
The hero slide — and the payoff of the identity beat. "I spent years teaching people to write the test first. This is the first test I've ever seen that teaches the NEXT developer — a test written to resist the system's own future laziness, telling whoever comes after to fix reality instead of the test." Not a passing test; a self-defending one. When the codebase fills with artifacts like this, the discipline is real without me enforcing it. TDD didn't get abandoned when I stopped reviewing code. It got projected up a level — from a practice I performed to a property the system defends. This is what "solid" looks like up close. Hold it a beat; it's the emotional center of the middle act.
-->

---

## I don't read the code. I read what it says about itself.

314 wiki entries, regenerated from live pipeline events · 41 named domain terms — **name drift breaks the build** · 91 ADRs · diagrams regenerated on every PR

<!--
The living-knowledge layer — HydraFlow's answer to comprehension debt, and the novelty beat alongside MockWorld. Nobody can read a codebase that rewrites itself daily; Yegge says it plainly — he's never read Beads, 225k lines of his own system's Go. I can't read mine either. The difference is mine is REQUIRED to keep explaining itself: the wiki regenerates from live pipeline events, not from anyone's memory. The architecture diagrams regenerate on every PR. And the sharpest one — the vocabulary is load-bearing: forty-one domain terms live as files in the repo, the glossary auto-extracts from code, and if the code and the glossary disagree about what a word means, CI FAILS. That's Eric Evans' ubiquitous language — the DDD discipline — made executable. Documentation didn't die in this regime. Static documentation died. What replaced it is documentation with a pulse, maintained by the same factory it describes — so the comprehension debt never compounds silently. Which raises the obvious question: if even the explanations are code the factory maintains... (hand straight into the next slide)
-->

---

## What I expect to break

# The container itself going fluid.

#### A softened gate looks like a routine change.

<!--
The honest slide — deliver with conviction, not hedging; the room trusts everything else more after this. The scariest failure isn't a breach. It's a slow softening: a threshold lowered, a skip added, each one defensible, each approved by an agent judging against standards the same drift is relaxing. Gate erosion reads as routine, so it never trips the wire that pulls me in. And yes — I've built a tripwire: there is literally a CI workflow named gates-drift that verifies the branch-protection artifacts still match the gates.toml source of truth and every active gate maps to a real job. But notice what that is: a watcher for the watchers, and it's code too. Turtles, all the way down to one place: the walls cap the damage, and the conventions are mine to keep sound. That's the one job I can't delegate. That's where "stay the engineer" actually bites.
-->

---

## I'm not out here alone.

Steinberger trusts the tests. Cherny keeps a gate.
Yegge babysits the fleet. I trust the walls.

#### Different bets on one question: what holds when you step back?

<!--
Thirty seconds, peers not foils. And Steve returns — I borrowed his question and made the opposite bet on the answer. He built my kind of machine, Gas Town, twenty or thirty agents over a memory system — and his answer is to babysit it; he literally retitled himself "AI babysitter" and gates it on staying vigilant. Mine is to move the watching into the structure so it doesn't depend on me being sharp. Both are live experiments; neither is finished. Then the plant that the turn detonates: "Every one of us, though, is working where failure is LEGIBLE — a red test, a bad diff, a broken build. Hold that."
-->

---

## So: how much of the human comes out?

### For legible software — almost all of it.

<!--
Close the loop on motive two, honestly scoped. Legible software: a bad commit is detectable, a failing test observable, drift auditable, side effects reversible. The factory has something concrete to be sharper about. That's the class HydraFlow lives in, and within it the evidence says yes — the human time per unit of value dropped far enough to change the economics. (beat) "And that's where I expected this talk to end, when I started writing it."
-->

---

## Somewhere in those four months, the reason changed.

# My daughter — Z — wants to make a game.

<!--
The turn — pay off the plant from the Gas Town slide. Introduce her by initial only: "my daughter — Z." Say it plain and a little proud: it's called Poop Scoop Hero. It's real — we have a name, a concept, and she has strong opinions about the dog. Let the room smile; the smile is the door. I started building to maintain a platform. I kept building to answer Steve's question. And then I realized what I was actually holding: not a thing that makes ME better — a thing that could let HER make. (She's "Z" everywhere on slides and stage — minor, public stage.)
-->

---

## The game won't start from zero.

It's born inside the format: one Makefile, the same security, quality, and testing standards, the same CI walls.

#### A blueprint for printing. Follow the spec, get the thing.

<!--
The lessons roll forward — third time now, and say so; the motif pays off here. "v1's collapse became v2's guardrails. v2's guardrails became the factory. And now the factory's discipline becomes the game's birthright." Every HydraFlow-format project inherits the container on day one: the shared make targets, the quality gates, the test pyramid, the CI checks, the walls. Four months of the factory teaching itself discipline, compiled into a blueprint any new repo starts inside. The game gets all of it for free — builds, deploys, regressions, security, every legible failure already guarded. (beat) "Which means the experiment is clean. Every variable the format can check is controlled. There's exactly one it can't." Next slide.
-->

---

## The format checks everything — except the thing that matters most.

# Fun is not a unit test.

<!--
Games dynamite the legibility assumption the whole field shares — that's why this is the frontier and not a hobby footnote. Success is aesthetic. Content is generated, not implemented. "Right" means "this feels good," and there is no green checkmark for a seven-year-old laughing. Every peer on the earlier axis works above the line of legible failure. This experiment goes below it — with everything legible already controlled by the inherited container, so the open question is isolated to exactly the part no test can reach.
-->

---

## Evening: Z tells it what she wants.
## Overnight: the factory builds.
## Morning: Z plays what it made.

# A 3D printer for ideas.

<!--
The image of the close — keep it future tense, this hasn't run yet. "The plan is a ritual: in the evening Z and I describe the thing — instruct Claude, queue the work. The factory prints overnight. In the morning she plays the build and tells it what's wrong." And the symmetry, said quietly: that's already MY morning. The factory runs while I sleep; I wake to what it made and extend what it can do. The experiment is whether that morning can belong to a kid who can't code. One inoculation, one sentence: a 3D printer hands you an object and walks away — this printer maintains what it printed. Patches, balance, live ops. That's the part desktop printing never had.
-->

---

## When making is free, judging is scarce.

Z's "is it fun?" becomes the spec.

<!--
Second-order effect one. If the factory builds anything I can specify, the constraint stops being skill at building — it's knowing what's worth building and whether it's good. For her game that signal lives in her face, not a test suite. And fold the inheritance question in here, spoken: I learned to make by struggling with the making. She might learn to make by directing and judging, never touching syntax. New literacy or lost craft — I genuinely don't know, and I'm the one responsible for getting it right.
-->

---

## My walls protect my repo.

# They don't protect the players.

<!--
End the second-order beats on the gut-punch, not a list. Hooks, credit caps, immutable state — those keep the factory from hurting itself. They say nothing about a shipped experience that's bad, unfair, or worse, for the people on the other end. Who is accountable for software a factory built and a kid published? The floor I built guards the system. It does not guard the player. I don't have an answer. That's why it's here.
-->

---

# Where does the engineer go?

## Into the printer.

#### We'll find out together. I'll let you know.

<!--
Answer the title — for THEM, not just for you. The craft doesn't disappear; it becomes the machine. Everything that made the factory safe — the walls, the gates, the tests that defend themselves — is SOLID-era engineering, projected up a level. Only people with the craft can build a printer worth trusting. "I spent years teaching the craft one engineer at a time. The factory is the same teaching, compiled." So the direction, plainly: "Go build one. It starts smaller than you think — a format: shared make targets, quality gates, a test pyramid, CI walls that every new repo inherits. A blueprint for printing. For your team. For someone who can't code. The engineer goes into the printer — that's where the craft lives now." Then home: "Mine is for Z, and a game about scooping poop. We'll find out together. I'll let you know." Walk off on that.
-->

---

## Thank you

HydraFlow · the FLUID principles · V2V

<!--
References, contact, the essay link. Keep it short; the last real slide was the close.
-->
