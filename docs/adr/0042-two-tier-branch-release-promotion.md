# ADR-0042: Two-tier branch model with automated release-candidate promotion

- **Status:** Accepted
- **Date:** 2026-04-17
- **Supersedes:** none
- **Superseded by:** none

## Context

HydraFlow agents land many PRs per day directly on `main`. Per-PR CI sometimes
passes on flaky scenarios, and integration bugs only surface when multiple
agent changes interact. `main` is both the integration branch and the release
branch, so a regression landing on `main` is a regression in "production."

## Decision

Split the branch model into two tiers:

- **`staging`** — fast integration branch. Agent PRs target this. Moves
  frequently. Expected to be usually green but not guaranteed.
- **`main`** — known-good, only advanced via automated release-candidate (RC)
  promotion PRs that pass the full test gate (unit, scenario, regression,
  smoke, typecheck, security, ui-build).

Promotion is fully automated: a new `StagingPromotionLoop` (BaseBackgroundLoop)
cuts a frozen `rc/YYYY-MM-DD-HHMM` snapshot every `rc_cadence_hours` (default 4),
opens a PR into `main`, and merges with `gh pr merge --merge --delete-branch`
on green. No human approval gate.

Merge strategy is **merge commit**, not squash. Squash-merging from a
long-lived integration branch produces a growing-diff regression (the next
RC's diff against `main` includes commits that are logically already on `main`
but commit-wise are not).

Feature is dark-launched behind `HYDRAFLOW_STAGING_ENABLED` (default false).
When false, every behavior is identical to the pre-feature state.

## Consequences

**Positive**
- `main` becomes a trustable deploy/rollback baseline.
- Soak window between merge and release catches interaction bugs.
- Per-repo `staging_branch` + `main_branch` config generalizes to multi-repo
  factory management.
- Rollback is trivial — flip the env flag.

**Negative**
- p50 time-to-main grows by ~`rc_cadence_hours / 2`.
- CI YAML must list branch names literally (no dynamic evaluation), so renaming
  `staging_branch` via env var also requires workflow edits. Single-repo scope
  today; revisit when the multi-repo factory lands.
- `main`'s history becomes two-tier (first-parent = releases, full = authors).
  Use `git log --first-parent main` for the release view.

**Neutral**
- RC failures are fail-closed (no rollback needed since `main` never moves).
  A `hydraflow-find` issue is filed; the next cycle retries.

## Alternatives considered

1. **Direct `staging → main` PR (no snapshot).** Rejected: PR diff moves while
   CI runs; never converges under agent PR volume.
2. **Tag-based promotion (no PR).** Rejected: loses the PR UI for status checks
   and audit trail.
3. **GitHub Actions cron as the scheduler.** Rejected: the user wants the
   release pipeline contained in the factory when HydraFlow begins managing
   multiple target repos. The loop is a factory capability, not external infra.
4. **Human approval gate on the promotion PR.** Rejected: explicit user goal is
   full automation.
5. **Squash-merge of the RC PR.** Rejected: produces growing-diff regressions
   on every subsequent cycle.

## References

- Spec: `docs/superpowers/specs/2026-04-17-staging-rc-promotion-design.md`
- Plan: `docs/superpowers/plans/2026-04-17-staging-rc-promotion.md`
- ADR-0003: Git worktrees for isolation
- ADR-0029: Caretaker loop pattern
