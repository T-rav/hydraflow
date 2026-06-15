# When Code Becomes FLUID, Where Does the Work Go?

*When the grunt work gets cheap, deciding what is worth doing becomes the job.*

For four months I have been running a system called HydraFlow. Its tagline is the whole
pitch: intent in, software out. It opens its own issues, writes the fix, runs the tests,
and merges the pull request, mostly without me in the loop. Forty-seven loops. More than
1,600 merged PRs. Around 15,800 tests. The marginal cost of a finished, tested,
mergeable PR runs about three to seven dollars.

I built it believing the hard part was getting an agent to produce a correct change. For
the kind of software HydraFlow works on, that part is close to solved. Point it at a
problem and it will generate a valid fix, cheaply, overnight, while I sleep. Most
mornings there is more finished work waiting than I would have produced in a week by hand.

I expected that to feel like winning. It felt like a new problem.

Because the moment a finished fix costs three dollars, the question stops being "can we
fix this." It becomes "of the several hundred things this system could do tonight, which
ones should it?"

## The backlog was always infinite

Every real system carries an effectively infinite backlog. Tech debt. Security findings.
Dependency upgrades. Flaky tests. Performance work. Accessibility gaps. Documentation
that drifted out of date. A code smell someone flagged two years ago and nobody had time
to chase. The list never had a bottom, and it never will. Anyone who has run a backlog
knows it fills faster than it drains.

What kept that infinity manageable was not discipline. It was scarcity.

## Scarcity was doing your prioritizing for you

You had a few engineers and a finite number of hours, so you did the handful of things at
the top and the rest waited. The triage was real, but most of it was never written down.
The constraint did it for you. You were not calmly selecting the best five candidates out
of a thousand on their merits. You were doing the five you had capacity for, and the
merits sorted themselves out roughly, under pressure, in standups and planning meetings
nobody enjoyed.

That is the part cheap generation breaks.

When the cost of execution falls toward zero, the constraint that used to do your
prioritizing disappears. You are no longer limited to five. You can do five hundred. And
the instant you can do five hundred, you have to answer a question you were never
actually forced to answer before: which of these is worth doing?

The judgment was always there. It was hidden inside the scarcity. Pull the scarcity out
and the oldest question in engineering leadership is standing in the middle of the room
with nothing in front of it.

Where does the work go?

## The only question

This is not a new question. In a sense it is the only one. More worth doing than you can
do, and a finite amount of attention to decide with. Every engineering leader has been
answering it their whole career, usually implicitly, often under the cover of "we don't
have the headcount." Cheap generation did not invent the question. It removed the excuse
that used to stand in for the answer.

And the answer still needs a person. Not because the machine cannot act. It plainly can.
Because deciding what is worth building means weighing things the machine has no access
to. What the business actually cares about this quarter. Which risk would end the company
versus merely irritate it. What a competitor is about to ship. Which of two equally valid
fixes buys you room to move next year. That is judgment, and it takes time and effort. The
effort does not shrink just because the typing did. If anything it grows, because there is
now more it could be applied to.

## "But we already prioritize"

A fair objection: this is just product management, and we have been doing it forever.
True, and that is the point. What changed is not that prioritization appeared. It is that
the cost structure inverted underneath it.

Old prioritization sequenced a scarce, expensive build capacity. The question was "what
do we spend our limited engineering against," and the limit was so binding that it made
most of the decision for you. You ranked the top of the list because the bottom was never
going to get built anyway.

New prioritization rations an abundant, cheap build capacity against the things that are
now scarce: judgment, attention, and tolerance for risk. The bottom of the list can get
built now. So deciding it should not is suddenly a real, deliberate choice, and it carries
a cost it never used to. Every cheap thing you green-light still consumes review, still
widens the surface area, still has to be governed even though it was nearly free to make.
Abundance on the supply side does not make the demand-side decisions cheaper. It makes
them more frequent and more consequential.

That is why this feels different even though the words are the same. The scarce resource
moved. The discipline has to move with it.

## The grunt was the toll, not the job

