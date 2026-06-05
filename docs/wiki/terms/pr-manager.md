---
id: "01KTAN07XWECDDWZ84AQD4HFC7"
name: "PRManager"
kind: "service"
bounded_context: "shared-kernel"
code_anchor: "src/pr_manager.py:PRManager"
aliases: ["pr lifecycle service", "pull request manager", "github mutation facade"]
related: [{"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B6"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9C3"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B4"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B5"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B2"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A2"}, {"kind": "depends_on", "target": "01KSY46G6QFVCRC5FE26Q5FKJY"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A4"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A9"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A7"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A1"}, {"kind": "depends_on", "target": "01KT3WKPR5MN8QJ14CF77W6K6"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-05T01:05:16.732899+00:00"
updated_at: "2026-06-05T01:05:16.732902+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-06-05T01:05:16.732756+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 12
---

## Definition

PRManager is the shared-kernel service responsible for the full pull-request lifecycle against GitHub: pushing branches, opening and merging PRs, posting and truncating comments, swapping labels, creating and querying issues, and managing repo labels. It is the sole outbound mutation surface for GitHub in HydraFlow — every caretaker loop that needs to file an issue, swap a label, or open a PR does so through PRManager. It enforces a validated repo slug before any mutation, respects the global dry_run flag, and retries transient gh-CLI failures via configurable max_retries.

## Invariants

- Repo slug must match `owner/name` pattern before any mutation is attempted (`_assert_repo`).
- All state-mutating operations are no-ops when `HydraFlowConfig.dry_run` is true.
- Label-count queries are cached with a 30-second TTL to reduce gh-CLI call volume.
