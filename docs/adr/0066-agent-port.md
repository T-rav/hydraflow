# ADR-0066 — AgentPort: Dependency-Injection Boundary for Agent Runner

**Status:** Proposed
**Date:** 2026-05-19
**Enforced by:** (none) — structural subtype check planned for `tests/test_ports.py` in follow-up

## Context

Infrastructure modules that need to shell out to the Claude Code agent (e.g. `merge_conflict_resolver`) originally imported `AgentRunner` or `BaseRunner` directly from the runner layer. This created a downward import from the infrastructure layer into the runner layer, violating the four-layer boundary (see ADR-0044 and the four-layer model in `docs/wiki/architecture-layers.md`).

The runner layer is also expensive to instantiate in tests — it wires real subprocess logic, paths, and config. Modules that only needed `build_command`, `execute`, and `verify_result` were forced to carry the full concrete dependency.

## Decision

Define `AgentPort` as a `@runtime_checkable Protocol` in `src/ports.py`. Infrastructure modules that need agent execution accept `AgentPort` as a constructor parameter rather than importing from the runner layer. Production wiring passes `AgentRunner`; tests pass `AsyncMock(spec=AgentPort)`.

The three declared methods are:

- `build_command(_worktree_path)` — constructs the CLI invocation
- `execute(cmd, prompt, cwd, event_data, *, on_output, telemetry_stats)` — runs the subprocess and returns the transcript
- `verify_result(worktree_path, branch)` — checks that the agent produced valid commits and quality passes

Method signatures are kept identical to `AgentRunner` so structural subtype checks pass without any code change to the concrete class.

## Consequences

- Infrastructure modules can be tested in isolation with a lightweight `AsyncMock(spec=AgentPort)`.
- The runner layer is no longer imported at infrastructure layer boundaries.
- Adding new methods to `AgentPort` requires a corresponding update to the concrete runner; the signature sync is verified by `tests/test_ports.py`.

## Alternatives considered

- **Import `BaseRunner` directly.** Simple but creates an illegal cross-layer import and makes infrastructure modules expensive to test.
- **Pass a callable.** Avoids a Protocol but loses the named-method contract and IDE discoverability.

## Related

- `src/ports.py:AgentPort` — the port definition
- `src/agent.py:AgentRunner`, `src/base_runner.py:BaseRunner` — concrete implementations
- [ADR-0044](0044-hydraflow-principles.md) — four-layer architecture
