# Architecture Compliance Check

Review the current branch diff for architectural boundary violations. This is a lightweight, per-PR complement to the full `/hf.audit-architecture` sweep. It does not modify files.

## When to Use

- After implementing changes, before committing
- When adding new imports or dependencies between modules
- When you want to verify architectural boundaries are respected

## Instructions

1. Get the diff of changes on the current branch:
   ```bash
   git diff origin/main...HEAD
   ```
   If that's empty, fall back to `git diff` (unstaged) or `git diff --cached` (staged).

2. Review the diff against the HydraFlow layer model:

   ```
   Layer 4 — Infrastructure/Adapters (I/O, external systems)
     pr_manager.py, worktree.py, merge_conflict_resolver.py,
     post_merge_handler.py, dashboard.py, dashboard_routes/

   Layer 3 — Runners (subprocess orchestration, agent invocation)
     base_runner.py, agent.py, planner.py, reviewer.py,
     hitl_runner.py, triage_runner.py, runner_utils.py,
     skill_registry.py, diff_sanity.py, scope_check.py,
     test_adequacy.py, plan_compliance.py, arch_compliance.py

   Layer 2 — Application (phase coordination, workflow orchestration)
     orchestrator.py, plan_phase.py, implement_phase.py, review_phase.py,
     triage_phase.py, hitl_phase.py, phase_utils.py, pr_unsticker.py,
     base_background_loop.py, *_loop.py (background loops)

   Layer 1 — Domain (pure data, business rules, no I/O)
     models.py, config.py

   Cross-cutting (available to all, imports only from Domain):
     events.py, state/

   Composition root (imports from ALL layers — exempt from direction checks):
     service_registry.py
   ```

3. Check for these five violation categories:

   - **Layer boundary violations** — New imports that go upward (Layer N importing Layer N+1)
   - **New coupling** — Phase importing another phase, runner importing another runner
   - **Domain pollution** — Infrastructure types leaking into `models.py` or `config.py`
   - **Missing abstraction** — New concrete dependency that should go through a protocol/port
   - **Bypass detection** — Direct `subprocess.run`, `httpx.get`, `open()` in application/runner layers

4. For each violation found, note the file path, line, severity, and suggested fix.

5. Produce structured output:

If all checks pass:
```
ARCH_COMPLIANCE_RESULT: OK
SUMMARY: No violations found
```

If violations are found:
```
ARCH_COMPLIANCE_RESULT: RETRY
SUMMARY: <comma-separated list of violation categories found>
VIOLATIONS:
- [SEVERITY] file:line - violation description - suggested fix
```

## Important

- Do NOT modify any files. This is a read-only review.
- Only flag clear violations — be conservative to avoid false positives.
- Do NOT flag `service_registry.py` for cross-layer imports (it is the composition root).
- Do NOT flag existing code that was not changed in the diff.
- This complements the static `make layer-check` — focus on judgment-based issues.
