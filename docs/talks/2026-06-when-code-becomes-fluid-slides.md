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
- DEMO IS A VIDEO — one pre-recorded screencap of a real cycle at 2–4× speed (issue filed →
  loop claims it → PR opens → checks green → label trail walks → merge), ~60–90s, played in
  silence and landed on the merged freeze-frame; a recording can't demoware-fail on stage.
  TO CAPTURE: pick a cycle with a back-row-readable issue title; show the labels, the green
  checks + label timeline, and the merged actor.
- SCAR SLIDE ("The bad day") needs the author's true specifics — the credit-exhaustion shape is
  reconstructed from the failure mode documented in CLAUDE.md; verify or swap in the real worst day.
- COVERAGE: get the actual % before stage (floor is 70); say both if actual is well above, drop
  the metric if it's near the floor.
- CUT PLAN (live, if behind at the peers slide): drop in this order —
  1. "Testing this used to mean an environment" (speak the pain over the MockWorld slide instead)
  2. "The factory red-teams itself" (point at the provocateur cell on the taxonomy grid)
  3. "The encoding has a size" (speak two of the four numbers over the social→structural slide)
  Never cut: the scar slide, gate erosion, the fork, the turn, the close.
- Numbers verified 2026-06-09: 47 loops (docs/arch/generated/loops.md), 1,644 merged PRs
  (gh search), first commit 2026-02-18. REFRESH BOTH before the stage — the loop registry
  is public on hydraflow.ai and the room will check.
- Quality metrics verified 2026-06-09: 15,838 tests collected (pytest) / 839 test files;
  12 Port classes, 34 Fake classes, per-fake conformance contracts in tests/trust/contracts/
  (github, git, docker, llm, honeycomb, workspace); coverage
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

#### No human reviews its code — none ever has.

<!--
Stage the numbers one at a time, like evidence at trial, not a LinkedIn cadence. "Forty-seven autonomous loops. (beat) More than sixteen hundred merged pull requests. (beat) Four months." Then land the claim flat and let it cost something: "No human reviews its code. None ever has. (beat) I haven't read a line of this code in a year." Don't soften it, don't qualify it — the flinch in the room IS the talk, and the next forty minutes earn the right to have said it. (The "year" reaches back through InsightMesh v2, also entirely vibe-coded with no review — the no-review bet predates the factory, and the next slides pay that off.) Relatability beat, optional: "And before you ask — no, not all sixteen hundred are glamorous. A lot of them are dependency bumps and housekeeping. That's the point. Maintenance is most of software. It does the boring part too." Owning the boring PRs buys more trust than the big number does. If a principal pulls the git log and sees early commits under my name, the answer is precise, not a walk-back: commit identity is not human review — I directed and committed work I never read, and vibe-authoring is not reviewing. The handover curve is still the deepest cut: "Two out of every three commits in the factory were authored by the factory; last month they out-committed me three to one." (Receipts: 1,227 of 1,790 non-merge commits by agent identities; last 30 days agents 305 vs Travis 116. STRONG CANDIDATE for a slide visual — monthly stacked bar, human vs agent commits, the flip is the picture of 'self-building'.) REFRESH NUMBERS before stage — loops from docs/arch/generated/loops.md, PR count from gh. The claim must match the public registry exactly, because someone in row three will pull it up.
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

# August 28, 2025: v1 died.

<!--
Motive one — the relatable one, a confession. InsightMesh: a real internal sales-enablement platform, built the way most of this room is building right now — Cursor, fast, thrilling, barely any review, no strong guardrails. (Stack stays a spoken aside at most — "LangGraph agents, Langfuse traces, the stack you'd expect." Real, not a toy.) "And v1 collapsed under its own weight. I couldn't maintain what I'd made. So on August 28, 2025 — the date's in the git history — I did what every engineer in this room has done at least once: threw it away and started over." This conference's tagline is "you ship it, you own it, you maintain it" — and the word AI changed most isn't ship or own. It's maintain. I didn't need a faster way to write code. I needed help keeping what I'd written alive.
-->

---

## The fork: put the human back in — or build walls?

v2 is still entirely AI-written. Still almost no human review. What changed was the guardrails.

# The version with less structure died. The version with more structure lives.

