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
- Daughter's name kept out of slide text pending the author's OK (minor's name, public stage).
- Numbers verified 2026-06-09: 47 loops (docs/arch/generated/loops.md), 1,644 merged PRs
  (gh search), first commit 2026-02-18. REFRESH BOTH before the stage — the loop registry
  is public on hydraflow.ai and the room will check.
- The her-and-Claude ritual has NOT run yet. Keep it future tense on stage. The close is
  "I'll let you know," and that only stays true if nothing earlier pretends it already happened.
- TODO: pick one concrete InsightMesh failure moment for S5 (the vibing-hit-the-wall scene).
-->

# When Code Becomes Fluid

#### Where does the engineer go?

Accelerate Chicago 2026

<!--
Hold the title card five seconds. Don't speak. Don't open on a thesis. The first words out of your mouth are the birth scene.
-->

---

## Four months ago, I made a folder inside another repo.

# Three days later, it left.

<!--
Say it slow, like you're still slightly unsettled by it. "Four months ago I created a folder inside an internal platform I'd vibe-coded. Three days later, what was in that folder got pulled out into its own repository. (beat) It has been building itself ever since." Eerie, not boastful. Anyone can claim they don't read their code — this opening, nobody else has. Don't explain yet. Let the room want the chronology.
-->

---

## It has been building itself ever since.

# 47 loops. 1,600+ merged PRs.

#### I have never reviewed its code. No human has.

<!--
Stage the numbers one at a time, like evidence at trial, not a LinkedIn cadence. "Forty-seven autonomous loops. (beat) More than sixteen hundred merged pull requests. (beat) Four months. (beat) And I have never reviewed its code. No human has." REFRESH NUMBERS before stage — loops from docs/arch/generated/loops.md, PR count from gh. The claim must match the public registry exactly, because someone in row three will pull it up.
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

An internal platform I vibe-coded. Agents, retrieval, scheduled tasks, observability.

# Vibe shipped it. Vibe couldn't keep it alive.

<!--
Motive one — the relatable one. InsightMesh: a real production sales-enablement platform, vibed the way most of this room is building right now. (Stack stays a spoken aside at most — "LangGraph agents, Langfuse traces, the stack you'd expect." Real, not a toy.) It shipped. It worked. Then it had to LIVE. [TODO: insert the one concrete failure moment here — the scene where vibing visibly ran out.] This conference's tagline is "you ship it, you own it, you maintain it" — and the word AI changed most isn't ship or own. It's maintain. I didn't need a faster way to write code. I needed help keeping what I'd written alive. That's where everyone on this road ends up. Vibe to Value — the methodology name is this journey, compressed to three characters.
-->

---

## Then Steve Yegge published *Gas Town*.

#### January 1, 2026.

# How much of the human can you pull out — and what breaks?

<!--
Motive two — the question. Be honest: Gas Town was the catalyst, not a parallel discovery. Steve showed the operational thing was buildable — a fleet of agents, an orchestrator, a human babysitting the swarm. I couldn't put the question down. Seven weeks later: first commit, February 18 — inside the InsightMesh repo, because it was born as a maintenance helper for the thing I'd vibed. Three days later it outgrew its host and moved into its own repo. Then the plant, one line, move on: "And somewhere in the four months since, the reason I was building changed. I'll get there."
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
This is the lean-back line — say it plainly and let it cost something. What got pulled out: code review, PR approval, the planning of routine work. Every approval in the day-to-day pipeline is made by another agent. I'm pulled in for high-blast-radius decisions, and I verify direction on a pass — not line by line. My job is to author the conventions the system reviews against, and to hold the boundary it cannot cross. The next four slides are what holds the line instead of me.
-->

---

## Quality moved from **social** to **structural**.

#### The gates are habits. The blast radius is a wall.

<!--
Senior reviewers and tribal knowledge don't scale to a system that mutates daily — so quality got encoded. Validation runs continuously. Governance is executable. Scenarios are the spec. If you hear "fluid" and think "lower standards," it's exactly backwards: the bar didn't drop, it moved INTO the system. Distinguish the two layers now, because the next slide depends on it: the gates are habits — code the factory can edit. The walls are not.
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

## Merged at 21:43. Main red 42 minutes later.

# Fixed 42 minutes after that.

#### No human in that story.

<!--
A real scene, not a pattern citation. Cleanup PR last month: removed redundant defensive checks, 211 tests green, types clean, merged. Forty-two minutes later main was red — two test files the change hadn't accounted for. The hotfix landed forty-two minutes after that, end to end, while I was doing something else. Read it as a failure and you miss it: the validation didn't gate, it PUSHED. The wrong-but-specific first pass got driven toward right. That's how rightness emerges when wrongness is fast, cheap, and contained.
-->

---

## The artifact I trust most

> *"activate it in gates.toml rather than deleting this test"*

#### A test written to resist the system's own future laziness.

<!--
The hero slide — and the payoff of the identity beat. "I spent years teaching people to write the test first. This is the first test I've ever seen that teaches the NEXT developer — a test written to resist the system's own future laziness, telling whoever comes after to fix reality instead of the test." Not a passing test; a self-defending one. When the codebase fills with artifacts like this, the discipline is real without me enforcing it. TDD didn't get abandoned when I stopped reviewing code. It got projected up a level — from a practice I performed to a property the system defends. This is what "solid" looks like up close. Hold it a beat; it's the emotional center of the middle act.
-->

---

## What I expect to break

# The container itself going fluid.

#### A softened gate looks like a routine change.

<!--
The honest slide — deliver with conviction, not hedging; the room trusts everything else more after this. The scariest failure isn't a breach. It's a slow softening: a threshold lowered, a skip added, each one defensible, each approved by an agent judging against standards the same drift is relaxing. Gate erosion reads as routine, so it never trips the wire that pulls me in. The walls cap the damage — but the conventions are mine to keep sound. That's the one job I can't delegate. That's where "stay the engineer" actually bites.
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

# My daughter wants to make a game.

<!--
The turn — pay off the plant from the Gas Town slide. Say it plain and a little proud: it's called Poop Scoop Hero. It's real — we have a name, a concept, and she has strong opinions about the dog. Let the room smile; the smile is the door. I started building to maintain a platform. I kept building to answer Steve's question. And then I realized what I was actually holding: not a thing that makes ME better — a thing that could let HER make. (Name stays off the slide — minor, public stage.)
-->

---

## Her game breaks every rule the factory relies on.

# Fun is not a unit test.

<!--
Games dynamite the legibility assumption the whole field shares — that's why this is the frontier and not a hobby footnote. Success is aesthetic. Content is generated, not implemented. "Right" means "this feels good," and there is no green checkmark for a seven-year-old laughing. Every peer on the previous axis works above the line of legible failure. This experiment goes below it.
-->

---

## Evening: she tells it what she wants.
## Overnight: the factory builds.
## Morning: she plays what it made.

# A 3D printer for ideas.

<!--
The image of the close — keep it future tense, this hasn't run yet. "The plan is a ritual: in the evening she and I describe the thing — instruct Claude, queue the work. The factory prints overnight. In the morning she plays the build and tells it what's wrong." And the symmetry, said quietly: that's already MY morning. The factory runs while I sleep; I wake to what it made and extend what it can do. The experiment is whether that morning can belong to a kid who can't code. One inoculation, one sentence: a 3D printer hands you an object and walks away — this printer maintains what it printed. Patches, balance, live ops. That's the part desktop printing never had.
-->

---

## When making is free, judging is scarce.

Her "is it fun?" becomes the spec.

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
Answer the title — for THEM, not just for you. The craft doesn't disappear; it becomes the machine. Everything that made the factory safe — the walls, the gates, the tests that defend themselves — is SOLID-era engineering, projected up a level. Only people with the craft can build a printer worth trusting. "I spent years teaching the craft one engineer at a time. The factory is the same teaching, compiled." So the direction, plainly: "Go build one. For your team. For someone who can't code. The engineer goes into the printer — that's where the craft lives now." Then home: "Mine is for a seven-year-old and a game about scooping poop. We'll find out together. I'll let you know." Walk off on that.
-->

---

## Thank you

HydraFlow · the FLUID principles · V2V

<!--
References, contact, the essay link. Keep it short; the last real slide was the close.
-->
