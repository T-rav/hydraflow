# AGENTS.md

Canonical reference for every agent role in HydraFlow. Each section documents:
- **Role** — what the agent does and its constraints
- **Prompt structure** — required sections and ordering
- **Output contract** — exact markers the system parses
- **Key rules** — non-negotiable constraints

Source of truth for prompt intent. Prompt text lives in the runner files; this
document explains *why* each prompt is structured the way it is.

---

## Agent Runtimes

HydraFlow is **runtime-agnostic**. The same prompt contracts work with any
agent CLI that can read a prompt from stdin / a flag and write text to stdout.
The output markers (`PLAN_START`, `VERDICT:`, `SUMMARY:`, etc.) are plain text
and impose no tool-specific requirements.

### Supported runtimes

| Runtime | CLI invocation | Config key |
|---------|---------------|------------|
| **Claude Code** | `claude -p "<prompt>"` | `planner_tool = "claude"` |
| **OpenAI Codex** | `codex "<prompt>"` | `planner_tool = "codex"` |
| **Pi.dev** | `pi "<prompt>"` | `planner_tool = "pi"` |

Each stage (plan, implement, review, HITL) can use a different runtime:

```env
HYDRAFLOW_PLANNER_TOOL=claude
HYDRAFLOW_IMPLEMENT_TOOL=codex
HYDRAFLOW_REVIEW_TOOL=claude
HYDRAFLOW_HITL_TOOL=pi
```

### What the runtime must support

For any runtime to work with HydraFlow:

1. **Stdin / flag prompt ingestion** — the prompt is passed as a positional
   argument or `--prompt` flag.
2. **Filesystem access** — the agent must be able to read files in the
   working directory (read-only for the planner, read-write for others).
3. **Shell tool access** — `make lint`, `make quality`, `git` commands must
   be executable from within the agent session (for implementer and reviewer).
4. **Plain-text stdout** — output markers are parsed from raw stdout/stderr;
   no structured JSON response format is required.

### Output marker stability

The following markers are parsed by HydraFlow's Python code and **must not be
renamed without a coordinated update to the corresponding runner**:

| Marker | Agent | Parser location |
|--------|-------|----------------|
| `PLAN_START` / `PLAN_END` | Planner | `planner.py:_extract_plan` |
| `SUMMARY: <text>` | Planner, Reviewer, CI-fix | `*._extract_summary` |
| `ALREADY_SATISFIED_START` / `…_END` | Planner | `planner.py:_extract_already_satisfied` |
| `NEW_ISSUES_START` / `NEW_ISSUES_END` | Planner | `planner.py:_extract_new_issues` |
| `VERDICT: APPROVE\|REQUEST_CHANGES\|COMMENT` | Reviewer | `reviewer.py:_parse_verdict` |
| `PRE_QUALITY_REVIEW_RESULT: OK\|RETRY` | Implementer sub-skill | `agent.py:_parse_skill_result` |
| `RUN_TOOL_RESULT: OK\|RETRY` | Implementer sub-skill | `agent.py:_parse_skill_result` |
| `MEMORY_SUGGESTION_START` / `…_END` | All | `memory_sync_loop.py` |
| `PRECHECK_RISK:` / `PRECHECK_CONFIDENCE:` / `PRECHECK_ESCALATE:` | Reviewer precheck | `reviewer.py:_run_precheck_context` |

These markers are **tool-agnostic** — any runtime that includes them verbatim
in its output will work correctly.

---

## Planner Agent (`src/planner.py` → `PlannerRunner`)

### Role

Read-only exploration agent. Explores the codebase and produces a concrete
implementation plan for a GitHub issue. Never writes, edits, or deletes files.

### Scales

| Scale | When used | Required sections |
|-------|-----------|-------------------|
| `lite` | Small issues: bug fix, typo, docs. Detected by label (`lite_plan_labels`) or short body + small-fix title keywords. | Files to Modify, Implementation Steps, Testing Strategy |
| `full` | Features, multi-file changes (default). | All seven sections below. |