Writing the fix, running the tests, wiring up the PR, chasing the flaky test until it goes
green: that was always grunt labor. We called it the job because it was where the hours
went. But it was the toll you paid to reach the decision, not the decision itself. The
decision was always the same one. Is this the right thing to spend on? The grunt stood in
front of it and ate most of the day, so you rarely had to look the decision in the eye.

Take the grunt away and you arrive at the decision immediately, and then again, and then
again. Every night HydraFlow hands me a pile of finished, correct work it is ready to
merge, and the only thing between that pile and production is me deciding which of it
should exist at all. The labor that used to fill the day is gone. What is left is the part
that was always the hard part, and was always the actual point: judgment about what is
worth doing.

That is the move. Not "the engineer gets replaced." The engineer gets elevated, up out of
the doing and into the deciding, because the doing got cheap enough to give away.

And here is the part worth sitting with. The tool that removes the grunt is not the
durable advantage. Everyone is going to have a version of it soon. Once the doing is a
commodity, the only thing left to compete on is the judgment about where to point it. A
machine that builds anything is impressive for about a year. The taste for what is worth
building does not commoditize, because it is not a feature you can ship. It is the thing
the feature was always there to serve.

## What I am not claiming

I want to be precise about what I am not saying, because the easy version of this essay is
dishonest.

I do not have an expected-value engine. HydraFlow does not produce a ranked table of fixes
with costs and benefits and confidence percentages. I have seen those tables in pitch
decks, the ones with rows like "upgrade this dependency: two hours, ninety-five percent
confidence, high risk reduction." Those numbers are invented. Nobody has a calibrated
model that generates them for real software work, myself included, and a table of made-up
confidence is worse than no table at all, because it launders a guess into something that
looks like a decision, and quietly tells you the judgment can be automated away. It can't.
That is the whole point.

What I have is narrower and, I think, more honest. I ran a system until execution stopped
being the bottleneck, and I watched the bottleneck move up to judgment. That is an
observation, not a product.

## What deciding well would actually take

So what would it take to decide well, when supply is cheap and the backlog is bottomless?
At minimum, four things, none of them solved.

A way to express what the business values, in terms a system can act on, that is more
honest than a priority field on a ticket.

A sense of blast radius: which changes are reversible and cheap to be wrong about, and
which are not. This is the one I trust most, because it is the closest to legible, and
HydraFlow already runs on it. The system is allowed to act on its own precisely where
being wrong is recoverable, and nowhere else.

Calibrated confidence: not a number somebody typed into a cell, but an actual track record
of how often this kind of change, in this kind of place, lands cleanly.

Opportunity cost: the thing you did not do tonight because you did the other thing. The
hardest of the four to see, and the most expensive to get wrong.

Most of that is not machine-legible today, and I do not expect to close the gap next
quarter. That is the reason a human stays in the loop to guide and direct. The inputs to
the decision live mostly in the heads of the people who run the business, and getting them
out is slow, manual, unglamorous work. The details take time and effort. That is not a
defect in the tooling. That is where the job went.

## The same shift, from the other chair

I have a talk coming up that asks where the engineer goes when the machine writes the
code. This essay is the same shift seen from the other chair. One question is about the
person: what is the work now? The other is about the work itself: where does the effort
and the attention get pointed now? They are the same event. The grunt got cheap, and the
instant it did, the deciding became the whole job.

The work still goes somewhere. Someone still decides where. That decision used to be made
for you by the plain fact that you could not afford to do everything. You can afford to do
nearly everything now, and the bill for that abundance arrives as judgment: harder,
slower, more human, and more obviously the point than it has ever been allowed to look.

Where does the work go? Up. Out of the doing and into the deciding, which was always
the hard part, and is now the only part that still needs you.

---

<!-- DRAFT NOTES — strip before publishing
- Reframed away from the FinOps / capital-allocation framing. The spine is the elevation
  of work: the machine takes the grunt labor, the human moves up into the decisions. NOT
  a cost-governance story. The cloud-cost / FinOps analogy was cut, which also removed the
  previously unattributed Substack source.
- Receipts used (verify still current at publish time): 47 loops, 1,600+ merged PRs,
  ~15,800 tests, $3–7/PR.
- Companion talk: "When Code Becomes FLUID, Where Does the Engineer Go?" (GOTO, June 24).
-->
