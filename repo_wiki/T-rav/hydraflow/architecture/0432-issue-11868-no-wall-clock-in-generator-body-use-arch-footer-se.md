---
id: 0432
topic: architecture
source_issue: 11868
source_phase: plan
created_at: 2026-09-01T03:50:35.471649+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# No wall-clock in generator body — use {{ARCH_FOOTER}} sentinel

Rule: Generator bodies must not call `datetime.now()` or embed ISO timestamps. End the body with the `{{ARCH_FOOTER}}` sentinel constant so `runner._stamp_footer` supplies the generation timestamp. Pass a fixed sentinel `observed_at` into the collector instead of a live clock.

**Why:** Wall-clock in the body breaks byte-identical regeneration and makes `--check` always stale — the runner's idempotency guarantee depends on the sentinel pattern.
