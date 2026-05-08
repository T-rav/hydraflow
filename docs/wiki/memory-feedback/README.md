# Memory feedback — in-repo backlog

This directory is the in-repo redacted mirror of `feedback_*.md` files
from Claude's session-memory directory
(`~/.claude/projects/<repo-encoded>/memory/`). Each file here is a
candidate for promotion into a structurally-enforced rule (test,
fixture, lint, loop) per `docs/wiki/dark-factory.md` §6.

`MemoryBacklogLoop` (`src/memory_backlog_loop.py`, ADR-0057) walks this
directory on its tick and files `hydraflow-find` issues for any entry
with `status: pending`.

## Frontmatter schema

Every file has YAML frontmatter:

```yaml
---
source: feedback_subagent_batch_size.md      # filename in the source memory dir
name: <human-readable rule name>             # short title
description: <1-line summary>
status: pending                              # pending | issue-open | promoted | wontfix
issue: null                                  # GH issue number (null until filed)
promoted_in: null                            # PR number / commit SHA when status -> promoted
wontfix_reason: null                         # required when status -> wontfix
created: 2026-04-21                          # ISO date pulled from source memory mtime
---
```

## Body redaction rules

Body is the source memory's body with these redactions applied at write-time:

- `originSessionId` field stripped from frontmatter (never mirrored).
- Absolute paths under `$HOME` (e.g. `/Users/travisf/...`) replaced with `~`.
- Contributor email addresses stripped (allowlist: `@anthropic.com`,
  `@hydraflow.local`, `@example.com`).
- Internal session URLs / API tokens / private keys stripped.
- All other prose (rule, **Why**, **How to apply**, examples) preserved verbatim.

## Status state machine

```
pending ──────loop tick──────> issue-open
   │                              │
   │ (human marks)                │ (issue closed without resolution)
   ▼                              ▼
wontfix                       (re-files next tick after cooldown)
   ▲                              │
   │ (issue closed + PR linked)   │
   └──────────promoted ◄──────────┘
```

- `pending`: not yet filed. The loop will pick this up.
- `issue-open`: the loop filed an issue (`issue: <N>`). The loop won't re-file.
- `promoted`: enforcement landed. `promoted_in` carries the PR / commit SHA.
- `wontfix`: human declined to enforce. `wontfix_reason` is required.

## Adding a new entry

When Claude saves a new `feedback_*.md` to its session memory, it ALSO
commits a redacted mirror here in the next commit. The redaction is
manual (Claude's responsibility); a future iteration may automate it
via a slash command or hook.

See ADR-0057 for the design rationale.
