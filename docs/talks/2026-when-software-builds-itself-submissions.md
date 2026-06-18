# "When Software Builds Itself" — CFP submissions

The friction/leadership-framed spinoff of the Accelerate Chicago talk
("Self-Building Software / When Code Becomes Fluid"). This file tracks where the
talk has been submitted and the open CFP pipeline, plus a second talk
("Observability is the Control Plane for Agent Systems," AGNTCon + MCPCon).
CFP statuses change weekly, re-verify each live page before relying on a deadline.

**Submitted as of 2026-06-18:** CTO Craft Con (leadership), Build Stuff (45-min),
BeyondConf (45-min), Platform Engineering Day @ KubeCon NA (25-min) for "When Software
Builds Itself"; AGNTCon + MCPCon Europe and North America for "Observability is the
Control Plane for Agent Systems." Six submissions, two talks.

---

## Submitted

### CTO Craft Con: London 2027
- **Status:** Submitted 2026-06-18. Awaiting selection.
- **Conference:** Engineering-leadership audience (CTOs, VPs, directors). London, ~Mar 15–17 2027. Pillars: Leadership, Culture, Technology, Wellbeing.
- **Pillars selected:** Leadership (primary) + Technology.
- **Deadline:** Not published on the CFP page; confirm via hannah@ctocraft.com.
- **CFP:** https://conference.ctocraft.com/london/

**Title submitted:** When Software Builds Itself: Where Do Your Engineers Go?
*(alternates considered: "What's Left to Lead?"; "The Friction Has to Go Somewhere")*

**Synopsis (leadership-framed):**

> I ran the experiment most engineering leaders are only debating: I took the human out of the loop. For months, an autonomous system has filed, designed, tested, reviewed, and merged its own code. No human reviews it. None ever has. This is not a tooling talk. It is a field report on what that does to an engineering organization.
>
> When code generation becomes free, two things move. Value moves to judgment: deciding what is worth building and whether it is any good. And risk moves to a question your org chart does not answer: who is accountable for what a machine built and a human shipped?
>
> I will walk through what I learned running it. Why your senior reviewers do not scale to a system that rewrites itself daily, so quality has to move from social to structural. Where your engineers' value goes when typing is no longer the job. And the governance gap I hit and still have not fully closed.
>
> You will leave with a clear-eyed model for where engineering leadership, and the engineer, goes when making software costs almost nothing, plus an honest account of what I got wrong.

**Key takeaways:**
- Why quality has to move from social (trusting reviewers and discipline) to structural (encoded standards a system cannot bypass) once code changes faster than people can review it.
- Where engineers' value relocates when generation is free, from producing code to exercising judgment, and what that does to hiring, leveling, and leading.
- The accountability gap autonomous delivery opens: who owns what a machine built and a human shipped, and an honest look at the governance I have and don't.

**One-sentence bio (confirm exact title before reuse):**
> Travis Frisinger is a principal-level engineer at 8th Light who taught test-driven development to hundreds of engineers and runs tddbuddy.com; for the past year he has handed his own engineering discipline to an autonomous system to find out what is left for the human.

**Follow-ups:** add previous-talk links (Accelerate Chicago, GOTO) if not already in; confirm deadline by email.

### Build Stuff 2026: Vilnius
- **Status:** Submitted 2026-06-18. **45-min slot** (full talk fits, no cut needed). Awaiting selection.
- **Conference:** Vilnius, LT, Dec 2–4 2026. Builder/craft + AI-native + leadership audience. Tracks: AI-Native Software Development, Developer Craft & Code Quality, Engineering Leadership. Travel + lodging reportedly covered (verify).
- **CFP:** https://buildstuff.events/pages/call-for-papers

**Title submitted:** When Software Builds Itself: Someone Still Has to Engineer It

**Speaker tagline (6 words, leadership + AI):** "Leading engineering in the agentic age" *(confirm which you actually used; alt offered: "AI ships code, leaders own it")*

**Areas of expertise:** Software craft & code quality, AI agents & agentic systems, software architecture, engineering leadership

