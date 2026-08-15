---
id: 2621
topic: testing
source_issue: 11193
source_phase: plan
created_at: 2026-08-15T00:39:44.183343+00:00
status: active
corroborations: 1
---

# Use AST over regex for ADR path pinning in regression tests

Use AST scanners, not regex, to detect hard-coded ADR filename pins in `tests/regressions/`.

- Regex flags ~31 false positives in T-rav/hydraflow (synthetic `tmp_path` fixtures like `0049-fixture.md`, wiki topic pages, and meta-tests quoting defect shapes).
- AST scanner (`tests/architecture/adr_pin_scan.py`) resolves path provenance, flagging pins only when joined onto the real `docs/adr` dir.

**Why:** Text regex ignores path provenance and flags legitimate fixtures, weakening or reverting the architecture guard.
