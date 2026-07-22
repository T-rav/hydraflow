---
id: "01KY4QKSBGMKHY3AV0JJ0QNMMD"
name: "SubprocessRunner"
kind: "port"
bounded_context: "shared-kernel"
code_anchor: "src/execution.py:SubprocessRunner"
aliases: ["subprocess execution port", "host/docker execution abstraction"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-22T10:58:15.024800+00:00"
updated_at: "2026-07-22T10:58:15.024802+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-22T10:58:15.024751+00:00"
proposal_signals: ["S1", "S2"]
proposal_imports_seen: 5
---

## Definition

SubprocessRunner is the Protocol that abstracts how a command gets executed — on the host via asyncio.create_subprocess_exec, or inside a Docker container — behind a single interface (create_streaming_process, run_simple, cleanup). Runners and loops that need to spawn a Claude Code process or shell out to git/gh depend on this seam rather than the concrete HostRunner/DockerRunner implementation, so the same call sites work unchanged whether HydraFlow is running bare-metal or containerized.

## Invariants

- Two implementations select the execution environment: HostRunner (asyncio.create_subprocess_exec on the host) and DockerRunner (inside a container)
- run_simple's cancel_check is polled every cancel_poll_interval seconds; a True verdict tears down the whole process group and raises SubprocessCancelledError rather than a plain timeout (#9577)
- cleanup() must release any held resources (containers, connections), not just terminate processes