### Prompt structure

1. **Role declaration** — `You are a planning agent for GitHub issue #N.`
2. **Issue context** — title, body (truncated to `max_issue_body_chars`), discussion (up to 6 comments, each capped at 1 000 chars), image note if attachments present.
3. **Manifest + memory injection** — repo manifest and agent memory for codebase context.
4. **Mode note** — LITE or FULL plan mode banner.
5. **READ-ONLY constraint** — explicit prohibition on file writes, git commits, installs.
6. **Exploration strategy** — use `claude-context search_code` and `cclsp` tools before grep; special UI exploration checklist when issue involves frontend.
7. **Planning steps** — numbered 1–5: restate → explore → file deltas → testing → UI reuse.
8. **Required output** — `PLAN_START` / `PLAN_END` markers, then `SUMMARY:` line.
9. **Schema** — required section headers (scale-adaptive).
10. **Pre-mortem** (full only) — assume failure, list top 3 risks in Key Considerations.
11. **Uncertainty handling** — `[NEEDS CLARIFICATION: ...]` markers; ≥4 escalates to HITL.
12. **Optional discovered issues** — `NEW_ISSUES_START` / `NEW_ISSUES_END` block.
13. **Already-satisfied path** — `ALREADY_SATISFIED_START` / `ALREADY_SATISFIED_END`; auto-closes the issue.
14. **Memory suggestion** — `MEMORY_SUGGESTION_START` / `MEMORY_SUGGESTION_END` (one per run).

### Required plan sections (full)

```
## Files to Modify        — at least one file path
## New Files              — or "None"
## File Delta             — MODIFIED/ADDED/REMOVED: path lines
## Implementation Steps   — at least 3 numbered steps
## Testing Strategy       — at least one test file/pattern; never deferred
## Acceptance Criteria    — extracted or synthesized
## Key Considerations     — edge cases, compatibility, dependencies
```

### Output contract

| Marker | Parsed by |
|--------|-----------|
| `PLAN_START` … `PLAN_END` | `_extract_plan()` |
| `SUMMARY: <text>` | `_extract_summary()` |
| `ALREADY_SATISFIED_START` … `ALREADY_SATISFIED_END` | `_extract_already_satisfied()` |
| `NEW_ISSUES_START` … `NEW_ISSUES_END` | `_extract_new_issues()` |
| `MEMORY_SUGGESTION_START` … `MEMORY_SUGGESTION_END` | `memory_sync_loop` |

### Validation gates

Plans are rejected (and retried once) if any gate fails:

- Missing required section header
- `## Files to Modify` has no file path pattern
- `## Testing Strategy` has no test file/pattern reference
- `## Implementation Steps` has fewer than 3 numbered steps
- Word count below `min_plan_words` (full plans only)
- ≥4 `[NEEDS CLARIFICATION]` markers
- `## Testing Strategy` is empty or deferred (testing gate)
- `constitution.md` principles violated (constitution gate)

### Retry behaviour

On first validation failure the planner is re-prompted with the failed plan and
explicit error list. If the retry also fails, `retry_attempted=True` is set on
the result and the issue escalates to HITL.

---

## Implementation Agent (`src/agent.py` → `AgentRunner`)

### Role

Full read-write agent. Implements an issue inside an isolated git worktree.
Commits changes but never pushes or creates PRs.

### Prompt structure

