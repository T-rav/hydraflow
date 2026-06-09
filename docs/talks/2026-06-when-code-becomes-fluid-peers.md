# Peers on the Frontier

Research note for *When Code Becomes Fluid* (GOTO Accelerate Chicago, June 24 2026).
Companion to the skeleton, v2, and slides.

## Spirit of this section

These are peers, not targets. Everyone listed here is exploring the same frontier:
how humans stay meaningfully in charge of software that increasingly writes and
maintains itself. The goal in the talk is to situate HydraFlow among fellow
travelers, show that we all converged on the same thesis, and then be honest
about where each of us placed a different bet. Not a ranking. A map of the
choices, with mine as one point on it.

If a comparison ever reads as "I do it better," cut it. The room respects these
people, and so do I. The interesting thing is not who is ahead. It is that
serious builders, working independently, arrived at the same shape and then
diverged on one specific question.

## The thesis everyone already shares

By mid-2026 the loop-engineering thesis is consensus, not a hot take:

- **Peter Steinberger (OpenClaw):** "You shouldn't be prompting coding agents
  anymore. You should be designing loops that prompt your agents."
- **Boris Cherny (Claude Code, Anthropic):** "I don't prompt Claude anymore. I
  have loops running that prompt Claude." Claude authored 80%+ of merged
  production code at Anthropic by May 2026.
- **Addy Osmani:** named and popularized "loop engineering" in June 2026,
  crediting Steinberger and Cherny.
- **Steve Yegge:** 8-stage model of AI-assisted development topping out at
  "build your own orchestrator"; runs 20-30 parallel agents via Gas Town.

Talk consequence: I do not have to convince the room the horizon exists. They
arrive believing it. So the talk should not re-argue the thesis. It should pick
up where the thesis stops and ask the question the chorus mostly hasn't: once
the loop runs without you, what keeps it honest?

## The one axis that separates peers

Everyone agrees on "build loops." Where peers differ is **how much human review
stays in the routine loop, and what replaces it when it leaves.** That single
axis is the spine of the comparison.

| Peer | Human in routine review? | What carries the trust |
|---|---|---|
| Addy Osmani | Yes, human is the backstop verifier | Human judgment + maker/verifier split |
| Boris Cherny | Removed from prompting, kept as judgment gate | "A brutal review gate" + human on the other end |
| Peter Steinberger | No human code review | Automated tests pass = trust; reviews the prompt, not the code |
| Steve Yegge | Human as live supervisor of the swarm | Vigilant "babysitter" + CI + fixing what agents miss |
| HydraFlow (mine) | No human in the routine loop | Structural gates, agent review, containing loops, self-documenting enforcement |

This is a spectrum of bets on the same problem, not a quality ranking. Each bet
has a cost. Mine included.

## Where my bet sits, honestly

I bet on **structural containment over human vigilance.** No human approval in
the routine loop; I hold the walls, not the keyboard. The claim is not that this
is the right answer for everyone. It is that vigilance does not scale to software
that mutates daily, so I moved the safety from a person staying sharp into the
structure: independent gates, a four-layer test pyramid, review loops that repeat
to convergence, and caretaker loops that keep the docs and language true.

What this bet shares with the others: I merge code I have not read. So does
Steinberger. So does Yegge. That is common ground, not a dividing line.

What this bet costs: the safety is only as good as the container, and the
container is made of code, so it can drift. That is the honest price, and it is
the contribution below.

## The contribution to the shared conversation

The failure mode I can report from where I'm standing: **the container itself
going fluid.** Gates are code, so they soften. One defensible threshold at a
time, each lowered by an agent judging against the standard that is already
drifting. Gate erosion looks like a routine change, so it never trips the wire
that pulls a human in.

This is offered as a dispatch, not a gotcha. It is the kind of thing you only see
after running unattended long enough for drift to accumulate, and it sharpens
every peer's model, not just mine:

- It is why "if tests pass, trust it" (Steinberger) is necessary but not
  sufficient: the test can be softened by the same drift it is meant to catch.
- It is why a vigilant babysitter (Yegge) is not a full answer either: a person
  cannot see a wall slowly melting any better than a green test can, because
  erosion reads as routine.

Keeping the conventions sound is the one job that stays mine. That is where
"stay the engineer" actually bites, and it is the same worry on my
"What I expect to break" slide.

## Yegge: the closest peer, worth its own beat

Yegge is the most useful comparison because he is in the same architectural
category, not the commentary category. He built his own orchestrator.

- **Gas Town**: orchestrator running 20-30 parallel agents in YOLO mode, tmux HUD.
- **Beads**: his memory / issue-tracking substrate.
- Fleet of agents, issue-driven, external memory. Structurally the same machine
  as HydraFlow's worker-loop fleet + label state machine + memory.

His posture is "AI babysitter" (literally his LinkedIn title). The human watches
the swarm: review output, fix misses, create the PR, babysit CI. He gates it on
vigilance, his own words: higher stages need a "chimp-wrangler," and "if you have
any doubt whatsoever, you can't use it."

The peer framing: Yegge and I built the same kind of machine and made opposite
bets on safety. He keeps a sharp human watching. I tried to make the watching
structural so it does not depend on me being sharp. Both are live experiments.
Neither is finished.

The gift he hands the talk: "I've never read Beads, 225k lines of Go." That is
comprehension debt, stated plainly by one of the most credible people in the
field. I can agree with him completely (nobody can read it), and then show my
answer not as a one-up but as a different response to the same fact: I don't read
it either, but the system is forced to keep explaining itself, so the debt does
not compound silently. He accepted the debt. I structuralized around it. Both are
valid; the talk just shows the second path.

## Verification to-do before the stage

- Confirm exact Steinberger quotes ("Prompt Requests," deploy-without-reading)
  against his own X posts / OpenClaw transcript, not secondary writeups.
- Confirm the Cherny "brutal review gate" phrasing against a primary source.
- Confirm Yegge's "never read Beads / 225k lines" and the Gas Town agent counts
  against the Changelog episode or his own posts.
- **Naming collision:** my notes use "beads"; Yegge has a system literally called
  Beads. Decide on stage: am I using his, or is mine independent? Disambiguate or
  rename so no one thinks it's cribbed or gets confused about which Beads I mean.

## Sources

- Addy Osmani, Loop Engineering: https://addyo.substack.com/p/loop-engineering
- Steinberger on loops (X): https://x.com/steipete/status/2063697162748260627
- Steinberger profile (secondary): https://www.toolmesh.ai/news/peter-steinberger-ai-driven-software-development
- OpenClaw / Steinberger transcript: https://singjupost.com/how-i-created-openclaw-the-breakthrough-ai-agent-peter-steinberger-transcript/
- Cherny on loops + review gate (secondary): https://www.developersdigest.tech/blog/codex-loops-boris-cherny-agent-routines
- Yegge on babysitting agents (Changelog & Friends #96): https://changelog.com/friends/96
- Yegge's 8 levels: https://www.augmentcode.com/guides/steve-yegge-8-levels-ai-assisted-development
- Understanding Yegge's Gas Town: https://leosimons.com/2026/01/02/understanding-yegges-gas-town/
- From IDEs to AI Agents with Steve Yegge (Pragmatic Engineer): https://newsletter.pragmaticengineer.com/p/from-ides-to-ai-agents-with-steve
- Yegge's Vibe Coding Manifesto (Latent Space): https://www.latent.space/p/steve-yegges-vibe-coding-manifesto
