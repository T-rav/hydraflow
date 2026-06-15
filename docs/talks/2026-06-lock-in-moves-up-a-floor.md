# Once the Harness Is Commoditized, Lock In the Workflow

*The agent harness is the new lock-in layer. Make it swappable, and the lock-in climbs one floor, into the workflow.*

A recent [focused.io piece](https://focused.io/lab/the-agent-harness-is-the-new-lock-in-layer)
makes a sharp claim: in AI systems, lock-in has moved from the model to the harness. It is
right. It is also not the end of the story, and two of my own repos, sitting one directory
apart, show where the lock-in goes next.

Start with the claim. The harness is the layer wrapping the model call. Routing and model
selection. Tools and permissions. Memory. Credentials. Policy. Approval workflows. Retries
and cost controls. Traces. The argument runs parallel to cloud: nobody gets locked into raw
compute, they get locked into the Terraform, the IAM, and the eight weeks of accumulated
configuration around it. Swapping the model endpoint is easy. Swapping everything you built
around it is not.

That reading of the present is accurate. I want to push on one assumption buried inside it:
that the harness is where lock-in *settles*. It isn't. Lock-in lives at whatever layer holds
the judgment that is expensive to recreate. The harness is just where that judgment happens
to sit today, for most teams. Abstract the harness, and the lock-in doesn't disappear. It
moves up a floor.

I have a clean demonstration of this, because I built both floors.

## Two repos, one directory apart

On my laptop, `insightmesh/` and `hydraflow/` are siblings. HydraFlow was born inside
InsightMesh and pulled out after three days. Same lineage, opposite postures toward the
harness.

**InsightMesh** is a product: warm-intro pathfinding, RAG over a knowledge base,
deep-research agents answering in Slack. Open the repo and the harness is right there as
named directories. `control_plane/` holds auth, service accounts, permissions, MCP OAuth.
`mcp-gateway/` holds tool adapters and capability gating. A RAG service over Qdrant holds
memory. Langfuse holds the traces. LangGraph runs the agents. Map that against the
focused.io checklist and nearly every box is ticked: credentials, policy, tool permissions,
memory, observability, routing, retries.

And it is built *on* LangGraph, which means it touches the model call directly. InsightMesh
is the article's thesis made literal. Its lock-in is the SDK stack it stands on. Moving off
that stack means rewriting the parts of the product that make it a product.

**HydraFlow** is a different animal. It runs the full GitHub issue lifecycle on its own:
triage, planning, implementation, review, merge. You would expect it to be even more
harness-coupled than its parent. It is the opposite.

HydraFlow never touches a model call. Every LLM invocation goes out through a subprocess to
an agent CLI, and which CLI is a config field:

```python
AgentTool = Literal["claude", "codex", "gemini", "pi"]
```

Implementation agents on one backend, review agents on another, triage on a third. The
harness, the thing focused.io says you get locked into, is a swappable adapter in HydraFlow.
Claude Code, Codex, Gemini, Pi. Pick per role, change in config.

So HydraFlow did to the harness exactly what the harness did to the model. It turned the
layer below it into a commodity you can switch.

## So where did the lock-in go?

It didn't vanish. If you tried to move a team off HydraFlow, the pain would not be the model
and it would not be the CLI backend. It would be everything that accumulated one floor up.
Fifty-some architecture decision records. A 240-entry repo wiki that a loop keeps current
from live pipeline events. A label state machine that encodes the entire workflow.
Methodology playbooks. A ubiquitous-language glossary that fails CI when code drifts from it.
That is the switching cost. That is the lock-in. It just sits above the harness instead of
inside it.

Two repos, one directory apart, three layers of the same stack:

- InsightMesh is locked into its harness and SDK. The floor focused.io named.
- HydraFlow commoditized that floor and is locked into its accumulated orchestration and
  knowledge. The floor above.
- Neither is meaningfully locked into a model. The floor everyone worried about two years
  ago, now the cheapest to swap.

## The pattern

Lock-in is not a property of a layer. It is a property of accumulated judgment. It pools
wherever you have encoded the most hard-won, expensive-to-recreate decisions. For most AI
teams right now that is the harness, because the harness is the newest place they are pouring
effort. focused.io is reading the present correctly.

But it is a decision, not a destiny. You can choose which floor you want to be locked into.
If you abstract the harness the way HydraFlow does, you had better have built something
valuable on the floor above, the orchestration, the knowledge base, the workflow, or you
have commoditized your own moat away and left nothing holding the customer.

## The staircase

There is a through-line here to something I keep circling. As generation gets cheap, the
bottleneck moves up, from writing code to judging it. Lock-in climbs the same staircase, for
the same reason. The model became a commodity, so the value moved to the harness. Abstract
the harness, and the value moves to the judgment accumulated above it: the decision records,
the workflows, the institutional memory. The cheaper the layer below, the more the floor
above matters.

The agent harness is the new lock-in layer. For now. The real question was never whether you
are locked in. It is which floor you want to own when the one below it goes cheap.

*Source: ["The Agent Harness Is the New Lock-In Layer," focused.io](https://focused.io/lab/the-agent-harness-is-the-new-lock-in-layer).*