1. **Role declaration** — `You are implementing GitHub issue #N.`
2. **Issue context** — title, body (truncated).
3. **Implementation Plan** — extracted from the planner's issue comment (`## Implementation Plan` header) or `.hydraflow/plans/issue-N.md` fallback; summarized to `_MAX_IMPL_PLAN_CHARS` (6 000).
4. **Review Feedback** (if re-implementing after rejection) — previous reviewer feedback, summarized to `_MAX_REVIEW_FEEDBACK_CHARS` (2 000).
5. **Discussion** — up to 6 non-plan comments, each capped at `_MAX_DISCUSSION_COMMENT_CHARS` (500).
6. **Common review feedback** — aggregated patterns from recent review history (via `ReviewInsightStore`), summarized to `_MAX_COMMON_FEEDBACK_CHARS` (2 000).
7. **Manifest + memory injection**.
8. **Runtime logs** (opt-in via `inject_runtime_logs`).
9. **Instructions** — 7 numbered steps: understand → implement → write tests → diff sanity → pre-quality review → run quality gate → commit.
10. **UI guidelines** — component reuse, centralized constants/theme, responsive design, spacing.
11. **Rules** — mandatory tests, no push/PR, quality gate must pass before commit.
12. **Memory suggestion**.

### Sub-skills invoked inline

After the main implementation run, the agent executes two sub-skill loops
(up to `max_pre_quality_review_attempts`):

**Pre-Quality Review Skill** — correctness and plan adherence review, edge case
test addition, direct fixes. Output: `PRE_QUALITY_REVIEW_RESULT: OK|RETRY`.

**Run-Tool Skill** — runs `make lint` → `{test_cmd}` → `make quality` in order,
fixing failures before rerunning. Output: `RUN_TOOL_RESULT: OK|RETRY`.

### Quality fix loop

If `make quality` fails after pre-quality review, up to `max_quality_fix_attempts`
additional passes are made with a targeted quality-fix prompt (focused on the
exact failure output). Each pass re-runs `_verify_result()`.

### Commit convention

```
Fixes #<issue>: <concise summary>
quality-fix: <description> (#<issue>)
```

### Rules enforced by prompt

- Write tests for all new code — tests are mandatory.
- Never push to remote.
- Never create PRs (`git push`, `gh pr create` are explicitly prohibited).
- `make quality` must pass before committing.

---

## Reviewer Agent (`src/reviewer.py` → `ReviewRunner`)

### Role

Code review and CI-fix agent. Reads the PR diff, evaluates correctness /
completeness / quality, optionally applies fixes, and returns a verdict.

### Review prompt structure

1. **Role declaration** — `You are reviewing PR #N which implements issue #M.`
2. **Issue context** — title, summarized body (up to 8 bullet cue lines).
3. **Manifest + memory injection**.
4. **Runtime logs** (opt-in).
5. **Precheck context** — output from the precheck sub-agent (risk, confidence, escalation recommendation).
6. **PR diff** — summarized: file list with +/- counts, diff excerpts (up to `excerpt_limit` chars); truncated at `max_review_diff_chars`.
7. **Review instructions** — evaluate 3 dimensions; must find ≥`min_review_findings` issues or emit `THOROUGH_REVIEW_COMPLETE` block.
8. **Verification step** — either "do NOT run tests (CI handles it)" or "run `make lint` + test cmd", depending on `max_ci_fix_attempts`.
9. **Project audits** — SRP, type hints, naming, complexity, test 3As structure, security (injection, crypto, auth).
   Includes the HydraFlow test-value standard: no skipped/xfail/commented-out or placeholder tests in active coverage, unit tests use documented factories/world-building helpers, integration tests keep real business logic wired and mock only external boundaries, and MockWorld scenarios assert fake-adapter state instead of raw mock call counts.
10. **UI-specific checks** (when `"ui/" in diff`) — DRY, responsive, style consistency, component reuse.
11. **Fix instructions** — make direct fixes and commit if issues are found.
12. **Findings format** — `[SEVERITY] file[:line] - issue - expected fix`.
13. **Required output** — verdict line + `SUMMARY:`.
14. **Memory suggestion**.

### Precheck sub-agent

Before the main review, a lightweight precheck agent runs on a diff snippet
(≤3 000 chars, further capped by `max_review_diff_chars`) to provide a fast
triage signal that shapes the main review prompt.

#### Prompt structure