**Target audience:** Senior engineers, architects, and engineering leaders (tech leads through CTO) bringing AI agents into how their teams build, who care about getting AI-built software to production safely, not just to a demo. Intermediate-to-senior; a field report and a way of thinking, not a hands-on tutorial.

**Abstract (293 words):**

> Generating code is easy now. Getting it to production safely is the hard part, and that part is still engineering.
>
> Since early this year I have run an experiment to prove it: I handed my engineering discipline to an autonomous system and stepped out of the loop. It files work, designs it, writes the tests, implements, reviews itself, and merges. No human in the routine path. No one reads the code it produces. It has shipped real software that way for months.
>
> It should have produced slop. It didn't, and the reason is the whole talk. When code generation becomes nearly free, the engineering does not disappear. It moves. It moves out of the typing and into the things that actually decide whether software is any good: the structure it has to fit, the tests that define what working means, the guardrails it cannot cross, and the judgment about whether it should ship at all. Take those away and you don't get speed. You get a confident machine shipping plausible, wrong code at scale.
>
> This is a field report from inside that system, built for people who care about craft, not hype. I will show you how the discipline gets encoded so it holds without a human watching, how quality moves from something a senior reviewer catches to something the system enforces, and the night it failed anyway and what that taught me. You will leave with a concrete model for where the engineering goes when the code writes itself, why "someone still has to engineer it" is the most important sentence in this shift, and an honest account of the parts I still have not solved.
>
> Whether you lead a team or write the code, the job is moving. This is where it goes.

**Key takeaways:**
- Where the engineering goes when code is nearly free: a concrete model of value moving out of typing and into the structure, tests, guardrails, and judgment that decide what ships.
- How to make quality structural, not social: why reviewers and team discipline don't scale to a system that changes faster than anyone can review, and how to encode the bar so it holds without a human watching.
- What it really takes to get AI-built code to production safely, and the failure mode when you skip it (a confident machine shipping plausible, wrong code at scale).
- Where the human still owns the job: judgment on what's worth building and whether it's good, plus the accountability gap, who owns what a machine built and a human shipped.

**Bio (292 words, "Head of Agentic AI" — current canonical version, timeline corrected):**

> Travis Frisinger is Head of Agentic AI at 8th Light, where he helps teams get AI-built software to production, not demos, not prototypes, but systems real users depend on. He has built software for more than twenty years, and now works on the gap most teams hit the moment the novelty wears off: generating code is easy, and getting it to production safely is the hard part. Most "AI made me a developer" stories stall exactly there.
>
> Since early this year he has been running an unusual experiment to understand that gap from the inside. He handed his own engineering discipline to an autonomous system and stepped out of the loop. It files work, designs it, writes the tests, implements, reviews itself, and merges, with no human in the routine path and no one reading the code it produces. It has shipped real software that way for months. The interesting part was never the code generation. It was everything around it: the structure, the tests, the guardrails, and the judgment that decides whether any of it should ship.
>
> That experiment changed how he thinks about the work. When code becomes nearly free, quality stops being something a senior reviewer catches and has to become structural, encoded into the system itself. The engineer's value moves from producing code to exercising judgment, and a new question appears that no org chart answers yet: who is accountable for what a machine built and a human shipped?
>
> He speaks on agentic AI, software craft, architecture, and engineering leadership, drawing on both the production work and the experiment. Underneath all of it is the question he keeps chasing: when the machines build the software, what is left that is ours, and how do we lead through it?

**Follow-ups:**
- **Timeline flag:** the autonomous system is ~4 months old (born Feb 2026); the "year" only refers to the broader no-review habit. Abstract uses "since early this year" (correct). If the bio you submitted still said "for the past year he has been running an unusual experiment," fix it if the form allows edits (corrected version above).
- Confirm the exact tagline used and the "Head of Agentic AI at 8th Light" title wording.
- The CTO Craft entry above used the older bio (tddbuddy / "principal-level"); this Head-of-Agentic-AI bio is the current positioning. If reusing materials, prefer this one.
- Refresh numbers + verify quotes (Cherny, Yegge, Gabriel) before stage.

