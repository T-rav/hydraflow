"""S4's observed-boundary assertion and the framing rules under it (#11537).

ADR-0137 records a **conditional** go and S4 is the condition, so these are not
incidental unit tests — they are the tests of the thing the whole design's
safety rests on. Each one pins a single way the assertion must refuse, and the
refusals matter more than the acceptance: the finding that forced S4 into
existence (F2) is that a name deny-list is *fail-open*, so an assertion that
read an absent key, a renamed key or an unobserved version as a pass would
reproduce the exact defect inside the fix for it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from director_sandbox import (
    DIRECTOR_ENV_ALLOWLIST,
    DirectorSandboxError,
    ProbeEvidence,
    SurfaceVerdict,
    assert_observed_surface,
    build_scrubbed_env,
    captured_session_id,
    director_sandbox,
    last_init_frame,
    normalise_cli_version,
    parse_stream_json,
    turn_failed,
)

if TYPE_CHECKING:
    from pathlib import Path

EVIDENCE = ProbeEvidence(
    agent_cli_version="2.1.239 (Claude Code)",
    residual_agents=5,
    residual_skills=15,
    residual_slash_commands=42,
)


def _init(**overrides: Any) -> dict[str, Any]:
    """A clean init frame — every S4 part satisfied — with targeted overrides."""
    frame: dict[str, Any] = {
        "type": "system",
        "subtype": "init",
        "tools": [],
        "mcp_servers": [],
        "plugins": [],
        "agents": [],
        "skills": [],
        "slash_commands": [],
        "version": "2.1.239",
    }
    frame.update(overrides)
    return frame


# --------------------------------------------------------------------------
# S4 part 1 — tools present and empty
# --------------------------------------------------------------------------


def test_a_clean_isolated_turn_verifies() -> None:
    assert assert_observed_surface(_init(), evidence=EVIDENCE).verified is True


def test_a_turn_with_no_init_frame_is_unverified() -> None:
    observation = assert_observed_surface(None, evidence=EVIDENCE)

    assert observation.verdict is SurfaceVerdict.NO_INIT_FRAME


def test_an_absent_tools_key_reads_as_unverified_never_as_empty() -> None:
    # The CLI-upgrade shape S4 exists to catch: a renamed or dropped key must
    # not be mistaken for a proven-empty surface.
    frame = _init()
    del frame["tools"]

    observation = assert_observed_surface(frame, evidence=EVIDENCE)

    assert observation.verdict is SurfaceVerdict.TOOLS_KEY_ABSENT


def test_a_non_list_tools_key_reads_as_unverified() -> None:
    observation = assert_observed_surface(_init(tools={}), evidence=EVIDENCE)

    assert observation.verdict is SurfaceVerdict.TOOLS_KEY_ABSENT


def test_a_single_surviving_tool_refuses_the_turn() -> None:
    # Denying every advertised name still left two enabled in the probe, so a
    # residual surface is the *expected* failure, not a hypothetical one.
    observation = assert_observed_surface(
        _init(tools=["Grep", "Glob"]), evidence=EVIDENCE
    )

    assert observation.verdict is SurfaceVerdict.TOOLS_NOT_EMPTY


def test_a_refused_turn_reports_how_many_tools_it_saw() -> None:
    observation = assert_observed_surface(_init(tools=["Bash"]), evidence=EVIDENCE)

    assert observation.observed_tools == 1


# --------------------------------------------------------------------------
# S4 part 2 — mcp_servers and plugins
# --------------------------------------------------------------------------


def test_a_loaded_mcp_server_refuses_the_turn() -> None:
    observation = assert_observed_surface(
        _init(mcp_servers=[{"name": "some-server"}]), evidence=EVIDENCE
    )

    assert observation.verdict is SurfaceVerdict.MCP_OR_PLUGINS_PRESENT


def test_a_loaded_plugin_refuses_the_turn() -> None:
    observation = assert_observed_surface(
        _init(plugins=["superpowers"]), evidence=EVIDENCE
    )

    assert observation.verdict is SurfaceVerdict.MCP_OR_PLUGINS_PRESENT


def test_an_absent_plugins_key_refuses_the_turn() -> None:
    frame = _init()
    del frame["plugins"]

    observation = assert_observed_surface(frame, evidence=EVIDENCE)

    assert observation.verdict is SurfaceVerdict.MCP_OR_PLUGINS_PRESENT


# --------------------------------------------------------------------------
# S4 part 3 — finding F4's residual channels
# --------------------------------------------------------------------------


def test_residual_channels_at_the_probed_counts_still_verify() -> None:
    # These are CLI built-ins that survive isolation by construction and are
    # unreachable once Task and Skill are denied. Unchanged is fine; moved
    # is not.
    frame = _init(agents=[{}] * 5, skills=[{}] * 15, slash_commands=[{}] * 42)

    assert assert_observed_surface(frame, evidence=EVIDENCE).verified is True


def test_a_residual_channel_that_grew_refuses_the_turn() -> None:
    frame = _init(skills=[{}] * 16)

    observation = assert_observed_surface(frame, evidence=EVIDENCE)

    assert observation.verdict is SurfaceVerdict.RESIDUAL_CHANNEL_MOVED


# --------------------------------------------------------------------------
# S4 part 4 — the version fence
# --------------------------------------------------------------------------


def test_a_cli_upgrade_re_arms_the_gate() -> None:
    observation = assert_observed_surface(_init(version="2.2.0"), evidence=EVIDENCE)

    assert observation.verdict is SurfaceVerdict.CLI_VERSION_MISMATCH


def test_the_preflight_version_is_used_when_the_frame_carries_none() -> None:
    frame = _init()
    del frame["version"]

    observation = assert_observed_surface(
        frame, evidence=EVIDENCE, observed_cli_version="2.1.239"
    )

    assert observation.verified is True


def test_an_unobservable_version_refuses_the_turn() -> None:
    frame = _init()
    del frame["version"]

    observation = assert_observed_surface(frame, evidence=EVIDENCE)

    assert observation.verdict is SurfaceVerdict.CLI_VERSION_UNOBSERVED


def test_the_version_comparison_ignores_the_evidence_formatting() -> None:
    # The evidence records what ``claude --version`` printed; the init frame
    # carries a bare token. A fence that fired on formatting would be ignored.
    assert normalise_cli_version("2.1.239 (Claude Code)") == "2.1.239"


# --------------------------------------------------------------------------
# Evidence loading — fail closed rather than assert against nothing
# --------------------------------------------------------------------------


def test_the_committed_evidence_loads() -> None:
    from config import HydraFlowConfig

    evidence = ProbeEvidence.load(HydraFlowConfig().director_probe_evidence_path())

    assert evidence.agent_cli_version


def test_evidence_without_a_cli_version_refuses_to_load() -> None:
    with pytest.raises(DirectorSandboxError, match="agent_cli_version"):
        ProbeEvidence.from_json(json.dumps({"proofs": []}))


def test_unreadable_evidence_refuses_to_load(tmp_path: Path) -> None:
    with pytest.raises(DirectorSandboxError, match="unreadable"):
        ProbeEvidence.load(tmp_path / "absent.json")


# --------------------------------------------------------------------------
# S5 — framing discipline
# --------------------------------------------------------------------------


def test_is_error_beats_a_success_subtype() -> None:
    # Observed on the same frame in the committed evidence. Keying on subtype
    # is fail-open; is_error is authoritative.
    frames = [{"type": "result", "subtype": "success", "is_error": True}]

    assert turn_failed(frames) is True


def test_a_turn_with_no_result_frame_counts_as_failed() -> None:
    assert turn_failed([{"type": "system", "subtype": "init"}]) is True


def test_the_last_init_frame_wins_under_upstream_retry() -> None:
    frames = [
        {"type": "system", "subtype": "init", "tools": ["Bash"]},
        {"type": "system", "subtype": "init", "tools": []},
    ]

    assert last_init_frame(frames) == {
        "type": "system",
        "subtype": "init",
        "tools": [],
    }


def test_an_unframed_banner_line_is_refused() -> None:
    with pytest.raises(ValueError, match="unframed output"):
        parse_stream_json('Welcome to the CLI\n{"type":"result"}\n')


def test_the_vendor_session_id_is_captured_as_a_hint() -> None:
    assert captured_session_id([{"session_id": "abc-123"}]) == "abc-123"


# --------------------------------------------------------------------------
# S1/S2 — the environment allow-list
# --------------------------------------------------------------------------


def test_no_variable_outside_the_allow_list_survives() -> None:
    hostile = {
        "ANTHROPIC_API_KEY": "sk-real",
        "GH_TOKEN": "ghp_real",
        "SSH_AUTH_SOCK": "/tmp/agent",
        "PATH": "/usr/bin",
    }

    env = build_scrubbed_env(hostile, home="/h", config_dir="/c")

    assert set(env) <= DIRECTOR_ENV_ALLOWLIST


def test_an_inherited_auth_token_is_dropped_even_though_the_name_is_allowed() -> None:
    # The name is on the allow-list because the VIRTUAL key occupies it. An
    # operator's real token must not ride in on that permission.
    env = build_scrubbed_env(
        {"ANTHROPIC_AUTH_TOKEN": "sk-operator-real"}, home="/h", config_dir="/c"
    )

    assert "ANTHROPIC_AUTH_TOKEN" not in env


def test_the_virtual_gateway_key_is_the_one_credential_that_is_passed() -> None:
    env = build_scrubbed_env(
        {}, home="/h", config_dir="/c", gateway_token="hf-virtual-123"
    )

    assert env["ANTHROPIC_AUTH_TOKEN"] == "hf-virtual-123"


def test_home_is_overwritten_with_the_disposable_sandbox_path() -> None:
    env = build_scrubbed_env({"HOME": "/Users/operator"}, home="/h", config_dir="/c")

    assert env["HOME"] == "/h"


# --------------------------------------------------------------------------
# S1 — the disposable boundary
# --------------------------------------------------------------------------


def test_the_sandbox_working_directory_is_empty(tmp_path: Path) -> None:
    # An empty non-project cwd is what makes ``--setting-sources project`` load
    # nothing: there is no .claude/settings.json and no CLAUDE.md to find.
    with director_sandbox(base_dir=tmp_path) as paths:
        assert list(paths.cwd.iterdir()) == []


def test_the_sandbox_is_destroyed_on_exit(tmp_path: Path) -> None:
    with director_sandbox(base_dir=tmp_path) as paths:
        root = paths.root

    assert root.exists() is False


def test_the_sandbox_is_destroyed_even_when_the_turn_raises(tmp_path: Path) -> None:
    captured: Path | None = None
    with pytest.raises(RuntimeError), director_sandbox(base_dir=tmp_path) as paths:
        captured = paths.root
        raise RuntimeError("turn blew up")

    assert captured is not None and captured.exists() is False


def test_an_unusable_base_directory_fails_closed(tmp_path: Path) -> None:
    # S1 forbids degrading to the bypassPermissions builder, and a half-built
    # sandbox is that fallback wearing a different name.
    with (
        pytest.raises(DirectorSandboxError),
        director_sandbox(base_dir=tmp_path / "does-not-exist"),
    ):
        pass  # pragma: no cover — construction must raise first


def test_a_renamed_capability_channel_reads_as_moved_not_as_empty() -> None:
    # Parts 1 and 2 refuse an absent key outright; part 3 must too, or the
    # assertion is fail-open on one of its own four legs. A CLI that renames
    # `agents` to `subagents` would otherwise read as "zero agents" and verify —
    # exactly finding F2's shape, inside the fix for it.
    frame = _init()
    del frame["agents"]

    observation = assert_observed_surface(frame, evidence=EVIDENCE)

    assert observation.verdict is SurfaceVerdict.RESIDUAL_CHANNEL_MOVED