```
Run a compact review precheck for PR #N (issue #M).

Goal:
- estimate risk and confidence
- list top findings (max 5)
- recommend whether debug escalation is needed

Return EXACTLY:
PRECHECK_RISK: low|medium|high
PRECHECK_CONFIDENCE: <0.0-1.0>
PRECHECK_ESCALATE: yes|no
PRECHECK_SUMMARY: <one line>

Issue title: <title>
Diff snippet: <≤3 000 chars>
```

#### Output contract

The precheck agent **must** emit all four markers on their own lines, in order:

| Marker | Values | Description |
|--------|--------|-------------|
| `PRECHECK_RISK:` | `low` \| `medium` \| `high` | Overall change risk |
| `PRECHECK_CONFIDENCE:` | `0.0`–`1.0` | Confidence in the risk estimate |
| `PRECHECK_ESCALATE:` | `yes` \| `no` | Whether debug-mode escalation is recommended |
| `PRECHECK_SUMMARY:` | one-line free text | Human-readable summary of top concern |

Parsed by `reviewer.py:_run_precheck_context` via `precheck.run_precheck_context`.

#### Integration

The four-line precheck result is injected verbatim into the **main review
prompt** under the "Precheck context" heading (step 5 of the review prompt
structure). If the precheck call fails or returns no output, the fallback text
`"No low-tier precheck context provided."` is used — the main review still runs.

### CI-fix prompt structure

Used by `fix_ci()` when CI fails after a review:

1. Role declaration with PR + issue numbers.
2. CI failure summary.
3. Full CI failure logs (truncated to `_MAX_CI_LOG_PROMPT_CHARS` = 6 000).
4. Fix instructions — fix root causes, run `make lint` + test cmd locally.
5. Required output — `VERDICT: APPROVE|REQUEST_CHANGES` + `SUMMARY:`.

### Output contract

| Marker | Values | Parsed by |
|--------|--------|-----------|
| `VERDICT: <value>` | `APPROVE`, `REQUEST_CHANGES`, `COMMENT` | `_parse_verdict()` |
| `SUMMARY: <text>` | free text, ≥10 chars, sanitized | `_extract_summary()` |
| `THOROUGH_REVIEW_COMPLETE` | block with 3 dimension justifications | review phase logic |
| `MEMORY_SUGGESTION_START` … `END` | — | `memory_sync_loop` |

### Commit convention

```
review: fix <description> (PR #<pr>)
ci-fix: <description> (PR #<pr>)
```

---

## HITL Agent (`src/hitl_runner.py` → `HITLRunner`)

### Role

Human-in-the-loop correction agent. Applies human guidance to resolve issues
that the automated pipeline could not handle: CI failures, merge conflicts,
insufficient issue detail, or general escalations.

### Cause classification

The escalation `cause` string is classified into a prompt template:

| Cause key | Trigger keywords | Instructions focus |
|-----------|------------------|--------------------|
| `ci` | "ci", "check", "test fail" | `make quality` → fix root causes → rerun |
| `merge_conflict` | "merge" + "conflict" | `git status` → resolve → quality check |
| `needs_info` | "insufficient", "needs", "detail" | Read guidance → implement → test → quality |
| `default` | (anything else) | Read guidance → fix → quality |

Note: `needs_info` is checked before `ci` because "insufficient" contains "ci".

### Prompt structure

1. **Role declaration** — `You are applying a human-in-the-loop correction for GitHub issue #N.`
2. **Issue context** — title, body (truncated to `max_issue_body_chars`).
3. **Manifest + memory injection**.
4. **Escalation reason** — truncated to 2 000 chars.
5. **Human guidance** — truncated to 4 000 chars.
6. **Instructions** — cause-specific numbered steps (from `_CAUSE_INSTRUCTIONS`).
7. **Rules** — tests mandatory, no push/PR, quality gate must pass.
8. **Memory suggestion**.

### Commit convention

```
hitl-fix: <description> (#<issue>)
hitl-fix: resolve merge conflicts (#<issue>)
```

### Output contract

