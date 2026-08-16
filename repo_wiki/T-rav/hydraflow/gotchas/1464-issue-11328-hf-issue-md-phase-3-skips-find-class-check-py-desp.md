---
id: 1464
topic: gotchas
source_issue: 11328
source_phase: review
created_at: 2026-08-16T12:27:43.693271+00:00
status: active
corroborations: 1
---

# Verify a slash-command doc's steps actually match what CLAUDE.md claims is wired in

When a slash-command doc claims a script is wired in, verify the actual command steps rather than trusting the CLAUDE.md summary. Mid-review, `.claude/commands/hf.issue.md` Phase 3 ran a bare `gh issue list --search` and never called `scripts/find_class_check.py`, despite `CLAUDE.md` already asserting it did.

- Fixed in this PR: Phase 3 now runs `scripts/find_class_check.py --check` (with a `--site`-per-discovered-site follow-up) before falling back to plain keyword search, per the plan.

**Why:** Stale CLAUDE.md claims cause future agents to assume class-folding is active when it is library-only, producing silent no-ops.
