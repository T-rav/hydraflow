---
marp: true
theme: default
paginate: true
---

<!--
Speaker deck for "When Code Becomes Fluid." Story-driven, not a patterns dump.
Slides are deliberately sparse; the narrative lives in the speaker notes.
Default Marp theme — brand visuals to be layered later.

ARCHITECTURE (v4): provocation cold open, three-stage motive arc, ending shot.
The motive matures across the talk: (1) need, maintain what I vibed; (2) question,
Gas Town: how much human can you pull out and what breaks; (3) consequence, when making
gets cheap, judgment and governance become the job. Act 2 answers motive 2. The back third
(the gaps machinery, then the SignalRoom/DealIQ handoff experiment) answers motive 3.
Daughter is a grace note now, not the ending shot. The 3D-printer metaphor is cut.

PRODUCTION NOTES:
- Daughter is a grace note only (one slide near the close). Refer to her as "my daughter," no name or initial on slides or stage (minor, public stage).
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
  Never cut: the scar slide, the gaps framing, the SignalRoom/DealIQ handoff, the fork, the close.
- Numbers verified 2026-06-09, refreshed 2026-06-17: 47 loops (docs/arch/generated/loops.md), 1,713 merged PRs
  (gh search is:pr is:merged; the issue+PR counter is at #9586, which is NOT a merge count, do not say "9,500 PRs"),
  first commit 2026-02-18. REFRESH BOTH before the stage, the loop registry
  is public on hydraflow.ai and the room will check.
- Quality metrics verified 2026-06-09, refreshed 2026-06-17: 15,838 tests collected (pytest) / 839 test files;
  12 Port classes, ~26 Fake classes (count drifted/ambiguous, lead with "12 Ports, conformance-pinned"), per-fake conformance contracts in tests/trust/contracts/
  (github, git, docker, llm, honeycomb, workspace); coverage
  fail-under 70 (pyproject + ci.yml); 478 scenario tests (tests/scenarios); 61 sandbox e2e
  files; 591 regression tests (tests/regressions); 314 wiki json:entry blocks; 41 term files; 90 ADRs; hero
  quote verbatim at tests/test_gates_activation.py:148; gates-drift.yml = watcher-for-the-
  watchers receipt; PR #8460 21:43:31Z → #8463 created 22:07:51, merged 22:25:14 (42 min
  break-to-fixed total).