### Platform Engineering Day @ KubeCon + CloudNativeCon NA 2026
- **Status:** Submitted 2026-06-18 (CFP closed Jun 21). **25-min Presentation.** Awaiting selection (they only contact selected speakers).
- **Conference:** Co-located event at KubeCon NA. Salt Lake City, UT, Nov 9 2026. Platform-engineering audience.
- **CFP:** https://events.linuxfoundation.org/kubecon-cloudnativecon-north-america/co-located-events/cfp-colocated-events/
- **Co-located event:** Platform Engineering Day · **Primary topic:** Platform Engineering · **Sub-topic:** Day 2 and beyond

**Title submitted:** When Software Builds Itself: The Paved Path That Lets a Machine Ship

**Description (930 chars):**

> Platform engineering makes the safe way the easy way: paved paths and guardrails. I took that to its limit. Since early this year, the developer on my paved path has been a machine.
>
> I built an internal system that takes intent and then designs, tests, implements, reviews, and ships, with no human in the loop and no one reading the code. It works because the paved path is complete: tests and standards define what "working" means before any code exists, guardrails bound what a bad run can do, and the pipeline reviews itself adversarially, since a fluent agent convinces even when wrong.
>
> But shipping was never the hard part. Day 2 is. This is a case study in operating an autonomous consumer of your platform: keeping it on the path, catching it when it drifts, and the night it failed anyway and recovered without me. You will leave with a model for guardrails strong enough to stop watching, and where mine are still thin.

**Benefits to the ecosystem (as submitted):**

> Platform teams are being asked to support AI coding agents, and most are improvising. This session offers a transferable model: treat the agent as a consumer of the paved path, make guardrails load-bearing enough that you can stop watching, and design for Day 2, because an autonomous system has to keep running, recover, and stay safe long after it ships. Attendees leave with a way to reason about paved paths, golden tests, and containment when the developer is a machine, plus an honest account of the failure modes and where my guardrails are still thin.

**Form answers (for the record):** Case study = Yes (single-org internal tooling). End-user company = No (8th Light is a consultancy/service provider, not a CNCF end user). Given before = No (not yet delivered; reframed version scheduled at Accelerate Chicago). Open-source projects = list only what's actually referenced on stage (git, pytest, Docker, etc.; OpenTelemetry only if the monitoring beat names it; do not pad with CNCF projects).

**Follow-ups:** build the 25-min cut only if accepted (separate from the 45-min Accelerate deck). Refresh numbers + verify quotes before stage.

### BeyondConf 2026: Detroit
- **Status:** Submitted 2026-06-18. **In Evaluation** (per Sessionize). 45-min session. CFP closes Jun 30.
- **Conference:** Detroit, MI, Sep 10 2026. AI-in-production, real-deployments-over-hype audience. $250 honorarium + registration; travel not covered.
- **Track:** How It Works.
- **CFP:** https://sessionize.com/beyondconf-2026

**Title submitted:** When Software Builds Itself: How the Engineering Gets Encoded *(the title on the Sessionize dashboard; the 909-char description below was drafted under the working title "How to Ship Code No One Reviews" and reads fine under either)*

**Description (909 chars):**

> I built a system that ships software with no human in the loop and no one reading the code. Here's how it works, and why it isn't slop.
>
> Intent comes in as an issue. An autonomous pipeline moves it through the stages a careful engineer would: design, tests first, build, review, merge. No human reviews the diff. What makes it safe isn't better code generation, it's everything wrapped around it.
>
> I'll walk the scaffolding: how tests and standards become the spec, so "working" is defined before any code exists; how quality is enforced structurally, not by a reviewer's attention; how it reviews itself adversarially, since a fluent machine convinces even when wrong; and the hard limits that bound a bad run. Plus the night it failed anyway.
>
> The takeaway: when code is nearly free, the engineering moves out of the typing and into the structure that decides what ships. That's the part you actually build.

**Follow-ups:** refresh numbers + verify quotes before stage.

---

## Separate talk: "Observability is the Control Plane for Agent Systems" (AGNTCon + MCPCon)

A different talk from "When Software Builds Itself," logged here so all CFP activity lives in one place. Submitted directly via Sessionize (not drafted in these sessions); pull the canonical title/abstract from the Sessionize submission.

