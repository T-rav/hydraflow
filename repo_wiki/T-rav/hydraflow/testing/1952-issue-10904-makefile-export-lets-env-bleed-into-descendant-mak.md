---
id: 1952
topic: testing
source_issue: 10904
source_phase: plan
created_at: 2026-07-31T10:40:34.520325+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Makefile export + ?= lets env bleed into descendant make

Use `:=` not `?=` for any Makefile variable that also appears under an `export` directive. In `Makefile:9` (`export`) + `Makefile:62` (`PYTEST_SERIAL_PATHS ?=`), a descendant `make` inherits a stale env value — an 8-path value overrides the file's 9 paths. `:=` ignores the environment; command-line `make VAR=…` still wins. Same fix applies to `PYTEST_PARALLEL`.

**Why:** `?=` captures the environment silently, so stale values from a parent shell change which tests run without any visible diff.
