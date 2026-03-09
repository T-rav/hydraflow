# ADR-0024: Update SKILL.md Examples When Removing Modules

**Status:** Proposed
**Date:** 2026-03-09

## Context

HydraFlow relies on `.codex/skills/` SKILL.md files to guide AI agents through
common workflows. Each SKILL.md contains example patterns that reference
specific source files (e.g., `src/cli.py`, `src/models.py`). When a module is
removed or renamed during a refactor, the corresponding SKILL.md examples can
become stale — pointing agents at files that no longer exist.

This was discovered during the removal of `cli.py` (consolidated into
`server.py` in PR #2457). The SKILL.md files under `.codex/skills/` still
referenced `cli.py` in their example invocations, causing agents to look for a
non-existent module and produce incorrect plans.

ADRs are historical records and do **not** need updating when code changes —
they document the decision at the time it was made. SKILL.md files, however,
are **operational instructions** consumed by agents in every session. Stale
examples in SKILL.md files actively mislead future agents, making this a
correctness concern rather than a cosmetic one.

## Decision

Adopt the following rule for all code-removal and module-rename changes:

1. **Check `.codex/skills/` for stale references.** Any PR that removes or
   renames a source module must search SKILL.md files for references to the
   old module path and update them to reflect the new location (or remove the
   example if the workflow no longer applies).

2. **Include `.codex/skills/` in the review checklist.** The review phase
   agent should treat stale SKILL.md references as a defect, on par with
   broken imports or dead code.

3. **Do not update ADRs for removed modules.** ADRs remain as-is because they
   document historical decisions, not current file paths.

### Operational impact on HydraFlow workers

- **Plan phase:** Agents read SKILL.md files to understand available
  workflows. Stale file references cause planners to produce invalid plans
  that reference non-existent modules, wasting an implementation cycle.
- **Implement phase:** Implementation agents that follow stale SKILL.md
  examples will attempt to import or modify removed files, leading to
  immediate failures or incorrect patches.
- **Review phase:** Reviewers should flag PRs that remove modules without
  updating SKILL.md references. This is a lightweight check (grep for the
  removed filename across `.codex/skills/`).
- **HITL phase:** Reduces human escalations caused by agents producing broken
  plans or implementations from stale instructions.

## Consequences

**Positive**

- Eliminates a class of silent agent failures caused by outdated operational
  instructions.
- Low overhead: the check is a simple grep during code review, not a new tool
  or process.
- Clear boundary between mutable instructions (SKILL.md) and immutable
  records (ADRs) prevents unnecessary churn on historical documents.

**Negative / Trade-offs**

- Adds a manual step to the module-removal workflow that developers must
  remember. Until this is automated (e.g., a pre-commit hook or CI check),
  it relies on reviewer diligence.
- SKILL.md files may accumulate references to internal paths, increasing
  maintenance surface as the codebase evolves.

## Alternatives considered

1. **Automate stale-reference detection in CI** — desirable long-term but
   premature now; the volume of SKILL.md files is small enough for manual
   review. Can be revisited if the skills directory grows significantly.
2. **Use symbolic references (e.g., "the server entry point") instead of
   concrete paths in SKILL.md** — rejected because agents perform better
   with explicit file paths; vague references reduce plan accuracy.
3. **Update ADRs alongside SKILL.md files** — rejected because ADRs are
   historical records; updating them creates churn and obscures the
   original decision context.

## Related

- Source memory: [#2465 — SKILL.md examples need updates when code is removed](https://github.com/T-rav/hydra/issues/2465)
- Implementing issue: [#2466](https://github.com/T-rav/hydra/issues/2466)
- CLI removal PR: [#2457 — Remove CLI layer and consolidate into server API](https://github.com/T-rav/hydra/pull/2457)
- Skills directory: `.codex/skills/` (SKILL.md files)