- **AGNTCon + MCPCon Europe 2026** — In Evaluation — 17–18 Sep 2026.
- **AGNTCon + MCPCon North America 2026** — In Evaluation — 22–23 Oct 2026.

**To confirm:** is this a reframe of the autonomous-engineering / HydraFlow talk (the observability-as-control-plane angle for an agent + MCP audience), or a genuinely separate talk? That determines whether the trust-fleet / OpenTelemetry / "how it knows when something's wrong" material is shared with the other talk or kept distinct.

---

## ShipItCon (Dublin) — not submitted

- **Status:** Posted deadline (May 4, 2026) and selection (end of May) both passed before we found it; CFP form still appears live. Optional long-shot: email organizers re: waitlist/late slots, or hold for 2027 (CFP ~Feb).
- **Best track fit:** Engineering Traction ("when is friction good?"). Bullseye.
- **Friction-framed materials are ready** (title + 186-word synopsis below) if pursuing 2027 or another delivery/DevEx venue.

**Friction-framed title:** When Software Builds Itself: The Friction Has to Go Somewhere
**Friction-framed synopsis (186 words):**

> Code generation is nearly free now, so I did the reckless thing: I took myself out of the loop. For months, an autonomous system has filed, designed, tested, reviewed, and merged its own work. No human reviews the code. None ever has.
>
> It should have produced slop. It didn't, and the counterintuitive reason is the talk. When you remove the friction of writing code, the friction doesn't disappear. It moves. It moves into the structure that decides whether the code is any good, the tests, the review, the guardrails, the paved path the system can't leave, and into the one place a machine can't go: judgment. Delete that friction and you don't get speed, you get a retry storm against an empty account.
>
> This is a field report from inside that system: the heat of fully autonomous delivery, the resistance I had to engineer back in to keep it safe, and the traction when the friction sits in the right place. You'll leave with a model for where friction belongs when making software costs almost nothing, and an honest account of what still has no answer.

---

## Open CFP pipeline (verified live 2026-06-18; re-check before submitting)

Three framings depending on audience: leadership (judgment/governance), AI engineering (autonomous agents), delivery/platform (friction/paved paths). Versions exist at 45, 30, and 15 min.

### Highest-fit, travel + lodging covered
- **AI Engineering Summit** — Berlin, DE · conf Nov 16 · CFP **Jul 14** · strong on paper (coding agents, prompt-to-PR, testing/review of AI-generated code, governance). **CAVEAT:** could not independently confirm a conference by this exact name on a follow-up check (organizer site blocked automated verification); the lead came from a Sessionize listing. Verify it's real before relying. Travel + lodging reportedly covered.
- **Build Stuff** — Vilnius, LT — **SUBMITTED 2026-06-18, 45-min slot** (see Submitted section above).

### Act-soon (imminent deadlines)
- **Platform Engineering Day @ KubeCon NA** — Salt Lake City, US — **SUBMITTED 2026-06-18, 25-min** (see Submitted section above).
- **BeyondConf** — Detroit, US — **SUBMITTED 2026-06-18, In Evaluation** (see Submitted section above).
- **Code Europe** — Warsaw, PL · CFP **Jun 30** · AI Engineering + staff+ track.

### Comfortable runway
- **DevOpsDays Portland**, US · CFP Jul 6 · DevEx/delivery.
- **Devoxx Belgium**, Antwerp · CFP Jul 17 · top-tier practitioner.
- **NDC London 2027** · CFP Aug 30 · longest runway, big senior audience.
- **Conf42 AI Agents** (virtual) · CFP Aug 24 · purest theme, virtual.
- **LeadDev LDX3 New York** · rolling/TBC · leadership audience.
- **Monktoberfest**, Maine · no hard deadline · engineering-culture framing.

### Could not auto-verify (browser-check)
ODSC AI West (SF), Ai4 (Las Vegas), DevExec World 2027 (Santa Clara, CFP due to open ~now).

### Curated / invite-only (no CFP, pursue via direct speaker inquiry)
QCon SF/London, GOTO editions, Web Summit, World Summit AI.
