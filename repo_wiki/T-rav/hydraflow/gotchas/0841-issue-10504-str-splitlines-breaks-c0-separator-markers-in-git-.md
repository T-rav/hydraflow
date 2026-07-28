---
id: 0841
topic: gotchas
source_issue: 10504
source_phase: plan
created_at: 2026-07-25T02:18:04.061411+00:00
status: active
corroborations: 1
fixed_in_pr: #10521
code_refs: src/escape/detect.py:_SHA_MARKER,src/audit/detect.py:_SHA_MARKER
---

# str.splitlines() broke C0-separator markers in git log parsing (fixed in #10521)

**Historical incident — the fix shipped in PR #10521 (closing sibling issue #10499).** `escape/detect._added_paths_for_range` once parsed `git log` output with `str.splitlines()`, which also split on the `\x1e` (Record Separator) byte embedded in the old SHA marker. The marker line never matched intact, so `CommitInfo.added_paths` came back as `()` — silently, with no exception. Downstream, `regression-pin` classification (medium confidence ⇒ CONFIRMED) was unreachable dead code and every pin commit fell through to `bug-issue`/low.

The fix replaced the separator-embedding marker with `_SHA_MARKER = "\x01ESCSHA\x01"` and switched the parse from `str.splitlines()` to an explicit `out.split("\n")` — `git log` emits bare `\n` line endings, so the explicit split is both correct and immune to any future marker or path colliding with the wider line-boundary set `str.splitlines()` honours (`\x1c`–`\x1e`, plus `\x85`/` `/` `). The same defect class was mirrored and fixed in `audit/detect` (`_SHA_MARKER = "\x01AUDITSHA\x01"`, same `out.split("\n")` parse).

**Why the lesson stands after the fix:** a parser that silently drops data on every call produces a permanently-empty field with no test failure to flag it — the bug hid until the field's downstream consumer (confirmed-escape rate) was audited for staying at 0.00. Durable takeaway: keep control-separator markers free of characters `str.splitlines()` treats as line boundaries, and prefer an explicit `str.split("\n")` when parsing `git log` output.

Shipped-fix provenance (machine-readable — verified by `WikiRotDetectorLoop`'s shipped-claim pass):

```json:entry
{"id": "0841", "rule": "str-splitlines-breaks-c0-separator-markers", "topic": "gotchas", "source_issue": 10504, "fixed_in_pr": "#10521", "code_refs": ["src/escape/detect.py:_SHA_MARKER", "src/audit/detect.py:_SHA_MARKER"]}
```

_Source line references at fix time: `src/escape/detect.py:54` (`_SHA_MARKER`, primary) and `src/audit/detect.py:29` (`_SHA_MARKER`, mirror). The `code_refs` above cite the symbol rather than the line number because the rot detector resolves symbol cites via AST and treats a purely-numeric tail as a line reference it deliberately skips._
