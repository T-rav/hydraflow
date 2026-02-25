# Pi Backend Integration Plan for HydraFlow

## Goal
Integrate `pi` as a first-class agent execution backend alongside `claude` and `codex` across HydraFlow stages (triage, plan, implement, review, AC, verification, summarization, memory compaction, subskill/debug).

## Scope
- Agent backend selection and command-building
- Config/CLI/env support for selecting `pi`
- Stream parsing and telemetry support for `pi` output
- Tests for command builder, parser behavior, config literals, and CLI choices

Out of scope for first pass:
- Replacing GitHub task/PR source
- UI redesign; only minimal display compatibility fixes

## Current Architecture Findings
- Backend command construction is centralized in `src/agent_cli.py`.
- Execution path is shared via `BaseRunner._execute()` and `stream_claude_process()` in `src/runner_utils.py`.
- Transcript normalization is centralized in `src/stream_parser.py` and already handles Claude/Codex event shapes.
- Tool selection is constrained by `Literal[...]` fields in `src/config.py` and CLI `choices=[...]` in `src/cli.py`.

## Implementation Phases

### Phase A: Enable Pi in Configuration and Command Construction
1. Extend tool literals from `"claude"|"codex"` to `"claude"|"codex"|"pi"` across all agent-facing config fields.
2. Update CLI argument choices to include `pi` for all backend flags.
3. Extend `AgentTool` and `build_agent_command()` to emit non-interactive pi command(s).
4. Keep defaults unchanged (still Claude) to minimize behavior risk.

Deliverable: HydraFlow can be configured to call `pi` commands without parser/runtime changes yet.

### Phase B: Runtime Streaming and Parsing
1. Generalize `stream_claude_process()` into backend-agnostic process streaming.
2. Add pi-specific stdin/argument handling if needed.
3. Extend `StreamParser` with pi event schema parsing.
4. Ensure token usage extraction covers pi usage keys.

Deliverable: End-to-end transcript streaming and telemetry work under pi backend.

### Phase C: Validation and Hardening
1. Add/extend tests for config literals, CLI choices, command builder, parser, telemetry.
2. Run targeted suites then `make quality-lite`.
3. Add operational docs for canary rollout (`planner_tool=pi` first).

Deliverable: Stable integration with test coverage and rollout guidance.

## Risks and Mitigations
- Unknown pi stream schema: isolate parser mapping in one module and use fixtures.
- Behavior divergence across tools: keep unified runner contract and stage prompts unchanged.
- Operational regressions: canary by stage before full rollout.

## Suggested Rollout
1. Canary: `planner_tool=pi` only.
2. Expand to `triage_tool` and `transcript_summary_tool`.
3. Expand to implement/review after stability checks.

## Initial Execution Slice (Now)
Proceed with Phase A immediately:
- Update config literals
- Update CLI choices
- Add pi command builder path in `agent_cli.py`
- Add or update focused tests for these changes
