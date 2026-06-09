---
marp: true
theme: default
paginate: true
---

<!--
Speaker deck for "When Code Becomes Fluid." Story-driven, not a patterns dump.
Slides are deliberately sparse; the narrative lives in the speaker notes.
Default Marp theme — brand visuals to be layered later.
NOTE: daughter's name kept out of slide text pending the author's OK (minor's name, public stage).
-->

# When Code Becomes Fluid

#### Where does the engineer go?

Accelerate Chicago 2026

<!--
Don't open on the thesis. Let the title sit for a beat, then go straight to the kid. The whole talk is a story with one question underneath it, and I want them carrying the question, not a framework.
-->

---

## My daughter wants to make a game.

# It is called *Poop Scoop Hero*.

<!--
Say it plain and a little proud. It is real: we have a name, a concept, and she has strong opinions about the dog. Let the room smile at the title — that smile is the hook. Then the turn: I don't want to *mock up* a game with her. I want us to build it, ship it, and keep it running. Just the two of us.
-->

---

## Shipping a game is a team's job.

Art. Code. Balance. Patches. Live ops.

Not a parent and a kid on a Saturday.

<!--
Spell out everything a real, maintained game needs, and how none of it fits a parent-and-kid weekend. So one of two things is true: the dream is too big, or the way we make software has to change. This talk is what happened when I bet on the second one.
-->

---

## So I didn't build a team.

# I built a factory.

#### Intent in. Software out.

<!--
Name HydraFlow here, not as a product, as the thing I built so the Poop Scoop Hero dream could exist. You file intent. The system plans, implements, tests, reviews, and merges. Humans provide intent and tests. Everything between is the system's job.
-->

---

## For decades, code was identity

Competence. Mastery. Control.

Then AI moved the bottleneck.

<!--
The discomfort in the room isn't about productivity. It's that code was how we proved we were good. AI didn't just make code cheaper; it moved the bottleneck off implementation. The question stops being "can AI write code" (yes, boring) and becomes "how do humans govern software that rewrites itself."
-->

---

## The fear is letting go.

## The bet is the opposite.

#### You earn fluid code by making the foundation more solid.

<!--
This is the thesis. Pour code fast with nothing underneath and you don't get agility, you get a flood: the leaked keys, the runaway bills, the dropped database. All the same failure, fluid with no vessel. Fluidity is not the absence of structure. It is what you get when the structure moves out of the code and becomes the container the code runs inside. The more solid the container, the more recklessly fluid you can be on top of it.
-->

---

# I do not review code.

#### No human approval in the routine loop.
#### I hold the walls, not the keyboard.

<!--
This is the line that makes people lean back. Every approval in the day-to-day pipeline is made by another agent. I am pulled in for high-impact decisions and I verify direction on a pass, not line by line. My job is to author the conventions the system reviews against, and to hold the boundary it cannot cross.
-->

---

## I'm not out here alone.

Steinberger trusts the tests. Cherny keeps a gate.
Yegge babysits the fleet. I trust the walls.

#### Same machine. Different bets on one question: what holds when you step back?

<!--
Social-proof beat, placed right after "I don't review code" on purpose, while the room is still leaning back. Name the convergence fast: Steinberger and Cherny both say stop prompting and build loops; Addy Osmani named it loop engineering. The thesis is consensus now, so I don't have to sell it. Then put us on one axis: how much human review stays in the loop. Steinberger ships on green tests without reading the code. Yegge built my kind of machine, Gas Town plus a memory system running a fleet of twenty or thirty agents, and his answer is to babysit it. His word, he literally retitled himself AI babysitter and gates it on staying vigilant. Mine is to move the watching into the structure so it doesn't depend on me being sharp. Deliver this as peers, not a scoreboard, we made different bets on the same hard problem. Close on the shared assumption: all of us are working where failure is legible, which is exactly what I'm about to question with games.
-->

---

## Is it real?

Months, not years. Hundreds of autonomous cycles.

It modifies its own codebase.

<!--
Ground it. First commit February 18, 2026. It started changing its own code within days of working. Substantial features converge over three to five rounds of the system's own fresh-eyes review before they merge. Show a real diff here if you have a screenshot.
-->

---

## The artifact I trust most

> *"activate it in gates.toml rather than deleting this test"*

A test written to resist the system's own future laziness.

<!--
This is the hero slide. Not a passing test, a test that anticipates the failure mode of the system over time and tells the next agent to fix reality instead of the test. When the codebase is full of artifacts like this, the discipline is real and self-defending. This is what "solid" looks like up close.
-->

---

## Why it doesn't collapse

Quality moved from **social** to **structural**.

#### The gates are habits. The blast radius is a wall.

<!--
Senior reviewers and tribal knowledge don't scale to a system that mutates daily, so quality got encoded: continuous validation, executable governance, scenarios as the spec. The factory can rewrite what it checks, the gates are just code. But it cannot take an action it can't take back: destructive ops are blocked by hooks, it can't raise its own budget, it can't touch persisted state. Habits it can edit. Walls it can't.
-->

---

## What I expect to break

The container itself going fluid.

#### A softened gate looks like a routine change.

<!--
The honest slide. The scariest failure isn't a breach, it's a slow softening: a threshold lowered, a skip added, each one defensible, each one approved by an agent judging against standards the same drift is relaxing. And gate-erosion reads as routine, so it never trips the wire that pulls me in. The walls cap the damage; the conventions are mine to keep sound. This one I can't delegate.
-->

---

## So: can it evolve and maintain software with one person steering?

### For legible software, the evidence says yes.

<!--
Legible software: a bad commit is detectable, a failing test is observable, drift is auditable. The factory has something concrete to be sharper about. That's the class HydraFlow lives in, and within it, solo works. The human time per unit of value dropped far enough to change the economics.
-->

---

## Games break the rule.

# Fun is not a unit test.

<!--
Here's the turn back to Zen. Games deliberately break the legibility assumption. Success is aesthetic. Content is generated, not implemented. "Right" means "this feels good," and there is no green checkmark for that. So the real next experiment is the one I actually care about: can the factory build, maintain, and publish *Poop Scoop Hero* with one parent steering, in a domain where the only test that matters is a kid laughing.
-->

---

# Where to next

## *Poop Scoop Hero*, built and run by the factory.

#### And the part I keep thinking about: what happens after.

<!--
This is the parting note. Not "and we shipped it, the end." The honest move is to name the second-order effects, the issues that arrive *because* this works, not despite it. The next four slides are questions I don't have answers to. That's why they're the close.
-->

---

## Second-order effect: taste becomes the scarce thing

When making is free, the bottleneck moves from **building** to **judging**.

Her "is it fun" becomes the spec.

<!--
If the factory builds anything I can specify, the constraint is no longer skill at building. It's knowing what's worth building and whether it's good. For a game that signal lives in a seven-year-old's face, not a test suite. The scarce input flips from labor to judgment, and judgment doesn't scale the way compute does.
-->

---

## Second-order effect: abundance kills scarcity

If anyone can ship a game, a game stops being scarce.

Creation was the wall. Now discovery is.

<!--
The marginal cost of a finished, maintained game falls toward zero for a solo operator. Multiply that across everyone. The constraint moves downstream to attention and curation. We are about to find out what a world of effectively-free software does to the value of any one piece of it.
-->

---

## Second-order effect: what does she inherit?

If the factory builds, the craft she learns is **judgment and intent**, not syntax.

New literacy, or lost craft?

<!--
I learned to make by struggling with the making. She might learn to make by directing and judging, never touching the syntax. I genuinely don't know if that's a loss or the next literacy. It's the question I'm least equipped to answer and most responsible for getting right.
-->

---

## Second-order effect: the blast radius reaches players

My walls protect my repo.

They don't protect the people who play what the factory shipped.

<!--
Hooks, credit caps, immutable state, those keep the factory from hurting itself. They say nothing about a shipped experience that is bad, unfair, or worse, for the people on the other end. Who is accountable for software a factory built and a kid published? The floor I built guards the system. It does not guard the player.
-->

---

# I don't have these answers.

## That's the next build: *Poop Scoop Hero*, with her, in the open.

#### We'll find out together. I'll let you know.

<!--
Bookend. Open on the kid, close on the kid. The talk isn't "I solved autonomous software." It's "I built the factory, here's what it taught me, and here's the honest edge of what I know, told through the thing I most want to be true." Walk off on "I'll let you know."
-->

---

## Thank you

HydraFlow · the FLUID principles · V2V

<!--
References, contact, the essay link. Keep it short; the last real slide was the close.
-->
