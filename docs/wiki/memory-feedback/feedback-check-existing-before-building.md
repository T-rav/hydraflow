---
source: feedback_check_existing_before_building.md
name: feedback-check-existing-before-building
description: '2026-08-18: I rebuilt an already-shipped feature (rung-0 ledger #11055)
  and overwrote it with a thinner version. Grep for the module/script BEFORE writing,
  especially when a roadmap says ''NOW''.'
status: issue-open
issue: 11947
promoted_in: null
wontfix_reason: null
created: '2026-08-17'
---

**Never write a new module without first checking whether it exists.** On 2026-08-18 I read epic #11035's roadmap line *"Rung 0 — #11055 mode-mismatch ledger (NOW)"*, took "NOW" to mean unbuilt, and wrote `src/mode_mismatch.py` from scratch with `Write` — **overwriting the real 253-line engine** that shipped on 2026-08-12 (commit d830c9339, six modes, decision rule, sample floor, plus `scripts/mode_mismatch_report.py`). I only noticed because the existing runner failed to import symbols my thinner version lacked. Nothing was pushed; the worktree was deleted and the engine restored from origin/staging.

**Why:** a roadmap's "NOW" marks *sequence*, not *state* — the issue was already CLOSED. The repo is the only authority on what exists.

**How to apply:** before creating any file, run `git ls-tree origin/staging <dir>` / `grep -rn "<concept>" src/ scripts/` and check the issue's state (`gh issue view N --json state`). Prefer `Read` before `Write` on any path you did not create this session. If a runner/script references a module, that module is the interface contract — match it, don't replace it. Related: [[feedback_check_existing_infra_first]].

**The useful residue:** running the EXISTING instrument found two real defects it had shipped with — an allow-list of event types the factory never emits, and reading `event['payload']` when the bus writes `data` — so it classified 0 issues against a 19k-event log. Fixed in #11406, plus a `discriminating()` gate: when no classified trace carries a non-build signal, the verdict is INSTRUMENT NOT DISCRIMINATING rather than "FIXED DAG VINDICATED" (a 0% rate on a blind instrument would have closed a 12-month roadmap on a tautology).
