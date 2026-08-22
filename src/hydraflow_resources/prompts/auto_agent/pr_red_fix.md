# PR CI auto-fix (real red)

You are dispatched by PrRedRepairLoop (#10027 Phase 2) because CI is red on
YOUR branch and the failure does NOT match any known infra-flake signature
(cancelled run / zero failed steps / failed setup step / vanished logs) —
this looks like a real regression in the diff, not CI infrastructure.

- **PR:** #{PR_NUMBER}
- **Branch:** `{PR_BRANCH}`

## CI failure log

The following is the failing-job log tail from the most recent settled-red
CI run on this branch (`gh run view --log-failed`).

```
{CI_FAILURE_LOG}
```

## Recent commits (last 3)

The following are the diffs of the last three commits on this branch.
Cross-reference with the CI failure log above to find which change broke
the build.

```diff
{RECENT_COMMIT_DIFFS}
```

## Constraints (per ADR-0050 envelope)

- Do NOT modify any file under `.github/workflows/`, `.git/`, `prompts/`,
  `src/preflight/`, or `src/pr_red_repair_loop.py`.
- Do NOT use `WebFetch` (CLI restriction enforced for the `claude` backend;
  honor-system for codex/gemini per `_envelope.md`).
- All edits must keep `tests/` green and `make quality` clean.

## Your task

1. Read the CI failure log and recent commit diffs above to find the root
   cause.
2. Make the minimal code change that would make CI green again.
3. Commit on the current branch (`{PR_BRANCH}`) with a message describing
   the fix.
4. Push the branch.

## Escalation

If the failure is not fixable within your tool budget, do nothing — the
caretaker loop will retry on the next tick and, after
`pr_red_repair_dispatch_max_attempts` consecutive misses, label the PR
`hydraflow-hitl` so a human picks it up.
