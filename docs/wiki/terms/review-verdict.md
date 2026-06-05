---
id: "01KTANCQNKWYRJ5ETEVNAMEY5A"
name: "ReviewVerdict"
kind: "value_object"
bounded_context: "shared-kernel"
code_anchor: "src/models.py:ReviewVerdict"
aliases: ["review decision", "review outcome", "pr verdict"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-05T01:12:06.067616+00:00"
updated_at: "2026-06-05T01:12:06.067619+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-06-05T01:12:06.067527+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 3
---

## Definition

An enumeration of the possible outcomes an automated or human reviewer can submit for a pull request — at minimum APPROVE and CHANGES_REQUESTED. ReviewVerdict is the canonical domain token that crosses the PRPort boundary whenever the system acts as a reviewer: callers pass a ReviewVerdict to PRPort.submit_review() to express a deliberate review decision rather than a raw string. DependabotMergeLoop, for example, submits ReviewVerdict.APPROVE after CI passes before calling merge_pr(), making the verdict an explicit, named step in the bot-PR lifecycle rather than an implicit side-effect of the merge call.

## Invariants

- Value must be a member of the closed set of review actions recognised by the GitHub Reviews API (e.g. APPROVE, REQUEST_CHANGES)