<!--
The beat that carries the talk in miniature — deliver it slow. "Here's the fork in the road. The obvious fix was to put the human back in the loop — review everything, slow down. I did the opposite. v2 — the version alive today — is still entirely AI-written. What changed was the guardrails: standards, tests, CI walls." The bet — walls over vigilance — was made HERE, ten months before the factory existed. The lessons rolled forward — that's roll number one, and it won't be the last time you hear that phrase tonight. Vibe to Value — the methodology name is this journey, compressed to three characters.
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

#### One real cycle. Filed to merged. No human in the path.

<!--
Restored to live motion — the stills went flat, and this is the one beat the room needs to SEE move. Pre-recorded screencap at 2–4× speed (a recording can't demoware-fail you on stage): a real issue filed → a loop claims it the moment the label lands → branch → PR opens → checks go green → the label trail walks → merge. Frame it before you hit play: "I filed the intent — that's my whole contribution to what you're about to watch. Everything after this is the factory." Then hand off the clicker, say "I'll let it run," and stay SILENT while it plays — the confidence is the whole move; narrating over it undercuts it. Land on the final merged frame and speak the punchline to the freeze: "Issue to merged production code. An agent planned it, implemented it, wrote the tests, reviewed it, merged it. Notice what's missing from that list: me. (beat) It did this sixteen hundred times in four months." Cut back to slides — don't linger past the punchline. (Pick a cycle whose issue title reads from the back row.)
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
This is the lean-back line — say it plainly and let it cost something. What got pulled out: code review, PR approval, the planning of routine work. Every approval in the day-to-day pipeline is made by another agent. I'm pulled in for high-blast-radius decisions, and I verify direction on a pass — not line by line. My job is to author the conventions the system reviews against, and to hold the boundary it cannot cross. So the obvious question: if I'm not the one watching the code, what is? Hold that question — the rest of this act is the whole answer, and it starts with who does the work. Next slide.
-->

---

## Forty-seven of what, exactly?

**Maintainers** keep state fresh · **Proposers** grow it · **Pruners** shrink it
**Auditors** verify invariants · **Repairers** fix what broke · **Watchers** budget & escalate
**Promoters** move work through tiers · **Provocateurs** attack the system on purpose

<!--
Pay off the cold-open number — this is the factory's workforce. Walk the categories fast, one breath each; don't lecture the grid. Then: "I designed the first couple up front. The rest accreted, one at a time, each answering a recurring operational problem — and the categories weren't in my sketch. They emerged." VERIFIED from file history: the first two loop files (base_background_loop, pr_unsticker_loop) land Feb 24 — day six. The rest accrete in ones, twos, and threes across four months; the newest entered the registry June 4. Spoken texture option: "The newest loop in that registry is three weeks old. The taxonomy is still growing while I'm standing here." (Caveat: file-date method doesn't follow renames — an Apr 24 ten-file burst is likely a refactor, so keep the claim soft: 'the rest accreted over four months.') Save the provocateurs for the next slide — point at the last cell and say "and that last category deserves its own slide."
-->

---

## The factory red-teams itself.

Provocateurs synthesize adversarial cases from past failures · run them against the system weekly · challenge its assumptions before reality does

<!--
The sit-up beat — the factory employs agents whose whole job is to ATTACK it. CorpusLearningLoop mines past skill failures and synthesizes adversarial cases from them; SkillPromptEvalLoop runs that hostile corpus against the built-in skills every week; the advisor pattern wires a skeptical second opinion into PR review and verification. A workforce that maintains, proposes, prunes, audits, repairs, watches, promotes — and red-teams itself. Nobody told it to be paranoid; I encoded the paranoia once and it became a job category. That's who does the work. The next slides are what keeps that workforce honest.
-->

---

## Quality moved from **social** to **structural**.

Senior reviewers, tribal knowledge, manual discipline — none of it scales to a system that mutates daily.

<!--
The unifying reframe — give it its own breath before the numbers. Quality enforcement used to be social: the senior reviewer who catches it, the tribal knowledge of who-knows-what, the discipline you hope survives the sprint. A system that rewrites itself daily outruns all of that. So HydraFlow doesn't lower the quality bar — it moves the bar INTO the system: validation continuous, governance executable, scenarios authoritative. If you hear "fluid" and think "lower standards," you've got it exactly backwards.
-->

---

## The encoding has a size.

15,800+ tests · 70% coverage floor, CI-enforced · 478 world-scenario tests · 176 regression tests

#### The gates are habits. The blast radius is a wall.

<!--
Numbers one at a time, same trial cadence as the cold open: nearly sixteen thousand tests. Four hundred seventy-eight scenario tests that exercise the system inside simulated worlds. A hundred seventy-six regression tests — every bug that ever bit lands with one, so it can never bite twice. (15,838 collected via pytest 2026-06-09; refresh with the others.) COVERAGE NOTE: to a room of principals, "70% floor" reads as "30% unwatched." Before stage, run coverage and get the ACTUAL number — if it's meaningfully above 70, say both ("the enforced floor is 70; actual is X"); if it's near 70, drop coverage from the slide entirely and let the test counts carry it. The floor's real story is structural anyway: the build fails below it, and the factory can't quietly lower it. Then the distinction the next slide depends on: the gates are habits — code the factory can edit. The walls are not. Hold that line; it's the hinge of the whole middle act — and it sets up the obvious question: what ARE the walls? The next slide names them.
-->

---

## Why it can't run away

**Per loop:** attempt budgets · kill switches · credit-aware yield
**Across loops:** one owner per work item · dedup · watchers
**Beyond its reach:** destructive ops blocked by hooks · can't raise its own budget · can't touch persisted state

<!--
Containment by construction, three rings — this is the "preventing runaway loops and cascades" promise from the abstract, delivered. Per loop: budgets and kill switches mean no single loop spins forever. Across loops: the label state machine gives every work item exactly one owner, so a local change can't snowball into a storm. And the hard walls live OUTSIDE the code the factory is allowed to edit: it cannot take an action it can't take back. The point isn't that loops never misbehave. It's that misbehavior is bounded, reversible, and in-budget — by construction. But "bounded, reversible, in-budget" is a CLAIM. How do you test a claim like that — without a staging org, real tokens, and a live bill running while you do? That's the next move.
-->

---

## Testing this used to mean an *environment*.

A staging GitHub org. Real tokens. Rate limits. Flaky networks. An LLM bill.

<!--
Start with the pain everyone in the room knows: "Testing a system like this used to mean an ENVIRONMENT. A staging GitHub org. Real tokens. Rate limits. A flaky network between you and everything. An LLM bill running while your tests do. And a test run measured in minutes — if it didn't fall over first." Let them nod. The next slide is the escape.
-->

---

## MockWorld: the test chamber

GitHub, git, Docker, the LLM itself — **12 Ports, 34 Fakes**, each pinned to its real adapter by a conformance contract.

#### A mock fakes a response. A Fake world has state, time, and failure modes.

<!--
The move: every external dependency the factory touches enters through a typed Port — and MockWorld swaps a Fake in at that boundary. These aren't traditional mocks. A mock simulates a RESPONSE — one call, one canned answer. A Fake world simulates CONDITIONS: it has state that persists, time that passes, and failure modes you can program. The entire factory runs inside a simulated world, on a laptop, in seconds — no tokens, no staging org, no bill. And the fakes can't quietly lie: every one is held to a conformance contract test that pins its behavior to the real adapter's (tests/trust/contracts/ — fake_github, fake_git, fake_docker, fake_llm, all of them). That's the answer to the question someone's already drafting for Q&A: "how do you know the fake matches reality?" The contract knows. Pre-arm the sharper jab too — "you faked the LLM, the only dependency that matters": the fake LLM tests the ORCHESTRATION — what the loops do when the model is slow, wrong, or rate-limited. Agent quality itself is validated one tier up, in the sandbox layer, against real models. Different layer, different question, both covered.
-->

---

# Given-When-Then was always pointing at the world.

<!--
The boldest claim — alone on the slide, give it room. "Given GitHub is rate-limiting. Given auth is flaky. Given the operator's budget is capped. WHEN the loop ticks — THEN the system yields its attempt budget. We always wrote tests in that shape. The 'Given' was never just user flows — it was always pointing past them, at the whole operating environment. It just took autonomous systems to make that urgent." Four hundred seventy-eight scenario tests run the factory through hostile worlds before anything it builds touches reality. Cockburn's ports plus North's scenarios — the heritage line again, briefly: nothing here is new; the combination is. So the only question left in this act: does it actually hold? Two days from the log answer it — one good, one bad.
-->

---

## Merged at 21:43. Hotfix open by 22:07. Merged 22:25.

# Broken to fixed: 42 minutes.

#### No human in that story.

<!--
A real scene, not a pattern citation — timestamps verified against the PRs (#8460 merged 2026-05-02 21:43:31Z; hotfix #8463 created 22:07:51, merged 22:25:14). Cleanup PR: removed redundant defensive checks, 211 tests green, types clean, merged. Main went red — two test files the change hadn't accounted for. Twenty-four minutes later the hotfix PR was open; eighteen minutes after that it was merged. The entire incident, break to fix, lasted forty-two minutes — while I was doing something else. Read it as a failure and you miss it: the validation didn't gate, it PUSHED. The wrong-but-specific first pass got driven toward right. That's how rightness emerges when wrongness is fast, cheap, and contained. Then the handoff that earns the next slide: "That was the good day. I owe you a bad one."
-->

---

## The bad day

# It burned its retry budgets against an empty credit account.

#### The loops did what loops do. All of them. At once.

<!--
THE SCAR SLIDE — the credibility purchase. [VERIFY THE DETAILS OR SWAP IN YOUR TRUE WORST DAY — the shape below is reconstructed from the failure mode documented in the repo's own rules (CLAUDE.md: CreditExhaustedError silently eaten → "the loop burns attempt budget against an exhausted billing signal"). Tell it with the real specifics only you have: when, how long, what it cost, how you found it.] The relatable shape: "The billing API said no. But the error came back wrapped as a generic failure — and loops do what loops do with generic failures. They retried. Every loop, independently, burning its attempt budget against an account that could not say yes. Anyone who's been paged for a retry storm knows exactly what this looks like. My factory built me one." The recovery, briefly: the fix wasn't heroics, it was a rule — every subprocess runner now re-raises credit exhaustion past the generic handler, and that rule lives in the repo where every future agent inherits it. The lesson, plainly: "The factory doesn't fail like a junior engineer. It fails like a distributed system — dumb, persistent, parallel. The walls held: budgets capped it, nothing was destroyed, everything was reversible. But I want you to have the real picture: this thing has bad days, and the bad days are why half those forty-seven loops exist." This slide buys more trust than every green checkmark in the deck. Don't rush it, don't soften it. Then the handoff into the artifact: "And the day after a bad day, this is the kind of thing the factory leaves behind."
-->

---

## The artifact I trust most

> *"activate it in gates.toml rather than deleting this test"*

#### A test written to resist the system's own future laziness.

<!-- (quote verified verbatim: tests/test_gates_activation.py:148 — option: cite file:line on the slide as documentary texture) -->

<!--
The hero slide — and the payoff of the identity beat. "I spent years teaching people to write the test first. This is the first test I've ever seen that teaches the NEXT developer — a test written to resist the system's own future laziness, telling whoever comes after to fix reality instead of the test." Not a passing test; a self-defending one. When the codebase fills with artifacts like this, the discipline is real without me enforcing it. TDD didn't get abandoned when I stopped reviewing code. It got projected up a level — from a practice I performed to a property the system defends. This is what "solid" looks like up close. Hold it a beat; it's the emotional center of the middle act. Then the turn into the last move: "I can't read the code that grows artifacts like this — so I stopped trying. I read what the code says about itself instead."
-->

---

## I don't read the code. I read what it says about itself.

314 wiki entries, regenerated from live pipeline events · 91 ADRs · architecture diagrams regenerated on every PR

<!--
The living-knowledge layer — HydraFlow's answer to comprehension debt. Nobody can read a codebase that rewrites itself daily; Yegge says it plainly — he's never read Beads, 225k lines of his own system's Go. I can't read mine either. The difference is mine is REQUIRED to keep explaining itself: the wiki regenerates from live pipeline events, not from anyone's memory. The architecture diagrams regenerate on every PR. Documentation didn't die in this regime. STATIC documentation died. What replaced it is documentation with a pulse, maintained by the same factory it describes — so the comprehension debt never compounds silently.
-->

---

## The vocabulary is load-bearing.

41 domain terms live as files in the repo. The glossary auto-extracts from code.

# If the code and the glossary disagree, the build fails.

<!--
The sharpest claim in the knowledge layer — give it its own slide because no one else can say it. Words drift in every codebase: "task" starts meaning three things, "promote" quietly changes semantics, and six months later nobody can read the system because the names lie. Here the names CAN'T lie: forty-one domain terms are files in the repo, the glossary extracts from the live code, and if they disagree about what a word means, CI fails the build. That's Eric Evans' ubiquitous language — the DDD discipline — made executable. The factory is not allowed to redefine a word without telling me. Which raises the obvious question: if even the explanations and the vocabulary are code the factory maintains... (hand straight into the next slide)
-->

---

## What I expect to break

# The container itself going fluid.

#### A softened gate looks like a routine change.

<!--
The honest slide — deliver with conviction, not hedging; the room trusts everything else more after this. The scariest failure isn't a breach. It's a slow softening: a threshold lowered, a skip added, each one defensible, each approved by an agent judging against standards the same drift is relaxing. Gate erosion reads as routine, so it never trips the wire that pulls me in. And yes — I've built a tripwire: there is literally a CI workflow named gates-drift that verifies the branch-protection artifacts still match the gates.toml source of truth and every active gate maps to a real job. But notice what that is: a watcher for the watchers, and it's code too. And name the sharper version of the same problem before someone in row three does: "My test scenarios live in the repo the factory edits. StrongDM holds their evaluations OUTSIDE the system so it can't optimize against them. Mine are inside. What I have today: fresh-eyes review by subagents with no conversation context, conformance contracts the fakes can't dodge, a sandbox tier with real dependencies. What I don't have yet: held-out evals. It's the next wall I owe the system." Saying the gap out loud is the credibility move — this room can smell an unaddressed weakness from the lobby. Turtles, all the way down to one place: the walls cap the damage, and the conventions are mine to keep sound. That's the one job I can't delegate. That's where "stay the engineer" actually bites.
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

<!--
The image of the close — keep it future tense, this hasn't run yet. "The plan is a ritual: in the evening Z and I describe the thing — instruct Claude, queue the work. The factory prints overnight. In the morning she plays the build and tells it what's wrong." And the symmetry, said quietly: that's already MY morning. The factory runs while I sleep; I wake to what it made and extend what it can do. The experiment is whether that morning can belong to a kid who can't code.
-->

---

# A 3D printer for ideas.

#### Except this printer maintains what it prints.

<!--
Name the metaphor alone, then inoculate it in the same breath — someone in the room is already thinking "3D printing was supposed to democratize manufacturing and mostly made trinkets." Own it: "I know what happened to desktop 3D printing. The difference between a trinket machine and a real tool was always the rigor of the machine. And there's one more difference here: a 3D printer hands you an object and walks away. This printer maintains what it printed — patches, balance, live ops, forever. That's the part desktop printing never had, and it's the part that was the whole problem to begin with." Maintain — the tagline word, closing its own loop from the InsightMesh slide.
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

=== Q&A ARMORY — the four hardest questions, answered in advance ===

1. "What stops it from optimizing against its own tests?" — Concede the gap first: "Honestly?
   Less than I want. My scenarios live in the repo it edits; StrongDM holds theirs outside the
   system, and that's the stricter discipline. What I have: fresh-eyes subagent review with no
   conversation context, conformance contracts pinning every fake to its real adapter, and a
   sandbox tier with real dependencies. Held-out evals are the next wall I owe it." The
   concession IS the answer — this room trusts named gaps over claimed completeness.

2. "What does it cost?" — Don't deflect; you have real numbers. "I'll give you an actual
   receipt: one night, thirty merged PRs, $125.19. The running average is three to seven
   dollars per merged pull request. There's a CostBudgetWatcher loop enforcing daily caps per
   source, and spend is attributed per-loop on the dashboard, so I always know that number. The honest pattern
   underneath it: we've spent more engineering on validation and governance than we've ever
   spent on inference." If pressed on whether it scales: the caps are the answer — the factory
   cannot outspend its budget by construction; cost is a wall, not a hope.

3. "You're going to let a factory with no human review ship software your KID publishes?" —
   Don't dodge; this is the player-blast-radius slide restated as an accusation. "That's exactly
   the right question, and it's why the experiment is the talk's ending and not its victory lap.
   The walls protect my repo today. Before anything she makes reaches another player, the walls
   have to reach the player too — that's a prerequisite of the experiment, not an afterthought.
   And the only test that gates a release is the one that can't be automated: us, playing it."

4. "Aren't 47 loops just sprawl? / cron jobs with opinions?" — "Fair — count alone isn't
   capability. Two things keep it from being sprawl: every loop honors one cross-cutting
   contract (kill switch, budget, idempotent checkpoints, auto-discovery test), and the
   taxonomy means a new loop slots into a category instead of inventing a pattern. Sprawl is
   47 special cases. This is 8 patterns with 47 instances."
-->
