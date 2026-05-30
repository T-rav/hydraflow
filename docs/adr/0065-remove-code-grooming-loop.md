# ADR-0065 — Remove CodeGroomingLoop

**Status:** Accepted
**Date:** 2026-05-19
**Enforced by:** (process)

The factory enforces this via `grep -rn 'code_grooming\|CodeGrooming' src/ tests/ docs/` returning no live references — only this ADR and historical date-stamped snapshots in `docs/arch/area_review_caretaking_2026-05-12.md` are allowed to mention the removed loop. Closes #8984.
**Related:** [ADR-0029](0029-caretaker-loop-pattern.md) — Caretaker Loop Pattern (this ADR removes one of the four original caretakers); `.claude/commands/hf.audit-code.md`; `.codex/skills/hf.audit-code/SKILL.md`.

## Context

`CodeGroomingLoop` (`src/code_grooming_loop.py`) shelled out to the Claude CLI nightly with the `/hf.audit-code` skill, regex-extracted JSON findings from a free-form transcript, and filed GitHub issues for `critical`-severity items only. It was one of the four loops introduced under the caretaker pattern in ADR-0029.

After ~6 months in production the investment-to-value ratio is poor:

- The loop already self-limited to `critical` (`_ACTIONABLE_SEVERITIES = frozenset({"critical"})`) with an in-code comment admitting that "high findings are deliberately ignored — over-investing in non-critical cleanup crowds the factory out of work that actually ships." That admission is the case for deleting the whole loop, not for keeping a degraded one.
- The finding extractor (`_FINDING_RE`) parsed nested JSON out of free-form LLM output — a fragile coupling between the audit skill's output shape and the loop's parser. The shape-drift warning at line 108 of `code_grooming_loop.py` is itself evidence of that fragility.
- The loop was already **gated off by default** (`code_grooming_enabled` defaulted to `False` per `src/config.py`). On 2026-04-18 the user approved bulk-closing 788 auto-filed `Code Quality:` issues that the loop had produced before the default flipped to `False` (see `docs/wiki/memory-feedback/feedback-dont-close-unfixed-issues.md`).
- Findings that genuinely matter belong on the `hydraflow-find` queue via the same path as everything else — driven by humans or by the targeted code-quality audit skills already invoked manually.
- The `/hf.audit-code` skill is discoverable to agents and humans via `src/skill_registry.py` (it auto-globs `.claude/commands/hf.*.md`). Removing the loop does not remove the skill's manual-invocation path.

## Decision

1. Delete `src/code_grooming_loop.py` and its dedicated tests (`tests/test_code_grooming_loop.py`, `tests/test_code_grooming_parse_warning.py`, `tests/test_audit_code_skill.py`, `tests/regressions/test_issue_6571.py`, `tests/regressions/test_issue_6830.py`).
2. Strip every other reference in `src/` and `tests/`: `service_registry`, `cost_budget_watcher_loop`, `orchestrator`, `models`, `config`, `state/_code_grooming.py`, `dashboard_routes/_common.py` and `_control_routes.py`, UI `constants.js` + `CaretakerPanel.jsx`, scenario catalog, and test helpers/fixtures.
3. **Keep** `.claude/commands/hf.audit-code.md` and `.codex/skills/hf.audit-code/SKILL.md`. Both remain advertised to agents and humans through the existing skill registry (`src/skill_registry.py` globs `.claude/commands/hf.*.md`), so the audit remains a one-command human-invocable workflow. Only the unattended scheduling layer is being removed.
4. Drop the `CodeGroomingSettings` model and the `code_grooming_filed`/`code_grooming_settings` `StateData` fields. No backward-compat shim — Pydantic's `extra="ignore"` on `StateData` swallows stale fields on existing on-disk state files without surfacing an error.
5. **Do not auto-delete user data files.** The legacy dedup file at `<data_root>/memory/code_grooming_dedup.json` will simply stop being written and read; operators may remove it manually if they care to.
6. Regenerate `docs/arch/generated/*` (loops.md, coverage_matrix.md, functional_areas.md). `CodeGroomingLoop` drops out automatically.

## Consequences

- One fewer caretaker loop to maintain; the regex-coupled parser stops being a fragility surface.
- Critical-severity findings that *would* have been auto-filed must now be surfaced by humans running `/hf.audit-code` or by other caretakers (`SecurityPatchLoop`, `CIMonitorLoop`, `FlakeTrackerLoop`, etc.).
- The "Background loops: five-step audit pattern" wiki entry now references a removed loop as its canonical example. The entry still describes a valid shape for future audit-style workers — the prose has been updated to acknowledge the loop's removal while preserving the pattern.
- `CARETAKER_KEYS` in `src/ui/src/components/CaretakerPanel.jsx` shrinks from 8 to 7. Dashboard layout reflows automatically.
- The `HYDRAFLOW_CODE_GROOMING_*` env vars and the `code_grooming_*` config fields are gone with no shim. Operators who had them set in `.env` files will need to remove the lines; Pydantic does not error on extra env vars.

## Alternatives considered

- **Keep the loop, tighten the filter.** Already done — the loop self-limited to `critical`. Did not solve the value problem; the loop kept being run with `enabled=False`.
- **Replace the regex parser with a structured tool-use output.** Would address the fragility but not the value question. The maintenance cost is what we want to eliminate; better mechanics on a low-value job is gold-plating.
- **Delete the `/hf.audit-code` skill too.** Rejected. The skill is invokable by humans and surfaces as an available agent tool — that's the right home for audit-on-demand. Only the unattended scheduling was the problem.
