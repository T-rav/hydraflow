# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**HydraFlow** — Intent in. Software out. A multi-agent orchestration system that automates the full GitHub issue lifecycle via git issues and labels.

## Architecture

HydraFlow runs five concurrent async loops from `orchestrator.py`:

1. **Triage loop**: Fetches new issues, scores complexity, classifies type, and applies the `hydraflow-plan` label.
2. **Plan loop**: Fetches issues labeled `hydraflow-plan`, runs a read-only Claude agent to explore the codebase and produce an implementation plan, posts the plan as a comment, then swaps the label to `hydraflow-ready`.
3. **Implement loop**: Fetches issues labeled `hydraflow-ready`, creates git worktrees, runs implementation agents with TDD prompts, pushes branches, creates PRs, then swaps to `hydraflow-review`.
4. **Review loop**: Fetches issues labeled `hydraflow-review`, runs a review agent to check quality and optionally fix issues, submits a formal PR review, waits for CI, and auto-merges approved PRs. CI failures escalate to `hydraflow-hitl` for human intervention.
5. **HITL loop**: Processes issues labeled `hydraflow-hitl` that need human-in-the-loop correction.

### Key Files

**Core infrastructure:**
- `cli.py` — CLI entry point (run, dry-run, clean, prep, scaffold)
- `orchestrator.py` — Main coordinator (five async polling loops)
- `config.py` — `HydraFlowConfig` Pydantic model (50+ env-var overrides)
- `models.py` — Pydantic data models (Phase, SessionLog, ReviewResult, etc.)
- `service_registry.py` — Dependency injection factory (`build_services()`)
- `state.py` — `StateTracker` (JSON-backed crash recovery)
- `events.py` — `EventBus` async pub/sub

**Phase implementations:**
- `plan_phase.py` / `implement_phase.py` / `review_phase.py` / `triage_phase.py` / `hitl_phase.py`
- `phase_utils.py` — Shared phase utilities

**Agents/runners:**
- `agent.py` — `AgentRunner` (implementation agent)
- `planner.py` — `PlannerRunner` (read-only planning agent)
- `reviewer.py` — `ReviewRunner` (review + CI fix agent)
- `hitl_runner.py` — HITL correction agent
- `base_runner.py` — Base runner class

**Git & PR management:**
- `worktree.py` — `WorktreeManager` (git worktree lifecycle)
- `pr_manager.py` — `PRManager` (all `gh` CLI operations)
- `merge_conflict_resolver.py` — Merge conflict resolution
- `pr_unsticker.py` / `pr_unsticker_loop.py` — Stale PR recovery
- `post_merge_handler.py` — Post-merge cleanup

**Background loops:**
- `base_background_loop.py` — Base async loop pattern
- `manifest_refresh_loop.py` / `memory_sync_loop.py` / `metrics_sync_loop.py` / `pr_unsticker_loop.py`

**Dashboard:**
- `dashboard.py` + `dashboard_routes.py` — FastAPI + WebSocket backend
- `ui/` — React + Vite frontend

**Repo scaffolding (prep system):**
- `prep.py` — Repository preparation orchestrator
- `ci_scaffold.py` / `lint_scaffold.py` / `test_scaffold.py` / `makefile_scaffold.py`
- `polyglot_prep.py` — Language detection

## Worktree Management

HydraFlow creates isolated git worktrees for each issue. **Always clean up worktrees when their PRs are merged or issues are closed. Always implement issue work on a dedicated git worktree branch; do not implement directly in the primary repo checkout.**

- **Default location:** `../hydraflow-worktrees/` (sibling to repo root)
- **Naming:** `issue-{issue_number}/`
- **Config:** `worktree_base` field in `HydraFlowConfig`
- **Cleanup:** `make clean` removes all worktrees and state
- Worktrees get independent venvs (`uv sync`), symlinked `.env`, and pre-commit hooks
- Stale worktrees from merged PRs should be periodically pruned with `git worktree prune`

## Testing is Mandatory

**ALWAYS write unit tests for code changes before committing.** Every new function, class, or feature modification MUST include comprehensive tests.

- Tests live in `tests/` following the pattern `tests/test_<module>.py`
- New features: Write tests BEFORE committing
- Bug fixes: Add regression tests that reproduce the bug
- Refactoring: Ensure existing tests pass, add tests for new paths
- Never commit untested code
- Coverage threshold: 70%

## Never Skip Commit Hooks

**NEVER** use `git commit --no-verify` or `--no-hooks` flags. Always fix code issues first.

## Development Commands

```bash
make run            # Start backend + Vite frontend dev server
make dry-run        # Dry run (log actions without executing)
make clean          # Remove all worktrees and state
make status         # Show current HydraFlow state
make test           # Run unit tests (parallel)
make test-fast      # Quick test run (-x --tb=short)
make test-cov       # Run tests with coverage report (70% threshold)
make lint           # Auto-fix linting
make lint-check     # Check linting (no fix)
make typecheck      # Run Pyright type checks
make security       # Run Bandit security scan
make quality        # Lint + typecheck + security + test (parallel)
make quality-lite   # Lint + typecheck + security (no tests)
make setup          # Install hooks, CLI, config, labels
make prep           # Scan + scaffold CI/tests for target repo
make ensure-labels  # Create HydraFlow lifecycle labels
make hot            # Send config update to running instance
make ui             # Build React dashboard
make ui-dev         # Start React dashboard dev server
make deps           # Sync dependencies via uv
```

### Quick Validation

```bash
# After small changes
make lint && make test

# Before committing
make quality
```

## Tech Stack

- **Python 3.11** with Pydantic, asyncio
- **FastAPI + WebSocket** for dashboard
- **React + Vite** for dashboard UI
- **Ruff** for linting/formatting
- **Pyright** for type checking
- **Bandit** for security scanning
- **pytest + pytest-asyncio + pytest-xdist** for testing
- **uv** for dependency management

## UI Development Standards

The React dashboard (`ui/`) uses inline styles in JSX. Follow these conventions.

### Layout
- **CSS Grid** for page-level layout (`App.jsx`), **Flexbox** for component internals
- Sidebar is fixed at `280px`; set `flexShrink: 0` on fixed-width panels/connectors
- Set `minWidth` on containers to prevent content overlap at narrow viewports

### DRY Principle
- Shared constants (`ACTIVE_STATUSES`, `PIPELINE_STAGES`) live in `ui/src/constants.js` — never duplicate
- Type definitions in `ui/src/types.js`
- Colors are CSS custom properties in `ui/index.html` `:root`, accessed via `ui/src/theme.js` — always use `theme.*` tokens, never raw hex/rgb values
- Extract shared styles to reusable objects when used 3+ times

### Style Consistency
- Define `const styles = {}` at file bottom; pre-compute variants (active/inactive, lit/dim) outside the component to avoid object spread in render loops (see `Header.jsx` `pillStyles`)
- Spacing scale: multiples of 4px (4, 8, 12, 16, 20, 24, 32)
- Font size scale: 9, 10, 11, 12, 13, 14, 16, 18
- New colors must be added to both `ui/index.html` `:root` and `ui/src/theme.js`

### Component Patterns
- Check for existing components before creating new ones (pill badges in `Header.jsx`, status badges in `StreamCard.jsx`, tables in `ReviewTable.jsx`)
- Prefer extending existing components over parallel implementations
- Interactive elements need hover/focus states (`cursor: 'pointer'`, `transition`)
- Derive stage-related UI from `PIPELINE_STAGES` in `constants.js`
