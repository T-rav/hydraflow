---
id: 2693
topic: testing
source_issue: 11317
source_phase: plan
created_at: 2026-08-16T07:49:38.021643+00:00
status: active
corroborations: 1
---

# Use `clean_zai_env` fixture for ZAI key-sensitive tests

Request the `clean_zai_env` fixture from `tests/conftest.py` for `*_without_zai_key` tests instead of local `monkeypatch.delenv` hand-lists.
Example: Tests setting `ZAI_API_KEY` must clear `ZAI_CODING_PLAN_KEY` first due to harness preference order.
**Why:** Local hand-lists duplicate logic and fail to clear both the plan key and REST lane keys simultaneously.
