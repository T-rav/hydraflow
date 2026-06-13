---
id: "01KRBL0F20M01PGF32CF88W9C1"
name: "DependabotMergeLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/dependabot_merge_loop.py:DependabotMergeLoop"
aliases: ["dependabot merge loop", "bot pr merge loop", "auto-merge bot PRs loop"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K4"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K7"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: ["01KRBX2N4QP7VW8FGH3J5YD0M5"]
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-06-12T04:18:46.416686+00:00"
---

## Definition

Caretaker loop that polls open PRs via `GitHubDataCache` and auto-merges those authored by Dependabot and other configured bot accounts after CI passes (ADR-0054, ADR-0057, ADR-0058). The list of bot authors is configurable via `config`; the loop compares `pr.author.lower()` against the set. Only PRs with a passing `ReviewVerdict` are merged — CI must be green before the loop touches a PR.

## Invariants

- Author matching is case-insensitive.
- CI must pass (`ReviewVerdict` green) before any merge is attempted; the loop never force-merges.
- Kill-switch is via `enabled_cb("dependabot_merge")` and `config.dependabot_merge_loop_enabled` (ADR-0049).
