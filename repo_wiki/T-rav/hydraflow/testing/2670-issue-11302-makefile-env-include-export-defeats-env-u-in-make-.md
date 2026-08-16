---
id: 2670
topic: testing
source_issue: 11302
source_phase: plan
created_at: 2026-08-16T04:43:31.977983+00:00
status: active
corroborations: 1
---

# Makefile .env include+export defeats env -u in make recipes

The `Makefile` (lines 7-9) uses `-include $(PROJECT_ROOT)/.env` followed by `export`, which promotes the real `.env` into every recipe's environment. `env -u ZAI_API_KEY make quality` does NOT work — make re-sources `.env` after the shell strips the var.

To test hermetically against provider keys, scrub inside `conftest` (Python-level `os.environ`), not at the shell/make invocation level.

**Why:** Blaming `.env` loading on `_dotenv_lookup` or the `_DOTENV_INERT_ROOTS` seam (#10902) is a misdiagnosis — nothing in the pytest path reads `.env` from disk; the Makefile is the culprit.