No structured markers are parsed from the HITL transcript. Success is determined
solely by `_verify_quality()` (exits 0 = pass).

---

## Shared: Memory Suggestion Protocol

All agents may emit at most one memory suggestion per run:

```
MEMORY_SUGGESTION_START
title: Short descriptive title
type: knowledge | config | instruction | code
learning: What was learned and why it matters
context: How it was discovered (reference issue/PR numbers)
MEMORY_SUGGESTION_END
```

| Type | Routing |
|------|---------|
| `knowledge` | Auto-applied (passive insight) |
| `config` | Routed for human approval |
| `instruction` | Routed for human approval |
| `code` | Routed for human approval |

Consumed by `memory_sync_loop.py`. Only suggest genuinely valuable learnings —
not trivial observations.

---

## Shared: Manifest + Memory Injection

All agents call `BaseRunner._inject_manifest_and_memory()` which appends:

- **Repo manifest** — structured summary of the target repo's architecture, test
  strategy, and key files (loaded from `.hydraflow/manifest.md`).
- **Agent memory** — curated learnings from past runs
  (loaded from `.hydraflow/memory/*.md`).

These sections give every agent codebase awareness without requiring fresh
exploration on every run.

---

## Prompt Evolution Guidelines

When modifying a prompt:

1. **Update this file** to reflect the intent change before touching runner code.
2. **Keep output markers stable** — downstream parsers depend on exact strings
   (`PLAN_START`, `VERDICT:`, `SUMMARY:`, etc.). Rename only with a coordinated
   parser update.
3. **Test prompt changes** with `make test` — runner prompt-builder methods have
   unit tests in `tests/test_planner.py`, `tests/test_agent.py`, etc.
4. **One concern per section** — each prompt section should have a single,
   clear purpose. Avoid combining instructions that could conflict.
5. **Scale-aware** — planner prompts have `lite`/`full` variants; keep both in
   sync when adding new required sections.
6. **Runtime-neutral language** — avoid Claude-specific tool names in prompt
   instructions (e.g. say "use semantic search" not "use `claude-context`").
   Tool-specific exploration steps belong in the runtime configuration, not
   the shared prompt contract documented here.
7. **Test across runtimes** — when adding a new output marker, verify that
   the parser in the corresponding runner handles both Claude and Codex
   transcript formats (whitespace differences, trailing newlines, etc.).

<!-- BEGIN BEADS INTEGRATION v:1 profile:full hash:d4f96305 -->
## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?

- Dependency-aware: Track blockers and relationships between issues
- Git-friendly: Dolt-powered version control with native sync
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
bd ready --json
```

**Create new issues:**

```bash
bd create "Issue title" --description="Detailed context" -t bug|feature|task -p 0-4 --json
bd create "Issue title" --description="What this issue is about" -p 1 --deps discovered-from:bd-123 --json
```

**Claim and update:**

```bash
bd update <id> --claim --json
bd update bd-42 --priority 1 --json
```

**Complete work:**

```bash
bd close bd-42 --reason "Completed" --json
```

### Issue Types

- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance (dependencies, tooling)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `bd ready` shows unblocked issues
2. **Claim your task atomically**: `bd update <id> --claim`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `bd create "Found bug" --description="Details about what was found" -p 1 --deps discovered-from:<parent-id>`
5. **Complete**: `bd close <id> --reason "Done"`

### Auto-Sync

bd automatically syncs via Dolt:

- Each write auto-commits to Dolt history
- Use `bd dolt push`/`bd dolt pull` for remote sync
- No manual export/import needed!

### Important Rules

- ✅ Use bd for ALL task tracking
- ✅ Always use `--json` flag for programmatic use
- ✅ Link discovered work with `discovered-from` dependencies
- ✅ Check `bd ready` before asking "what should I work on?"
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT use external issue trackers
- ❌ Do NOT duplicate tracking systems

For more details, see README.md and docs/QUICKSTART.md.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

<!-- END BEADS INTEGRATION -->
