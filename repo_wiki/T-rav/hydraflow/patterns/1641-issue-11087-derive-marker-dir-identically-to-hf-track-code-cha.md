---
id: 1641
topic: patterns
source_issue: 11087
source_phase: plan
created_at: 2026-08-14T06:12:02.565814+00:00
status: active
corroborations: 1
---

# Derive marker dir identically to hf.track-code-changes.sh

Hook scripts that arm or disarm markers must derive the marker dir the same way `hf.track-code-changes.sh` does: `md5sum` of `CLAUDE_PROJECT_DIR` with `md5` fallback on macOS. The path is `/tmp/claude-code-markers/<md5>`. **Why:** A divergent hash or path makes the arm hook write to one file and the disarm/Stop hooks read another, so markers are never cleared and every session gets Stop-blocked.
