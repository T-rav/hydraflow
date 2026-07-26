---
id: 1032
topic: gotchas
source_issue: 10566
source_phase: plan
created_at: 2026-07-25T23:57:01.883172+00:00
status: active
corroborations: 1
---

# Bulk repo_wiki repairs must ship in the same PR as their generator fix

`RepoWikiLoop` rewrites `repo_wiki/T-rav/hydraflow/` on every maintenance tick, so a hand-repaired topic (e.g. `dependencies/`) merged *before* the generator fix in `src/wiki_compiler.py` lands gets silently clobbered within hours. Land data repair in the same PR as the fix that stops the corruption (P5 depends on P2 in issue #10566's task graph), and treat any repo-wide backfill (2,077 misdirected `superseded_by` pointers across `testing/`, `gotchas/`, `patterns/`) as a separate high-blast-radius follow-up issue, not bundled work.

**Why:** repairing data without fixing the generator is pure churn — the next tick regenerates the same wrong edges.
