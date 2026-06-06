---
id: "01KT3WKPR5MN8QJ14CF77W6K6"
name: "WikiRotDetectorLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/wiki_rot_detector_loop.py:WikiRotDetectorLoop"
aliases: ["wiki rot detector loop", "wiki rot detector", "cite freshness loop"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K4"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K6"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01KTAN07XWECDDWZ84AQD4HFC7"}, {"kind": "depends_on", "target": "01KTAMZH9S4EH0H06BJ11QNRZE"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T00:00:00.000000+00:00"
updated_at: "2026-06-06T01:04:43.481148+00:00"
---

## Definition

Trust-fleet caretaker loop (ADR-0045 §4.9) that detects broken code citations in per-repo wikis. On each tick it walks every `RepoWikiStore`-registered repo's wiki entries, extracts code references via three patterns (`path.py:symbol`, dotted `src.module.Class`, and bare identifiers inside fenced code blocks as hints only), then verifies each hard cite. HydraFlow-self cites are checked via AST introspection; managed-repo cites are verified via grep over wiki markdown mirrors. For each broken cite the loop files a `hydraflow-find` + `wiki-rot` issue via `PRManager`, with a fuzzy-match suggestion from `difflib.get_close_matches` when the containing module still exists. After three unresolved attempts for a given slug+cite pair the loop escalates to `hitl-escalation` + `wiki-rot-stuck`.

## Invariants

- Kill-switch: `enabled_cb("wiki_rot_detector")` only — no config field (ADR-0049 trust-fleet convention).
- Calls `reraise_on_credit_or_bug(exc)` in its broad except block to prevent `CreditExhaustedError` from being silently swallowed.
- Does not run on startup (`run_on_startup=False`) — the first tick is deferred to the normal interval.
