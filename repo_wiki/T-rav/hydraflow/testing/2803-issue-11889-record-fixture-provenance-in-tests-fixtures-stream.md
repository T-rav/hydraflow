---
id: 2803
topic: testing
source_issue: 11889
source_phase: plan
created_at: 2026-09-01T10:19:26.410503+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Record fixture provenance in tests/fixtures/stream_json/README.md

Every new `.jsonl` fixture under `tests/fixtures/stream_json/` must record its capture command (e.g., `codex exec --json --skip-git-repo-check "run: cat /nonexistent"`) or, when derived from a vendor schema, the vendor doc URL and version.

Redact cwd/session ids from real captures.

**Why:** Without provenance, a fixture cannot be regenerated when the upstream wire format changes, and its validity becomes unverifiable.
