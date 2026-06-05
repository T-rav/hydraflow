---
id: "01KTBHAP0E4RHCFZVEC1P12QQM"
name: "GitHubIssue"
kind: "entity"
bounded_context: "shared-kernel"
code_anchor: "src/models.py:GitHubIssue"
aliases: ["github issue", "issue"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-05T09:20:18.958473+00:00"
updated_at: "2026-06-05T09:20:18.958477+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-06-05T09:20:18.958393+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 2
---

## Definition

A GitHub issue as seen by HydraFlow's domain layer: the primary work item the system fetches, enqueues, and drives through the issue→PR pipeline. Carries identity (issue number), lifecycle state (OPEN/CLOSED via GitHubIssueState), and the metadata all major ports exchange — IssueFetcherPort fetches collections of them, IssueStorePort queues and tracks them, and PRPort and PRManager act on them throughout the pipeline.

## Invariants

- State is always one of GitHubIssueState.OPEN or GitHubIssueState.CLOSED — no other lifecycle values are recognised at this layer.
