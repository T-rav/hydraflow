# ADR-0028: CLI Architecture — argparse with Config Builder Pattern

**Status:** Proposed
**Date:** 2026-03-08

## Context

HydraFlow needs a CLI that supports 50+ configuration options with values sourced
from multiple layers: config files, environment variables, and command-line
arguments. The two main Python CLI framework choices are:

1. **Click** — Decorator-based, widely used, adds an external dependency.
2. **argparse** — Standard library, no external dependency, imperative style.

Beyond framework choice, the CLI must merge configuration from three sources with
clear precedence rules. Two patterns are common:

- **Flat parsing:** Each source is handled independently; merging happens ad-hoc
  at the call site.
- **Builder pattern:** A dedicated function (`build_config()`) owns the merge
  logic, producing a single validated config object.

The `hf` console script (`hf_cli/__main__.py`) acts as a two-layer dispatcher:
workspace management commands (run, stop, view, init) are handled directly, while
orchestrator commands and flags are delegated to `cli.main()`. The dashboard
exposes `/api/control/*` endpoints for start/stop/config but does not yet cover
all CLI operations (clean, prep, scaffold, labels, audit).

## Decision

Use **argparse** (Python standard library) as the CLI framework, paired with a
**config builder pattern** implemented in `build_config()` (`src/cli.py`).

### Framework: argparse over Click

- argparse is a stdlib module — no additional dependency to install, pin, or
  audit. The project has zero Click usage in source or `pyproject.toml`.
- HydraFlow's CLI is an operational tool, not a user-facing product with rich
  help formatting needs. argparse's built-in help is sufficient.
- The CLI surface is flag-heavy (50+ flags) rather than subcommand-heavy. Click's
  decorator model adds boilerplate for flag-dominated interfaces without
  meaningful readability gains.

### Config merge: builder pattern

`build_config(args: argparse.Namespace) -> HydraFlowConfig` merges config with
explicit precedence (lowest to highest):

1. **Defaults** — Pydantic model field defaults in `HydraFlowConfig`.
2. **Config file** — YAML/JSON loaded via `load_config_file()`, filtered against
   `HydraFlowConfig.model_fields.keys()` to reject unknown keys.
3. **Environment variables** — Resolved by Pydantic's `model_validate()`.
4. **CLI arguments** — Highest priority; only explicitly-provided args override.
5. **Repo-scoped overlay** — Applied post-validation for fields not set by CLI.

#### The `cli_explicit` population mechanism

When `load_runtime_config()` receives an `overrides` dict (from CLI arguments or
programmatic callers such as `src/server.py`), it iterates the dict and adds each
key that matches a known `HydraFlowConfig` field to a local `explicit_fields: set[str]`.
This set is passed to `apply_repo_config_overlay()` as the `cli_explicit` parameter.
The set is also stored on the config object via the `cli_explicit_fields` frozen-set
field (marked `exclude=True` so it never appears in serialized output).

The purpose is to distinguish "caller intentionally set this value" from "value
happens to be present because Pydantic assigned a default." Without this tracking,
a repo-scoped overlay could silently overwrite a flag the operator explicitly passed
on the command line.

#### Repo-scoped overlay

The repo-scoped overlay is a JSON config file (typically at
`<data_root>/<repo_slug>/config.json`) that stores persistent per-repository
configuration. It is the fifth and final layer in the merge chain.

`apply_repo_config_overlay()` in `src/runtime_config.py` loads this file via
`load_config_file()` and iterates its key-value pairs. For each key that exists
in `HydraFlowConfig.model_fields` **and** is **not** in the `cli_explicit` set,
the value is written directly onto the config object via `object.__setattr__()`.
Fields that *are* in `cli_explicit` are skipped, preserving intentional CLI
overrides.

This overlay sits within the repo isolation model established by ADR-0003 and
ADR-0010: each repository gets its own data directory under `data_root`, and the
overlay file lives inside that directory so configuration is scoped per-repo
rather than shared globally.

### Two-layer dispatch

`hf_cli/__main__.py` handles supervisor/workspace commands directly and delegates
orchestrator flags to `cli.main()` via a `_FLAG_COMMANDS` mapping. This keeps the
two concern domains (workspace management vs. orchestrator operation) separated
without requiring a shared CLI framework.

## Consequences

**Positive:**

- Zero external CLI dependency — reduces supply chain surface and simplifies
  Docker images.
- Single, testable merge function (`build_config()`) owns all config precedence
  logic. Adding a new config source (e.g., remote config) requires changes in one
  place.
- Pydantic validation in `HydraFlowConfig` catches invalid combinations at
  startup, before any orchestrator loop runs.
- The `cli_explicit` tracking enables repo-scoped overlays to coexist with CLI
  overrides without ambiguity.

**Negative / Trade-offs:**

- argparse lacks Click's composable command groups. If the CLI grows many
  subcommands (beyond current flag-based dispatch), this decision should be
  revisited.
- The two-layer dispatch (`hf_cli` + `cli.py`) means CLI help is split across
  two parsers. Users running `hf --help` see workspace commands; orchestrator
  flags require `hf start --help`.
- Dashboard `/api/control/*` endpoints do not yet cover all CLI operations
  (clean, prep, scaffold, labels, audit). Parity will require either extending
  the API or invoking `cli.main()` programmatically from the dashboard.

**Pydantic startup-validation failure behavior:**

- When `HydraFlowConfig` construction fails (e.g., invalid field combinations,
  malformed Docker size notation, unrecognized repo format), Pydantic raises a
  `ValidationError` containing structured error details (field path, constraint
  violated, input value). Field validators (`@field_validator`) and the
  `resolve_defaults` model validator (`@model_validator(mode="after")`) raise
  `ValueError` for domain-specific checks (e.g., empty label list, invalid
  `visual_fail_threshold` range, unreachable Docker daemon).
- The calling layer (`load_runtime_config()` or direct construction) does not
  catch `ValidationError` — it propagates to the process entry point, producing
  a Pydantic-formatted error message on stderr and a non-zero exit code. This is
  intentional: configuration errors should halt startup immediately with a clear
  diagnostic rather than allowing a partially-configured orchestrator to run.
- No fallback config is loaded on failure. The operator must correct the
  invalid field(s) and restart.

## Alternatives considered

- **Click:** Would provide richer help formatting and subcommand composition, but
  adds an external dependency for marginal benefit given the current flag-heavy
  interface.
- **Typer:** Built on Click with type-hint-driven signatures. Attractive for new
  projects, but migrating 50+ argparse flags provides no functional improvement
  and adds two new dependencies (Typer + Click).
- **Flat config merge:** Spreading merge logic across call sites would make
  precedence rules implicit and harder to test. The builder pattern keeps them
  explicit and centralized.

## Related

- Source memory: Issue #2268
- `src/cli.py` — `build_config()`, `parse_args()`, `main()`
- `src/hf_cli/__main__.py` — Two-layer CLI dispatcher
- `src/config.py` — `HydraFlowConfig` Pydantic model
- `src/runtime_config.py` — `load_runtime_config()`, `apply_repo_config_overlay()`
- ADR-0003 (Git Worktrees for Issue Isolation) — repo isolation model
- ADR-0004 (Agent CLI as Runtime) — related but distinct: that ADR covers
  agent invocation via CLI subprocesses, this ADR covers HydraFlow's own CLI
- ADR-0010 (Worktree and Path Isolation) — path isolation that scopes the
  repo-scoped overlay to per-repository data directories
