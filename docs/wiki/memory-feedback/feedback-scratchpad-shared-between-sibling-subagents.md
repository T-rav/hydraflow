---
source: feedback_scratchpad_shared_between_sibling_subagents.md
name: Scratchpad dir is shared between sibling subagents — prefix filenames
description: Parallel implementer subagents spawned by one orchestrator all get the
  ORCHESTRATOR's scratchpad path; generic filenames (pr_body.md, quality.log) get
  silently overwritten by siblings — one PR shipped with another task's body
status: promoted
issue: 11949
promoted_in: 12015
wontfix_reason: null
created: '2026-08-21'
---

**What happened (2026-08-21, PR #11572):** I wrote my PR body to `<scratchpad>/pr_body.md`,
ran `sed` + `grep -c PLACEHOLDER` (0 — my content), pushed, then `gh pr create --body-file`.
In the ~10 s between, a sibling implementer session (codeql108 worktree) wrote ITS
`pr_body.md` to the same path. PR #11572 opened with the CodeQL PR's body under my title.
Caught only because the harness "file changed on disk" note showed foreign content.

**Why:** the system-prompt scratchpad path embeds the *orchestrator's* session id
(`bf5a2211…`), while my own task artifacts live under a different id (`eb8015bd…/tasks/`).
Every subagent the orchestrator spawns in parallel is handed the same scratchpad dir.
`ps` showed 3 sibling `make quality` runs from other `.claude/worktrees/*-20260821` trees.

**Rules:**
- Prefix every scratchpad file with a task-unique token (`gc-landed-11572-pr-body.md`,
  `gc-landed-quality.log`), never `pr_body.md` / `quality.log` / `notes.md`.
- Re-read (or `head`) a body file in the SAME command as `gh pr create/edit --body-file`,
  and verify `gh pr view --json body` immediately after creating.
- Background logs: a sibling `>` truncation garbles a shared log even while your fd is
  open — unique names for logs too; use a unique terminal marker (`GCLANDED_EXIT=`) not `EXIT=`.
- The scratchpad `ls` listing tells you instantly whether siblings are present (foreign
  files with recent mtimes).

**Also:** the destructive-git pre-tool hook pattern-matches the LITERAL string
"git branch -D" anywhere in the Bash command — including inside heredoc issue bodies and
`--needle` arguments. Phrase as "force-delete the local branch" in any text you pass via Bash.
