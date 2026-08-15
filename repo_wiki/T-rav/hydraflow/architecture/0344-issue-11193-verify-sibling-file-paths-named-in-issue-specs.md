---
id: 0344
topic: architecture
source_issue: 11193
source_phase: plan
created_at: 2026-08-15T00:39:44.183395+00:00
status: active
corroborations: 1
---

# Verify sibling file paths named in issue specs

Verify the existence of sibling files named in issue specs before copying their patterns.

- Issue #11193 named `tests/architecture/test_adr_no_double_colon_citations.py` as a sibling, but it does not exist.
- The actual structural sibling to copy is `tests/architecture/test_adr_source_citations_exist.py`.

**Why:** Relying on unverified paths in specs leads to copying non-existent patterns or breaking the build.
