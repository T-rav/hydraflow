---
id: "01KTANDXA5DG4WYGX733AH0FHC"
name: "SubprocessRunner"
kind: "port"
bounded_context: "shared-kernel"
code_anchor: "src/execution.py:SubprocessRunner"
aliases: ["subprocess executor", "process runner"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-05T01:12:44.613933+00:00"
updated_at: "2026-06-05T01:12:44.613938+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-06-05T01:12:44.613851+00:00"
proposal_signals: ["S1", "S2"]
proposal_imports_seen: 3
---

## Definition

A Protocol defining the subprocess execution contract used by loops and runners throughout HydraFlow. It abstracts the host-vs-Docker execution boundary, enabling AgentRunner, ReportIssueLoop, and SentryLoop to be injected with either a HostRunner (asyncio.create_subprocess_exec on the host) or a DockerRunner (containerised execution) without changing call-site code. The interface exposes two operations: create_streaming_process for long-running agent runs where the caller manages stdin/stdout lifecycle, and run_simple for command-and-capture invocations with a hard timeout.

## Invariants

- Two standard implementations: HostRunner (host asyncio) and DockerRunner (containerised execution)
- cleanup() must be called by callers to release resources held by container-based implementations
