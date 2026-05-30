# Runbook: Adding a Branch-Protection Gate

How to add a new required check without self-blocking the introducing PR. See
[ADR-0082](../../adr/0082-declarative-gate-contract.md) for the why; the gate
set lives in [`gates.toml`](gates.toml) and is the source of truth.

## The ordering problem

A required status check that has never run on the base branch reads as
"Expected, waiting for status" and blocks every PR forever. So a gate must
**exist and be green on the base branch before it is marked required**. Adding
the record and requiring it in the same step self-blocks the introducing PR.

Useful property that makes this safe: for `pull_request` events GitHub runs the
**head's** workflow, so a newly added gate's job runs on its own introducing PR
(visible in the checks rollup) even before it is required. Use that to confirm
the gate is green before requiring it.

## Steps

1. **Add the binding(s).** Add a `[[gate]]` record to `gates.toml` with the
   check `name`, `dimension`, `tier`, `required_on`, `runs_on`, `languages`,
   `requires_capability`, the producing `workflow` + `job`, and the
   `make_target`. For a tool that varies by capability (CodeQL vs Semgrep) or
   language (pip-audit vs npm audit), add one record per binding, all sharing
   the `dimension`; resolution picks the one whose `languages` and
   `requires_capability` match the repo's `[repo]` profile. Mark a gate that is
   not yet wired `status = "planned"` so it never reads as active.

2. **Add the CI job + config + tested helper.** Create the producing workflow
   job (its `name:` must equal the gate's `name`). Put tool config in the
   language manifest (`pyproject.toml`, `package.json`). Put logic in a small
   script with unit-tested pure functions, invoked identically locally and in CI
   via a `make <target>`. Gitignore any generated artifact.

3. **Regenerate.** `make gen-gates` writes the ruleset JSON and the README gate
   table. `make gen-gates-check` (and the `Gates Drift` CI job) fail if the
   committed artifacts drift, and `validate()` fails if any active gate's
   `(workflow, job)` producer does not exist. A planned gate is skipped by both.

4. **Land on the base branch first.** Open the PR (the new job runs on it for
   free as the head's workflow). Merge it. The gate is now present and green on
   the base branch, gated only by the *existing* required checks.

5. **Require it.** Flip the gate to `required_on` the branch (if it was
   `planned`, also flip `status = "active"`), regenerate, and apply protection:

   ```bash
   make gen-gates
   python scripts/setup_branch_protection.py --apply
   ```

6. **Verify live.** Confirm the live ruleset matches the canonical config:

   ```bash
   python scripts/setup_branch_protection.py --audit
   gh api /repos/<owner>/<name>/rulesets/<id> --jq '.rules[] | select(.type=="required_status_checks")'
   ```

## Prefer the umbrella aggregator over many path-filtered checks

GitHub treats a path-filtered **SKIPPED** required check as "not passed", so a
docs-only PR blocks forever if a job-conditional check is required directly.
Rather than require each conditional job, require the single **`CI Gate`**
umbrella job (`.github/workflows/ci.yml`): it runs `if: always()`, `needs:` all
conditional jobs, and fails only if a needed job ended in `failure`/`cancelled`
(a SKIPPED job counts as passed). Requiring only `CI Gate` gives strict gating
with path-filter compatibility, and adding a new job to its `needs:` never means
editing branch protection again.

`CI Gate` follows the same ordering rule: it must be green on the base branch
before being marked required. Until then it runs as a visible, non-required
check.
