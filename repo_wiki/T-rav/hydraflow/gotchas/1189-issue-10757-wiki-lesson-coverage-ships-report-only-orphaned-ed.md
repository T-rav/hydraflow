---
id: 1189
topic: gotchas
source_issue: 10757
source_phase: plan
created_at: 2026-07-28T00:08:58.218759+00:00
status: active
corroborations: 1
---

# Wiki lesson coverage ships report-only — orphaned edges are data, not failures

Rule: `src/wiki_lesson_coverage.py` and `scripts/audit_wiki_lesson_coverage.py` are diagnostic-only — no `--apply` flag, no CI gate, `repo_wiki/` stays byte-identical after every run.

The live corpus has ~307 orphaned `left_on_primary` edges. Turning those into a failing gate would red the build on pre-existing corpus debt. The data sweep belongs to #10753.

**Why:** Shipping a gate before triaging 307 real orphaned lessons would block the build on debt unrelated to the coverage tool, and would also violate the RepoWikiLoop ownership boundary on `repo_wiki/` entries.
