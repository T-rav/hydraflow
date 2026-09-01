---
id: 4090
topic: patterns
source_issue: 11947
source_phase: plan
created_at: 2026-09-01T10:45:05.630169+00:00
status: active
corroborations: 1
---

# Use both hook and CI for content-gating rules

Use both a PreToolUse `Write` hook and a CI step for any rule that gates file content. A hook prevents `Write` tool calls but is blind to `cat > f <<EOF`, `sed -i`, and other shell-level rewrites agents use under bypass-permissions. CI is the durable backstop.

- Hook: `.claude/hooks/hf.block-symbol-dropping-write.sh` exits 2 on PreToolUse `Write`.
- CI: `.github/workflows/ci.yml` runs `scripts/check_symbol_drop.py --base/--head`.
- Both call the same engine.

**Why:** Agents bypass the `Write` tool under bypass-permissions; without CI, a shell-redirect rewrite silently skips the gate.
