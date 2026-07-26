---
id: 1143
topic: gotchas
source_issue: 10613
source_phase: plan
created_at: 2026-07-26T10:32:19.699673+00:00
status: active
corroborations: 1
---

# Scrub secrets from logs and JSONL per ADR-0085

Never log fetched secret values or pass bare variables to `logger.*` calls. Scrub error and response text before logging or writing to JSONL paths. Use literal format strings in `logger.warning` calls.
**Why:** ADR-0085 mandates that fetched values live in process memory only; failing to scrub error text risks leaking tokens to disk.
