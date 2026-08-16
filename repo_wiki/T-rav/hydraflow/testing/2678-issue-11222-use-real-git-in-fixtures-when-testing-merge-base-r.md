---
id: 2678
topic: testing
source_issue: 11222
source_phase: plan
created_at: 2026-08-16T05:46:03.675034+00:00
status: active
corroborations: 1
---

# Use real git in fixtures when testing merge-base ranges

When a regression test exercises merge-base commit-range logic in `scripts/check_console_conformance.py` (`_resolve_merge_base`), build a real repository in `tmp_path` using shell `git` commands. Scaffold `agents/` trees with personas (`authority:`/`feeds:` frontmatter), chamber files, and conformant records; branch `staging` that rewrites a merged record; `git clone` to create `origin/*` refs; cut `rc/...` from `origin/staging`. Do not mock `git` or fake ref discovery. **Why:** merge-base semantics depend on real parent chains and ref topology that mocks cannot reproduce.