- New surfacing receipts (2026-06-17): self-modification guard (T29) = src/review_advisor.py + tests/test_review_advisor.py::TestSelfModificationGuard + ADR-0059; conformance scar = tests/test_mockworld_fakes_conformance.py (PR #8439 plural-typo remove_labels + nonexistent list_issue_comments); containment/interlock artifact = issue-reporter/services/tools.py "the client cannot opt out of scoping"; SignalRoom = rebrand of InsightMesh, same repo (FastMCP still names "InsightMesh"; only 7 commits mention SignalRoom, all June 2026); manifest loader = control_plane sync_apps_to_registry + apps/dealiq/manifest.json; gateway 4 meta-tools = mcp-gateway/mcp_server.py. The talk's DealIQ = the SignalRoom-hosted product, NOT the standalone deal-iq bonus-tracker repo (a side quest being renamed).
- CHERNY QUOTE SLIDE: wording matches published transcriptions of Acquired Unplugged
  (WorkOS, June 2 2026, youtube.com/watch?v=RkQQ7WEor7w); CONFIRM verbatim against the video
  before stage, same flag as the essay. The "~700k views in a day" texture and Huntley's
  "$297 vs $50k MVP" receipt are from secondary sources; verify against primary
  (ghuntley.com/ralph, his own posts) or soften to "it went around the industry in a day"
  and "a fraction of the quoted cost."
- DEALIQ HANDOFF + the her-and-Claude creative space have NOT run yet. Keep BOTH future tense on
  stage. The close is "I'll let you know," and that only stays true if nothing earlier pretends it
  already happened. Do NOT claim the factory has maintained DealIQ; it is "built in the lineage,
  handoff is the experiment."
- SIGNALROOM / DEALIQ lineage (back-third payoff of the Act-1 InsightMesh thread):
  InsightMesh v1 became unmaintainable (Aug 2025) -> v2 got guardrails -> v3 is the SAME v2 codebase rebranded SignalRoom (rebrand, NOT a rewrite), a dynamic-MCP platform of
  manifest-based apps that expose APIs and agents as role-gated tools (capability registry + ACL +
  control plane + service accounts; see apps/dealiq/manifest.json: 8 tools, mutating/exposed flags,
  dealiq-users vs dealiq-admins roles). DealIQ is an app ON SignalRoom: exec/sales company
  intelligence, buy signals, prospecting, deep-research agents in LangGraph. ALL 100% vibe-coded.
  HydraFlow (the factory) was born from InsightMesh and is the candidate to maintain its descendant:
  "the child maintains the parent." [FILL real receipts: in-prod-since, who uses it.]
- InsightMesh chronology VERIFIED from git (2026-06-09):
  · v1 → v2 rewrite began 2025-08-28 (v2 repo first commit: "ported slackbot from insightmesh").
  · v1 was Cursor-built, ~no human review, no guardrails — died. v2: still all vibe-coded, still
    ~no review, but WITH guardrails — alive today. The structure-over-vigilance bet predates the factory.
  · HydraFlow born inside InsightMesh at dx/hydra/ on 2026-02-18, commit 542dcd6a
    "feat: Add Hydra — parallel Claude Code issue processor". Standalone repo init same day
    08:57; orchestrator lands 2026-02-19 00:33; CI 00:38; quality hooks 00:40 (gates up in
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
Title card carries the submitted talk title — it must match the program attendees picked the session from — with the essay/series title as the subtitle question. The card does double duty: the program title says what the talk is, the subtitle plants the question the close slide answers ("Into judgment and governance").

Open with a SMALL intro over this card — no silent hold (dead air reads wrong live), but keep it to ~15–20 seconds and don't spend any later beats (no TDD, no daughter — those have slides waiting):

"Thanks, [emcee]. I'm Travis Frisinger — I've been building software for twenty-some years, and for the next forty-five minutes I'm going to tell you the story of the strangest thing I've ever built. (beat) It starts four months ago, with a folder."

Advance to the next slide ON "a folder" — the birth scene lands as the sentence completes. The intro's only jobs: name, warmth, and the promise of a story. Everything else waits.
-->

---

## Four months ago, I made a folder inside another repo.

# Three days later, it left.

<!--
Say it slow, like you're still slightly unsettled by it — picking up directly from the intro's "...with a folder": "The folder lived inside an internal platform I'd vibe-coded. It was called dx/hydra. (beat) Three days later, what was in that folder left — into its own repository. (beat) It has been building itself ever since." Eerie, not boastful. Optional escalation texture, all receipt-backed if you want to layer it in: within ten minutes of its orchestrator landing in the new repo it had CI and pre-push quality gates — the gates went up before the machine turned on — and it was fixing its own issues and merging its own pull requests by the next afternoon (PRs #53–60, ~17:00 Feb 19). Receipts: born at dx/hydra Feb 18 (commit 542dcd6a, "feat: Add Hydra — parallel Claude Code issue processor"); standalone repo init Feb 18 08:57; orchestrator Feb 19 00:33; CI 00:38; quality hooks 00:40. (Option: put a commit line on the slide as documentary texture.) Don't explain yet. Let the room want the chronology.
-->

---

## It has been building itself ever since.

# 47 loops. 1,700+ merged PRs.

#### No human reviews its code. None ever has.

<!--
Stage the numbers one at a time, like evidence at trial, not a LinkedIn cadence. "Forty-seven autonomous loops. (beat) More than seventeen hundred merged pull requests. (beat) Four months." Then land the claim flat and let it cost something: "No human reviews its code. None ever has. (beat) I haven't read a line of this code in a year." Don't soften it, don't qualify it — the flinch in the room IS the talk, and the next forty minutes earn the right to have said it. (The "year" reaches back through InsightMesh v2, also entirely vibe-coded with no review — the no-review bet predates the factory, and the next slides pay that off.) ON STAGE, preempt the "but you said four months" beat in the same breath: "The factory is four months old. The habit of not reading is a year — it started with the platform before it." Relatability beat, optional: "And before you ask — no, not all seventeen hundred are glamorous. A lot of them are dependency bumps and housekeeping. That's the point. Maintenance is most of software. It does the boring part too." Owning the boring PRs buys more trust than the big number does. If a principal pulls the git log and sees early commits under my name, the answer is precise, not a walk-back: commit identity is not human review — I directed and committed work I never read, and vibe-authoring is not reviewing. The handover curve is still the deepest cut: "Two out of every three commits in the factory were authored by the factory; last month they out-committed me three to one." (Receipts: 1,227 of 1,790 non-merge commits by agent identities; last 30 days agents 305 vs Travis 116. STRONG CANDIDATE for a slide visual — monthly stacked bar, human vs agent commits, the flip is the picture of 'self-building'.) REFRESH NUMBERS before stage — loops from docs/arch/generated/loops.md, PR count from gh. The claim must match the public registry exactly, because someone in row three will pull it up.
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

# August 28, 2025: v1 became unmaintainable.

<!--
Motive one — the relatable one, a confession. InsightMesh: a real internal sales-enablement platform, built the way most of this room is building right now — Cursor, fast, thrilling, barely any review, no strong guardrails. (Stack stays a spoken aside at most — "LangGraph agents, Langfuse traces, the stack you'd expect." Real, not a toy.) "And v1 collapsed under its own weight. I couldn't maintain what I'd made. So on August 28, 2025 — the date's in the git history — I did what every engineer in this room has done at least once: threw it away and started over." This conference's tagline is "you ship it, you own it, you maintain it" — and the word AI changed most isn't ship or own. It's maintain. I didn't need a faster way to write code. I needed help keeping what I'd written alive. Plant the credibility shield here so the room can't file this under toy apps: keeping a real platform alive, and failing at it, is what taught me the discipline that became the factory. The platform was the crucible, not a demo.
-->

---

## The fork: put the human back in, or build the structure?

v2 is still entirely AI-written. Still almost no human review. What changed was the guardrails.

# The version with less structure died. The version with more structure lives.

<!--
The beat that carries the talk in miniature — deliver it slow. "Here's the fork in the road. The obvious fix was to put the human back in the loop — review everything, slow down. I did the opposite. v2 — the version alive today — is still entirely AI-written. What changed was the guardrails: standards, tests, CI gates." The bet — structure over vigilance — was made HERE, ten months before the factory existed. The lessons rolled forward — that's roll number one, and it won't be the last time you hear that phrase tonight. Vibe to Value — the methodology name is this journey, compressed to three characters.
-->

---

## The bet had receipts.

**FLUID** · Mar 2025 · principles for code that mutates
**2,500 conversations** · Mar 2025 · my own discipline, measured: a third never made it past the AI's first response
**AI Coherence** · Apr 2025 · models produce plausibility, not truth

#### Vigilance measurably fails. Models can't supply truth. Verification has to be structural.

<!--
The credentials beat, and it's personal data, not opinion — walk it slow, because this is where "structure over vigilance" stops being a temperament and becomes a conclusion. Before v1 became unmaintainable, I'd already spent the spring of 2025 doing the homework. The case study: I exported 2,443 of my own ChatGPT sessions going back to 2023 and scored them against a five-stage decision loop I defined — frame, generate, judge, verify, refine. The findings were self-incriminating. 34% of my sessions never went past the model's first response. Of the loops I did complete, 27% skipped the critical-evaluation step. Say the next line plainly: "I taught test-driven development for twenty years, and my own validation discipline failed a third of the time. That's not a character flaw. That's what sustained contact with a fluent machine does to vigilance." One behavior fixed it: sessions where I asked the AI to critique its own output completed the loop 98% of the time. Hold that number — it comes back later as a job category. The coherence paper is the theory underneath: LLMs are coherence machines, not truth machines; hallucination is incomplete anchoring, not malfunction; truth enters from outside, through grounding and verification. So when v1 became unmaintainable and the fork came, the data had already voted: if the model only produces plausibility and human vigilance measurably fails — even mine — then verification can't be a virtue. It has to be structural. Both papers are at aibuddy.software/papers; the room can check. NUMBERS verified against the PDFs 2026-06-11: 2,443 sessions, 34% exit at step one, 27% of completed loops skipped validation, 98% completion for critique-involving sessions.
-->

---

## Then Steve Yegge published *Gas Town*.

#### January 1, 2026.

# How much of the human can you pull out, and what breaks?

<!--
Motive two — the question. Be honest: Gas Town was the catalyst, not a parallel discovery. Steve showed the operational thing was buildable — a fleet of agents, an orchestrator, a human babysitting the swarm. I couldn't put the question down. Seven weeks later: first commit, February 18 — inside the InsightMesh repo, because it was born as a maintenance helper for the thing I'd vibed, carrying v2's guardrail lessons with it. Roll number two, and you can see it in the log: within ten minutes of the orchestrator arriving in the new repo, it had CI and quality gates. The gates went up first. Three days later it outgrew its host and moved into its own repo — and InsightMesh carried a vendored copy of its offspring for three more months before the umbilical was fully cut in May. Then the plant, one line, move on: "And somewhere in the four months since, the reason I was building changed. I'll get there."
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
Restored to live motion — the stills went flat, and this is the one beat the room needs to SEE move. Pre-recorded screencap at 2–4× speed (a recording can't demoware-fail you on stage): a real issue filed → a loop claims it the moment the label lands → branch → PR opens → checks go green → the label trail walks → merge. Frame it before you hit play: "I filed the intent — that's my whole contribution to what you're about to watch. Everything after this is the factory." Then hand off the clicker, say "I'll let it run," and stay SILENT while it plays — the confidence is the whole move; narrating over it undercuts it. Land on the final merged frame and speak the punchline to the freeze: "Issue to merged production code. An agent planned it, implemented it, wrote the tests, reviewed it, merged it. Notice what's missing from that list: me. (beat) It did this seventeen hundred times in four months." Cut back to slides — don't linger past the punchline. (Pick a cycle whose issue title reads from the back row.)
-->

---

# The container is solid.
# The code inside it is fluid.

#### The container is what makes fluidity safe.

<!--
The thesis. Let the slide sit in silence for a few seconds first. Pour code fast with nothing underneath and you don't get agility — you get the flood: leaked keys, runaway bills, dropped databases. Fluidity is not the absence of structure; it's what you get when the structure moves out of the code and becomes the vessel the code runs inside. And name the heritage, because the man is in the room: the container is Alistair Cockburn's hexagon from 2005 plus Dan North's BDD from 2003, run at autonomous-system scale. Nothing here is new architecture. "Your craft isn't the casualty of this shift. It's the material."
-->

---

# The conveyor runs without me.

#### I cut the dies. The crew keeps it honest. The interlocks keep it safe. None of that is the keyboard.

<!--
This is the lean-back line. Say it plainly and let it cost something. The line runs without me: the conveyor is the label state machine, every work item rides it from intent to merged, and each loop is a station that claims it, does one job, and sends it on. No hands. I do three things, and none of them is the keyboard. I cut the dies, the workflow that shapes every part so its choices are good by construction. The crew, the loops, keeps it honest: tending, documenting, attacking, reviewing. And the interlocks make the unsafe move impossible, the way a press cannot close on a hand. No human approval in the routine loop; every approval in the day-to-day pipeline is made by another agent. I'm pulled in for high-blast-radius decisions, and I verify direction on a pass, not line by line. So the obvious question: if I'm not the one watching the code, what is? Hold that question; the rest of this act is how those three hold, named as they come. And I'm not the only one whose job description rewrote itself this spring. Next slide.
-->

---

## Three weeks ago, the man who built Claude Code said it out loud.

> *"I don't prompt Claude anymore. I have loops that are running. They're the ones prompting Claude and figuring out what to do. My job is to write loops."*

#### Boris Cherny, Head of Claude Code · June 2, 2026

<!--
The recognition beat. The clip went viral inside a day (secondary sources say ~700k views in 24 hours; VERIFY that figure before speaking it, or just say "it went around the industry in a day"). Half this room has seen it, so let them recognize it before you say a word. Then two moves, in order.

Move one, push on "anymore": prompting didn't disappear. It got compiled. I still prompt once, at the top, when I file an issue that states intent. The loops turn that single prompt into the ten thousand they fire at Claude on my behalf. Writing a loop is writing those prompts ahead of time, once, as reviewed and tested code, instead of typing them live and throwing them away. "Write loops" isn't a smaller job than prompting was. It's prompting moved up a level and made durable.

Move two, the disambiguation the room needs: when most of the industry hears "write loops," they picture Geoff Huntley's Ralph loop, the famous bash one-liner: while true, cat PROMPT.md, pipe to the agent, repeat. One prompt, re-fed forever, the repo as the only memory, done when the backlog converges. And it works; Huntley shipped a fifty-thousand-dollar-quoted MVP for about three hundred dollars in tokens. I'll even concede the kinship: at the bottom of every loop in my registry there's a Ralph loop trying to get out. An agent, a prompt, a retry budget. But a Ralph loop is a harness around one task. It finishes. What I run is what "write loops" means when the loops never finish.

Move three, the contemporary anchor — and at a CRAFT conference the name lands double: this week the field gave "write loops" a name. Loopcraft, the art of stacking loops (latent.space, June 2026). Their framing: "the entire game of the next century is to stack loops as effectively as possible." Own the timeline out loud: "Cherny said it three weeks ago. The field named it this week. I've been running it for four months." Then the bridge into the taxonomy: "So, forty-seven of WHAT, exactly? This is what loopcraft looks like when you don't stop at one loop." Next slide. (VERIFY the loopcraft framing + the stack-loops line against latent.space before stage; keep the fuller Acquired Cherny quote as the on-slide one. latent.space also corroborates the close: it says the field's focus is shifting "from model capability to governance" — exactly where this talk lands.)

SOURCE: Acquired Unplugged (presented by WorkOS), June 2 2026, https://www.youtube.com/watch?v=RkQQ7WEor7w. Wording matches published transcriptions; CONFIRM against the video before stage (same flag as the essay). Huntley receipts: ghuntley.com/ralph, ghuntley.com/loop, Dev Interrupted episode; verify the $297-vs-$50k figure against his own posts before speaking it.
-->

---

## Forty-seven of what, exactly?

**Maintainers** keep state fresh · **Proposers** grow it · **Pruners** shrink it
**Auditors** verify invariants · **Repairers** fix what broke · **Watchers** budget & escalate
**Promoters** move work through tiers · **Provocateurs** attack the system on purpose

<!--
Pay off the cold-open number — this is the factory's workforce, the crew from the conveyor slide. Walk the categories fast, one breath each; don't lecture the grid. Then: "I designed the first couple up front. The rest accreted, one at a time, each answering a recurring operational problem — and the categories weren't in my sketch. They emerged." VERIFIED from file history: the first two loop files (base_background_loop, pr_unsticker_loop) land Feb 24 — day six. The rest accrete in ones, twos, and threes across four months; the newest entered the registry June 4. Spoken texture option: "The newest loop in that registry is three weeks old. The taxonomy is still growing while I'm standing here." (Caveat: file-date method doesn't follow renames — an Apr 24 ten-file burst is likely a refactor, so keep the claim soft: 'the rest accreted over four months.') Save the provocateurs for the next slide — point at the last cell and say "and that last category deserves its own slide."
-->

---

## The factory red-teams itself.

Provocateurs synthesize adversarial cases from past failures · run them against the system weekly · challenge its assumptions before reality does

<!--
The sit-up beat — the factory employs agents whose whole job is to ATTACK it. CorpusLearningLoop mines past skill failures and synthesizes adversarial cases from them; SkillPromptEvalLoop runs that hostile corpus against the built-in skills every week; the advisor pattern wires a skeptical second opinion into PR review and verification. A workforce that maintains, proposes, prunes, audits, repairs, watches, promotes — and red-teams itself. Nobody told it to be paranoid; I encoded the paranoia once and it became a job category. And here's the 98% number from the receipts slide coming back: in my own 2025 chat data, asking the AI to critique its own output was the single behavior that almost guaranteed a completed decision loop. The provocateurs are that finding, hired full-time. That's who does the work. The next slides are what keeps that workforce honest.
-->

---

## Quality moved from **social** to **structural**.

Senior reviewers, tribal knowledge, manual discipline: none of it scales to a system that mutates daily.

#### The code got **disposable**. The intent and the tests got **precious**.

<!--
The unifying reframe — give it its own breath before the numbers. Quality enforcement used to be social: the senior reviewer who catches it, the tribal knowledge of who-knows-what, the discipline you hope survives the sprint. A system that rewrites itself daily outruns all of that. So HydraFlow doesn't lower the quality bar — it moves the bar INTO the system: validation continuous, governance executable, scenarios authoritative. Land the economics under it, because it's the mechanism, not just the assertion: code quality was always a proxy for the cost of the next human change, and that cost was comprehension. AI zeroes it, writing is free and maintenance moved onto the factory, so the code got disposable, it's output now, not the thing I keep. What stays precious, and what I hold to a high bar, is the intent and the tests: the spec and the gauntlet that defines working. Quality didn't drop, it relocated, from the code to the rubric. We stopped grading the essay and started grading the rubric. If you hear "fluid" and think "lower standards," you've got it exactly backwards. And this isn't post-hoc reasoning: the receipts slide in act one is the proof. The social version was measured failing, in me, in March 2025, before the structural version was ever built.

Heritage, for a craft room, one breath each: Gabriel named this in 1991, "The Rise of Worse is Better", good-enough beats the right thing and wins. He argued both sides for thirty years and never settled it; the AI regime settles it, good-enough is the rational target now, because the quality moved to the rubric. And the irony lands hard: Gabriel was a Lisp man, and the essay was a lament that Lisp, the AI language, the right thing, lost to good-enough. The AI that Lisp was built to create finally showed up, not in Lisp, not to restore the right thing, but as a machine that makes good-enough code at industrial scale. The dream came true and proved the lament right. (Verify the Gabriel citation; the standalone essay is 1991.)
-->

---

## The encoding has a size.

15,800+ tests · 70% coverage floor, CI-enforced · 478 world-scenario tests · 590+ regression tests

#### Gates you can edit. Interlocks you can't. The factory caps what it can break.

<!--
Numbers one at a time, same trial cadence as the cold open: nearly sixteen thousand tests. Four hundred seventy-eight scenario tests that exercise the system inside simulated worlds. A hundred seventy-six regression tests — every bug that ever bit lands with one, so it can never bite twice. (15,838 collected via pytest 2026-06-09; refresh with the others.) COVERAGE NOTE: to a room of principals, "70% floor" reads as "30% unwatched." Before stage, run coverage and get the ACTUAL number — if it's meaningfully above 70, say both ("the enforced floor is 70; actual is X"); if it's near 70, drop coverage from the slide entirely and let the test counts carry it. The floor's real story is structural anyway: the build fails below it, and the factory can't quietly lower it. Then the distinction the next slide depends on: the gates are habits — code the factory can edit. Interlocks are not. Hold that line; it's the hinge of the whole middle act — and it sets up the obvious question: what ARE the interlocks? The next slide names them. These tests are the dies, the craft cut into a shape every part has to fit.
-->

---

## Why it can't run away

**Per loop:** attempt budgets · kill switches · credit-aware yield
**Across loops:** one owner per work item · dedup · watchers
**Beyond its reach:** destructive ops blocked by hooks · can't raise its own budget · can't touch persisted state

<!--
Containment by construction, three rings — this is the "preventing runaway loops and cascades" promise from the abstract, delivered. Per loop: budgets and kill switches mean no single loop spins forever. Across loops: the label state machine gives every work item exactly one owner, so a local change can't snowball into a storm. And the interlocks live OUTSIDE the code the factory is allowed to edit: it cannot take an action it can't take back. The point isn't that loops never misbehave. It's that misbehavior is bounded, reversible, and in-budget — by construction. But "bounded, reversible, in-budget" is a CLAIM. How do you test a claim like that — without a staging org, real tokens, and a live bill running while you do? That's the next move.
-->

---

## Testing this used to mean an *environment*.

A staging GitHub org. Real tokens. Rate limits. Flaky networks. An LLM bill.

<!--
Start with the pain everyone in the room knows: "Testing a system like this used to mean an ENVIRONMENT. A staging GitHub org. Real tokens. Rate limits. A flaky network between you and everything. An LLM bill running while your tests do. And a test run measured in minutes — if it didn't fall over first." Let them nod. The next slide is the escape.
-->

---

## MockWorld: the test chamber

GitHub, git, Docker, the LLM itself: **12 Ports, 25+ Fakes**, each pinned to its real adapter by a conformance contract.

#### A mock fakes a response. A Fake world has state, time, and failure modes.

##### A type check once said the fakes matched. They didn't. Now the contract checks signatures too.

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
THE SCAR SLIDE — the credibility purchase. [VERIFY THE DETAILS OR SWAP IN YOUR TRUE WORST DAY — the shape below is reconstructed from the failure mode documented in the repo's own rules (CLAUDE.md: CreditExhaustedError silently eaten → "the loop burns attempt budget against an exhausted billing signal"). Tell it with the real specifics only you have: when, how long, what it cost, how you found it.] The relatable shape: "The billing API said no. But the error came back wrapped as a generic failure — and loops do what loops do with generic failures. They retried. Every loop, independently, burning its attempt budget against an account that could not say yes. Anyone who's been paged for a retry storm knows exactly what this looks like. My factory built me one." The recovery, briefly: the fix wasn't heroics, it was a rule — every subprocess runner now re-raises credit exhaustion past the generic handler, and that rule lives in the repo where every future agent inherits it. The lesson, plainly: "The factory doesn't fail like a junior engineer. It fails like a distributed system — dumb, persistent, parallel. The interlocks held: budgets capped it, nothing was destroyed, everything was reversible. But I want you to have the real picture: this thing has bad days, and the bad days are why half those forty-seven loops exist." This slide buys more trust than every green checkmark in the deck. Don't rush it, don't soften it. Then the handoff into the gaps: "A system that rewrites itself daily opens gaps ordinary software never has. The next few minutes are the machinery I built to fill them."
-->

---

## A system that rewrites itself opens gaps normal software never has.

#### Comprehension. Meaning. Judgment. Erosion.

<!--
The framing slide, and the pivot off the bad day. "Half of those forty-seven loops exist because of days like that. A system that edits itself daily opens four gaps ordinary software never faces. Nobody can read it, comprehension. The words quietly change meaning. A fluent machine is persuasive even when it's wrong, judgment. The structure softens one reasonable change at a time, erosion. The rest of this act is the machinery that fills them, and the one I haven't filled yet. I'll start with the dangerous one."
-->

---

## Judgment gap: the factory stays skeptical of itself.

Advisor pattern, a second opinion wired into review and verify · Corpus-learning loop mines past failures into fresh attacks · Provocateurs run them weekly

#### The artifact: a test that resists the system's own future laziness.

> *"activate it in gates.toml rather than deleting this test"*

<!-- (hero quote verified verbatim: tests/test_gates_activation.py:148 — option: cite file:line on the slide as documentary texture) -->

<!--
The judgment gap is the dangerous one: a fluent machine is persuasive even when it is wrong, and my own 2025 chat data proved I would believe it. The 98% number from the receipts slide is this gap, measured. So the factory is built to distrust itself. The advisor pattern wires a skeptical second opinion into PR review and verification. The corpus-learning loop mines past failures and synthesizes fresh adversarial cases from them. The provocateurs run that hostile corpus weekly. And the artifact those three produce is the emotional center of the act, and the payoff of the identity beat: "I spent years teaching people to write the test first. This is the first test I have ever seen that teaches the NEXT developer, a test written to resist the system's own future laziness, telling whoever comes after to fix reality instead of the test." Not a passing test, a self-defending one. TDD did not get abandoned when I stopped reviewing code. It got projected up a level, from a practice I performed to a property the system defends. Hold it a beat. Then the turn: "I cannot read the code that grows artifacts like this, so I stopped trying. I read what the code says about itself instead." (Provocateurs are introduced earlier on the taxonomy slide; this is the deeper machinery, and the 98% receipt makes it personal.)
-->

---

## The reviewer can't approve changes to its own reviewing.

When a diff touches the review code, the veto is forced on. The factory is structurally forbidden from editing the thing that judges it.

<!--
The objection every engineer in the room is already forming: if an agent approves the code, and that judgment is itself code the factory can edit, what stops it from loosening its own standards? I had the same fear, so I made it impossible. There is one rule the reviewer cannot vote its way around: when a change touches the reviewer's own files (src/review_advisor.py, src/review_phase/), its authority flips to veto, every time, no matter what the config says. It can block changes to its conscience; it can never approve them. This is the T29 self-modification guard (ADR-0059), tested at tests/test_review_advisor.py::TestSelfModificationGuard. I encoded the distrust once, and it became an interlock the system can't edit from the inside. Place it right after the judgment-gap slide: it is the deepest answer to "what stops it softening its own standards."
-->

---

## Comprehension gap: I don't read the code, I read what it says about itself.

314 wiki entries, regenerated from live pipeline events · 91 ADRs · architecture diagrams regenerated on every PR

<!--
The living-knowledge layer — HydraFlow's answer to comprehension debt. Nobody can read a codebase that rewrites itself daily; Yegge says it plainly — he's never read Beads, 225k lines of his own system's Go. I can't read mine either. The difference is mine is REQUIRED to keep explaining itself: the wiki regenerates from live pipeline events, not from anyone's memory. The architecture diagrams regenerate on every PR. Documentation didn't die in this regime. STATIC documentation died. What replaced it is documentation with a pulse, maintained by the same factory it describes — so the comprehension debt never compounds silently.
-->

---

## Meaning gap: the vocabulary is load-bearing.

41 domain terms live as files in the repo. The glossary auto-extracts from code.

# If the code and the glossary disagree, the build fails.

<!--
The sharpest claim in the knowledge layer — give it its own slide because no one else can say it. Words drift in every codebase: "task" starts meaning three things, "promote" quietly changes semantics, and six months later nobody can read the system because the names lie. Here the names CAN'T lie: forty-one domain terms are files in the repo, the glossary extracts from the live code, and if they disagree about what a word means, CI fails the build. That's Eric Evans' ubiquitous language — the DDD discipline — made executable. The factory is not allowed to redefine a word without telling me. Which raises the obvious question: if even the explanations and the vocabulary are code the factory maintains... (hand straight into the next slide)
-->

---

## Erosion gap: a softened gate looks like a routine change.

A CI workflow named **gates-drift** checks that the interlocks still match their source of truth.

#### What I haven't filled yet: held-out evals.

<!--
The honest slide — deliver with conviction, not hedging; the room trusts everything else more after this. The scariest failure isn't a breach. It's a slow softening: a threshold lowered, a skip added, each one defensible, each approved by an agent judging against standards the same drift is relaxing. Gate erosion reads as routine, so it never trips the wire that pulls me in. And yes — I've built a tripwire: there is literally a CI workflow named gates-drift that verifies the branch-protection artifacts still match the gates.toml source of truth and every active gate maps to a real job. But notice what that is: a watcher for the watchers, and it's code too. And name the sharper version of the same problem before someone in row three does: "My test scenarios live in the repo the factory edits. StrongDM holds their evaluations OUTSIDE the system so it can't optimize against them. Mine are inside. What I have today: fresh-eyes review by subagents with no conversation context, conformance contracts the fakes can't dodge, a sandbox tier with real dependencies. What I don't have yet: held-out evals. It's the next interlock I owe the system." Saying the gap out loud is the credibility move — this room can smell an unaddressed weakness from the lobby. Turtles, all the way down to one place: the interlocks cap the damage, and the conventions are mine to keep sound. That's the one job I can't delegate. That's where "stay the engineer" actually bites.
-->

---

## I'm not out here alone.

Huntley trusts the rerun. Steinberger trusts the tests.
Cherny keeps a gate. Yegge babysits the fleet.
I trust the standard: the craft, encoded and enforced.

#### Different bets on one question: what holds when you step back?

<!--
Forty seconds, peers not foils. Huntley first, one breath: the Ralph loop bets on stateless brute force, rerun the same prompt until the work converges, the repo is the only memory, read the result in the morning. Cherny next, and the callback earns its keep: the write-loops quote from earlier in this talk is his, and the same man still keeps a brutal human review gate on his own loops. The engineer who stopped prompting did not stop reading. And Steve returns — I borrowed his question and made the opposite bet on the answer. We even started at the same wall: he totaled a vibe-coded system and rebuilt it from scratch (his book's line is "Joel Spolsky was wrong" — rewriting is cheap now), and I totaled one too. He built my kind of machine, Gas Town, twenty or thirty agents over a memory system — and his answer is to rewrite freely and babysit it; he literally retitled himself "AI babysitter" and gates it on staying vigilant. Mine is to rebuild with the dies and interlocks so the next one can't total, and move the watching into the structure so it doesn't depend on me being sharp. (VERIFY the "Joel Spolsky was wrong" line against the Vibe Coding book before stage.) All of these are live experiments; none is finished. Then the line that sets up the close (NOT a cut payoff — it now points forward to judgment): "Every one of us is working where failure is LEGIBLE — a red test, a bad diff, a broken build. The structure handles the legible part. What no structure catches — is it any good, is it worth building, who does it hurt — is the illegible part. Hold that; it's the judgment the close lands on."
-->

---

## So: how much of the human comes out?

### For legible software, almost all of it.

<!--
Close the loop on motive two, honestly scoped. Legible software: a bad commit is detectable, a failing test observable, drift auditable, side effects reversible. The factory has something concrete to be sharper about. That's the class HydraFlow lives in, and within it the evidence says yes — the human time per unit of value dropped far enough to change the economics. (beat) "And that's where I expected this talk to end, when I started writing it."
-->

---

## The platform that became unmaintainable in Act One didn't stay dead, and it didn't get rebuilt.

# InsightMesh v3 is SignalRoom.

#### Same repo, new name. Deploying a manifest.json deploys an app: its tools, its visibility, its permissions.

<!--
Pay off the InsightMesh thread the room has been holding since "v1 became unmaintainable," and CLOSE THE LINEAGE LOOP explicitly so "child/parent" on the next slide is earned, not inferred: "Remember the repo HydraFlow was born inside and walked out of in three days? That was InsightMesh. It didn't stay dead, and here's the part people miss, it didn't get rebuilt either. Same repository, new name." v1 became unmaintainable, v2 came back with guardrails, and v3 is the same v2 codebase rebranded SignalRoom (the server still identifies as InsightMesh internally; only the brand changed, June 2026). The mechanism lands in a craft room: each app is a checked-in manifest.json, and merging it registers the app's tools, sets MCP visibility, and creates the role-based permission groups, with no wiring code. The gateway exposes four generic methods (search, list, describe, run); everything else is discovered live and filtered to who you are. Say the line that matters and let it land: it is 100% vibe-coded, not a line of it written by a human, because it's the same continuously-AI-built repo. And keep the stack name, it grounds the claim: the deep-research agents run in their own framework, LangGraph, executed in-framework. This is the same structure-over-vigilance bet from the fork slide, now running a real production platform. Prove "not toys" with usage, not line counts: it's in production, used by our sales team, about ten months old. And when I say 100% vibe-coded, I mean no human wrote a line; commits under my name are me pressing a button, not typing the code. Committing is not writing.
-->

---

## It runs DealIQ for our sales team.

Exec-level company intelligence, buy signals, prospecting. Deep-research agents in LangGraph. 100% vibe-coded.

# Can the child maintain the parent?

#### The factory goes home to maintain the platform that raised it.

<!--
The experiment, and keep it FUTURE TENSE, because the close depends on it. DealIQ is a real production app on SignalRoom: company intelligence for the sales team, buy-signal detection, prospecting profiles, deep-research LangGraph agents, every tool permission-gated right in its manifest. Real users, in production, and I have no time to feed it. So here is the next experiment: hand its maintenance to the factory. The thing born inside InsightMesh, that escaped in three days, goes home to keep alive InsightMesh's own descendant. The child maintains the parent. I am running it now. I do not have the result yet. Keep it qualitative on stage: real users, in production, the sales team. Do NOT name the host URL, no audience value and it is an internal box. If you want a sharper receipt, drop in an in-production-since date you can stand behind.
-->

---

## When making is cheap, judgment is scarce.

The constraint stops being "can we build it." It becomes "should we, and is it any good."

<!--
CASH THE "REASON CHANGED" PLANT (set on the Gas Town slide) out loud, FIRST thing on this slide: "I told you the reason I was building changed. Here it is. I started to maintain what I'd vibed. I kept building because when making gets this cheap, the one thing still scarce, and the one thing still mine, is judgment." That line is the payoff the talk has been promising since Gas Town; without it the back third reads as epilogue. Then the consequence motive 3 resolves to. If the factory builds anything I can specify, skill at building stops being the bottleneck. What's scarce is deciding what's worth building and telling whether it's good. I learned to make by struggling with the making; the next people may learn to make by directing and judging, never touching syntax. New literacy or lost craft, I genuinely don't know, and I'm the one responsible for getting it right.
-->

---

## The same handoff, somewhere quieter.

#### My daughter and I are starting to explore it as a creative space. We describe, it builds, we judge what came back.

<!--
The grace note, ONE breath, future tense, no printer and no "she ships software." Said plain and a little warm: the same handoff I'm testing on DealIQ, I'm also starting to explore with my daughter, as a creative space we share. We describe a thing, the factory builds it, and the part that stays ours is judging what came back. That's it. Don't oversell it, don't linger; the warmth is in the restraint. (She stays a grace note, minor, public stage, no full name.)
-->

---

## My interlocks protect my repo.

# They don't protect the org.

#### Who answers for what a factory built and a human shipped?

<!--
End the second-order beats on the gut-punch, not a list. Hooks, credit caps, immutable state, those keep the factory from hurting itself. They say nothing about software that's wrong, unfair, or worse for the people downstream of it. When a factory builds it and a human ships it, who is accountable? The floor I built guards the system. It does not guard the org, or the customer. I don't have a clean answer. That's why it's the last thing before the close.
-->

---

# Where does the engineer go?

## Into judgment and governance.

#### Making got cheap. Deciding what's worth making, holding the standards, owning what ships. That's the job that's left, and the one I can't hand off.

<!--
DELIVERY: "governance" is a flat noun, so land the VERBS on stage — deciding what's worth making, holding the standards, owning what ships — not the word itself. Answer the title, for THEM, not just for me. The craft doesn't disappear, it moves up a level. CRAFT-CONFERENCE TIE (land this, it's the room's whole reason for being): "The craft didn't die. It got a new material, the loop. The field's already named it: loopcraft. Same craft, one level up." Everything that made the factory safe, the interlocks, the gates, the tests that defend themselves, is SOLID-era engineering projected up a level. Only people with the craft can build a factory worth trusting. "I spent years teaching the craft one engineer at a time. The factory is the same teaching, compiled." So the direction, plainly: "Go build the container. Shared make targets, quality gates, a test pyramid, CI gates every new repo inherits. Then hand the keystrokes to the machine and keep the judgment for yourself. That's where the engineer goes." Then home, brief and true: "I'm running the experiment right now, on a platform called SignalRoom and an app called DealIQ, and quietly, with my daughter. I'll let you know." Walk off on that.
-->

---

## Thank you

HydraFlow · the FLUID principles · V2V · the papers: aibuddy.software/papers

<!--
References, contact, the essay link. Keep it short; the last real slide was the close.

=== Q&A ARMORY — the five hardest questions, answered in advance ===

1. "What stops it from optimizing against its own tests?" — Concede the gap first: "Honestly?
   Less than I want. My scenarios live in the repo it edits; StrongDM holds theirs outside the
   system, and that's the stricter discipline. What I have: fresh-eyes subagent review with no
   conversation context, conformance contracts pinning every fake to its real adapter, and a
   sandbox tier with real dependencies. Held-out evals are the next interlock I owe it." The
   concession IS the answer — this room trusts named gaps over claimed completeness.

2. "What does it cost?" — Don't deflect; you have real numbers. "I'll give you an actual
   receipt: one night, thirty merged PRs, $125.19. The running average is three to seven
   dollars per merged pull request. There's a CostBudgetWatcher loop enforcing daily caps per
   source, and spend is attributed per-loop on the dashboard, so I always know that number. The honest pattern
   underneath it: we've spent more engineering on validation and governance than we've ever
   spent on inference." If pressed on whether it scales: the caps are the answer — the factory
   cannot outspend its budget by construction; cost is an interlock, not a hope.

3. "You're going to let a factory with no human review maintain a product real users depend on?" —
   Don't dodge; this is the accountability slide restated as an accusation. "That's exactly the
   right question, and it's why DealIQ is an experiment I'm narrating, not a victory lap. The interlocks
   protect the repo today: nothing destructive, nothing irreversible, everything in budget. What
   they don't yet protect is the user on the other end of a shipped change. Reaching the user with
   the same guarantees is a prerequisite of the handoff, not an afterthought. And the release gate
   that can't be automated stays human: someone who owns the outcome decides it ships."

4. "Aren't 47 loops just sprawl? / cron jobs with opinions?" — "Fair — count alone isn't
   capability. Two things keep it from being sprawl: every loop honors one cross-cutting
   contract (kill switch, budget, idempotent checkpoints, auto-discovery test), and the
   taxonomy means a new loop slots into a category instead of inventing a pattern. Sprawl is
   47 special cases. This is 8 patterns with 47 instances."

5. "Isn't this just a Ralph loop with extra steps? Why not just Ralph it?" — Concede the
   kinship first; Huntley himself says everything is a Ralph loop, and at the bottom of every
   loop in my registry there IS one trying to get out: an agent, a prompt, a retry budget.
   "The difference is what the loop is FOR. A Ralph loop is a harness around one task: one
   prompt, no state between iterations, done when it converges, and convergence is the model
   running out of things to fix. My loops never finish. They hold a shared operating contract,
   kill switch, budget, credit-aware yield, they coordinate through a label state machine so
   every work item has exactly one owner, and a merge is authorized by executable gates, not
   by the model's own satisfaction. Ralph is a harness. This is an organization of harnesses.
   If you have one task and a weekend, Ralph it; I mean that. If the loop has to run the
   factory while you sleep, the loop needs an employer."

6. "Aren't you locked into one model or vendor?" — the other half of this month's loopcraft
   conversation (the provider-agnostic-harness thread). "No, by design. The factory reaches
   every model through a swappable agent-CLI backend — Claude, Codex, Gemini, Pi are a config
   field, not a rewrite. The lock-in in this world was never the model; it's the harness around
   it. My moat isn't a vendor — it's the structure, the conventions, and the knowledge the factory
   keeps about itself, and none of that moves when the model does."
-->
