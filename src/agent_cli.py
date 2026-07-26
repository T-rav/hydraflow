"""Agent CLI command builders for the Claude and Codex backends."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, get_args

AgentTool = Literal["claude", "codex"]

_SUPPORTED_TOOLS = frozenset(get_args(AgentTool))


def _require_supported_tool(tool: str) -> None:
    """Reject any harness other than the two supported CLIs.

    gemini/pi were removed (only claude + codex are supported), so a stale
    caller passing a dropped tool must fail loudly rather than silently
    spawn a ``[tool, ...]`` command for a binary we no longer wire.
    """
    if tool not in _SUPPORTED_TOOLS:
        msg = f"unsupported tool {tool!r}; supported: claude, codex"
        raise ValueError(msg)


# Base directory for plugins pre-cloned into the Docker image at build time
# (see Dockerfile.agent-base). Each subdirectory is passed as ``--plugin-dir``
# so the Claude CLI loads it for the session. On host machines this path
# doesn't exist and no flags are emitted — host-installed plugins are
# discovered via the default ``~/.claude/plugins/cache/`` path.
_PRE_CLONED_PLUGIN_ROOT = Path("/opt/plugins")


def _plugin_dir_flags() -> list[str]:
    """Return ``--plugin-dir`` flags for every pre-cloned plugin directory.

    Scans ``/opt/plugins/*`` dynamically so new plugins added to
    ``Dockerfile.agent-base`` don't require a parallel edit here. Returns
    an empty list when the root doesn't exist (host machines).
    """
    if not _PRE_CLONED_PLUGIN_ROOT.is_dir():
        return []
    flags: list[str] = []
    for entry in sorted(_PRE_CLONED_PLUGIN_ROOT.iterdir()):
        if entry.is_dir():
            flags.extend(["--plugin-dir", str(entry)])
    return flags


# Setting-source scope for isolated (contract-agent) claude spawns. Restricting
# the Claude CLI to the ``project`` scope drops user-level plugins and hooks —
# notably a host-installed superpowers ``SessionStart`` hook that injects
# "invoke a skill BEFORE any response, explore first" guidance into every
# headless ``claude -p`` session. That guidance derails strict-JSON contract
# agents (triage, judges, councils) off their output contract — they explore
# the repo instead of emitting the verdict — so the verdict parser finds
# nothing. ``--setting-sources project`` leaves OAuth/keychain auth intact
# (unlike ``--bare``, which forces ANTHROPIC_API_KEY). Callers that isolate also
# skip ``_plugin_dir_flags`` so a pre-cloned superpowers ``--plugin-dir`` can't
# re-introduce the hook inside the Docker image (an explicit ``--plugin-dir``
# load bypasses ``--setting-sources``).
_CONTRACT_SETTING_SOURCES = "project"


def claude_isolation_flags() -> list[str]:
    """Return flags restricting an isolated claude spawn to project settings.

    Public (not module-private) so callers outside this module — e.g.
    :func:`contract_recording.record_claude_stream` — can isolate a raw
    ``claude`` subprocess the same way :func:`build_agent_command` /
    :func:`build_lightweight_command` do, without re-deriving the flag.
    """
    return ["--setting-sources", _CONTRACT_SETTING_SOURCES]


# Tools the issue-derived implementer / auto-agent legitimately needs in
# restricted mode. WebFetch and WebSearch are deliberately EXCLUDED here and
# additionally placed on the disallow list — they are the agent's built-in
# network-egress/exfiltration surface that a prompt-injection payload would
# reach for. Bash stays allowed (the implementer must run git/tests/build), so
# a fully airtight egress block still requires a container-level network policy
# on the agent runtime (see ADR-0092). This is defence-in-depth, not a sandbox.
_RESTRICTED_ALLOWED_TOOLS = (
    "Bash Read Edit Write MultiEdit Glob Grep LS TodoWrite NotebookEdit Task Skill"
)
_NETWORK_EGRESS_TOOLS = ("WebFetch", "WebSearch")


def _merge_disallowed(disallowed_tools: str | None, extra: tuple[str, ...]) -> str:
    """Union a comma-separated disallow list with *extra* tool names."""
    present = [t.strip() for t in (disallowed_tools or "").split(",") if t.strip()]
    for name in extra:
        if name not in present:
            present.append(name)
    return ",".join(present)


def build_agent_command(
    *,
    tool: AgentTool,
    model: str,
    disallowed_tools: str | None = None,
    max_turns: int | None = None,
    effort: str | None = None,
    restricted: bool = False,
    isolate_user_settings: bool = False,
) -> list[str]:
    """Build a non-interactive command for an agent stage.

    *effort* sets the reasoning effort level (``"low"``, ``"medium"``,
    ``"high"``, ``"max"``).  When ``None``, the CLI default is used.

    *restricted* hardens issue-derived spawns (implementer, auto-agent) against
    prompt injection (ADR-0092): the blanket ``bypassPermissions`` is replaced
    by ``acceptEdits`` + an explicit tool allowlist, and the network-egress
    tools (WebFetch/WebSearch) are disallowed. Codex switches to its
    network-blocked ``workspace-write`` sandbox.

    *isolate_user_settings* (claude only) restricts the spawn to ``project``
    settings and skips the pre-cloned ``--plugin-dir`` flags. Strict-JSON
    contract agents (triage, judges, councils) set this so a host/user-level
    plugin's ``SessionStart`` hook can't inject skill-invocation guidance that
    breaks the JSON contract — see :data:`_CONTRACT_SETTING_SOURCES`.
    """
    _require_supported_tool(tool)
    if tool == "codex":
        return _build_codex_command(model=model, restricted=restricted)

    cmd = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--model",
        model,
        "--verbose",
    ]
    if restricted:
        cmd.extend(["--permission-mode", "acceptEdits"])
        cmd.extend(["--allowedTools", _RESTRICTED_ALLOWED_TOOLS])
        disallowed_tools = _merge_disallowed(disallowed_tools, _NETWORK_EGRESS_TOOLS)
    else:
        cmd.extend(["--permission-mode", "bypassPermissions"])
    if isolate_user_settings:
        cmd.extend(claude_isolation_flags())
    else:
        cmd.extend(_plugin_dir_flags())
    if disallowed_tools:
        cmd.extend(["--disallowedTools", disallowed_tools])
    if max_turns is not None:
        cmd.extend(["--max-turns", str(max_turns)])
    if effort is not None:
        cmd.extend(["--effort", effort])
    return cmd


def _build_codex_command(*, model: str, restricted: bool = False) -> list[str]:
    """Build a Codex `exec` command with non-interactive automation settings.

    In *restricted* mode the sandbox is ``workspace-write`` (writes allowed,
    network blocked) and the dangerous bypass flag is dropped — for codex this
    is a real network-egress block (ADR-0092). Otherwise the legacy
    ``danger-full-access`` behaviour is preserved for trusted, non-issue spawns.
    """
    cmd = [
        "codex",
        "exec",
        "--json",
        "--model",
        model,
        "--sandbox",
        "workspace-write" if restricted else "danger-full-access",
    ]
    if not restricted:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    cmd.append("--skip-git-repo-check")
    return cmd


def build_lightweight_command(
    *,
    tool: AgentTool,
    model: str,
    prompt: str,
    isolate_user_settings: bool = False,
) -> tuple[list[str], bytes | None]:
    """Build a simple CLI command for lightweight (non-streaming) callers.

    Unlike :func:`build_agent_command` which builds streaming commands for
    the full agent runners, this builds simple one-shot commands used by
    background workers (ADR reviewer, memory compaction, PR unsticker,
    transcript summarizer).

    Returns ``(cmd, input_bytes)`` where *input_bytes* is the prompt
    encoded as UTF-8 bytes when passed via stdin, or ``None`` when the
    prompt is short enough to pass as a CLI argument.

    Large prompts are passed via stdin to avoid hitting the OS
    ``ARG_MAX`` limit (typically ~130 KB on macOS/Linux).

    *isolate_user_settings* (claude only) restricts the spawn to ``project``
    settings and skips the pre-cloned ``--plugin-dir`` flags, shielding the
    contract worker from a host/user ``SessionStart`` hook — see
    :data:`_CONTRACT_SETTING_SOURCES`.
    """
    _require_supported_tool(tool)
    if tool == "codex":
        cmd = _build_codex_command(model=model)
        cmd.append(prompt)
        return cmd, None

    # For large prompts, pass via stdin to avoid OS ARG_MAX limit.
    prompt_bytes = prompt.encode()
    use_stdin = len(prompt_bytes) > 100_000  # ~100 KB threshold

    if use_stdin:
        cmd = [tool, "-p", "-", "--model", model]
        input_bytes: bytes | None = prompt_bytes
    else:
        cmd = [tool, "-p", prompt, "--model", model]
        input_bytes = None

    if tool == "claude":
        if isolate_user_settings:
            cmd.extend(claude_isolation_flags())
        else:
            cmd.extend(_plugin_dir_flags())
    return cmd, input_bytes
