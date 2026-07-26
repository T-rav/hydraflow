---
id: 1137
topic: gotchas
source_issue: 10591
source_phase: plan
created_at: 2026-07-26T03:23:10.272087+00:00
status: superseded
corroborations: 1
superseded_by: 1144
---

# Fix wiki-rot cite regex in the extractor, never as a downstream .isdigit() filter

When a cite-extraction bug surfaces in `WikiRotDetectorLoop`, fix `_STYLE_A_RE` in `src/wiki_rot_citations.py` itself (e.g. tighten the symbol group to `[A-Za-z_]\w*`), not with an `.isdigit()` guard in `_check_cite` or the loop. Example: `tests/regressions/test_issue_10591.py` includes a test that scans real `docs/wiki/` by calling `extract_cites` directly — a loop-level filter passes the loop's own tests but leaves this pin red, because other consumers (shipped-claim pass, issue bodies, fuzzy suggestions) call `extract_cites` directly and inherit nothing from a loop-side patch.

**Why:** the regex is the single source of truth for what counts as a symbol cite; patching a caller only fixes that one call site and leaves every other consumer exposed to the same false positive.
