---
id: "01KY4QGA4VF2GJDCW3ZVKNBPMY"
name: "PRManager"
kind: "adapter"
bounded_context: "shared-kernel"
code_anchor: "src/pr_manager.py:PRManager"
aliases: ["pr manager", "github adapter", "pull request manager"]
related: [{"kind": "depends_on", "target": "01KVHDB0GY6PSQPWY90DH8TNQS"}, {"kind": "depends_on", "target": "01KY4QF8BE4Y5782543MPQNDQ0"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K3"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KYABD5XVX4ZXFXT3Z76KMQZ0"}, {"kind": "depends_on", "target": "01KYBV9N8VSTKDRVDFC0FE40ZM"}, {"kind": "depends_on", "target": "01KYM003P7D6GN4KSS1X9RBEXQ"}, {"kind": "depends_on", "target": "01KYW34KGZNXKF5N1TNB7VB731"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-22T10:56:21.147213+00:00"
updated_at: "2026-08-14T05:32:18.123535+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-22T10:56:21.147157+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 13
---

## Definition

PRManager is the gh-CLI-backed adapter that manages the full pull-request and issue lifecycle for HydraFlow: pushing branches, creating and merging PRs, creating/listing/closing GitHub issues, swapping pipeline labels, and posting size-bounded PR/issue comments. It is the single concrete surface that caretaker loops, reviewers, and builders across the system call to talk to GitHub — the label-swap operations it exposes are what drive the label-state-machine transitions (ADR-0002) that move issues through the pipeline, and its cost-alert hooks and pipeline-label listener wire it into cross-cutting dashboard and budgeting concerns.

## Invariants

- Label-count queries are served from an in-memory cache with a 30s TTL (_LABEL_CACHE_TTL) to bound gh API pressure.
- Successful pipeline-label swaps notify an optional registered listener (_pipeline_label_listener) so dashboard state updates within seconds instead of waiting for the periodic label poll.
- Comment bodies are chunked to GitHub's comment size limit with truncation markers via CommentFormatter before posting.
