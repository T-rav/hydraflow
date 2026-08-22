"""Tests for agent_cli.py — CLI command builders for Claude and Codex."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import agent_cli
from agent_cli import (
    build_agent_command,
    build_lightweight_command,
)


class TestSupportedTools:
    def test_agent_tool_is_claude_and_codex_only(self) -> None:
        """The harness supports exactly claude and codex — gemini/pi removed."""
        assert set(agent_cli.AgentTool.__args__) == {"claude", "codex"}

    def test_build_lightweight_command_rejects_removed_tools(self) -> None:
        """Removed harnesses must be rejected, not silently spawned."""
        for dead in ("gemini", "pi"):
            with pytest.raises((ValueError, KeyError)):
                build_lightweight_command(tool=dead, model="x", prompt="p")  # type: ignore[arg-type]

    def test_build_agent_command_rejects_removed_tools(self) -> None:
        for dead in ("gemini", "pi"):
            with pytest.raises((ValueError, KeyError)):
                build_agent_command(tool=dead, model="x")  # type: ignore[arg-type]


class TestBuildAgentCommand:
    def test_claude_default_command_structure(self) -> None:
        """Claude command should include -p, --output-format, --model, --verbose, --permission-mode."""
        cmd = build_agent_command(tool="claude", model="sonnet")

        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--output-format" in cmd
        assert cmd[cmd.index("--output-format") + 1] == "stream-json"
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "sonnet"
        assert "--verbose" in cmd
        assert "--permission-mode" in cmd
        assert cmd[cmd.index("--permission-mode") + 1] == "bypassPermissions"

    def test_claude_restricted_hardens_against_injection(self) -> None:
        """ADR-0092: restricted mode drops bypassPermissions and blocks egress tools."""
        cmd = build_agent_command(tool="claude", model="opus", restricted=True)
        assert cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"
        assert "bypassPermissions" not in cmd
        assert "--allowedTools" in cmd
        allow = cmd[cmd.index("--allowedTools") + 1]
        assert "Bash" in allow and "Edit" in allow and "Write" in allow
        assert "--disallowedTools" in cmd
        disallow = cmd[cmd.index("--disallowedTools") + 1]
        assert "WebFetch" in disallow
        assert "WebSearch" in disallow

    def test_claude_restricted_preserves_extra_disallowed(self) -> None:
        cmd = build_agent_command(
            tool="claude", model="opus", restricted=True, disallowed_tools="Foo"
        )
        disallow = cmd[cmd.index("--disallowedTools") + 1]
        assert "Foo" in disallow
        assert "WebFetch" in disallow

    def test_codex_restricted_uses_network_blocked_sandbox(self) -> None:
        cmd = build_agent_command(tool="codex", model="gpt", restricted=True)
        assert cmd[cmd.index("--sandbox") + 1] == "workspace-write"
        assert "danger-full-access" not in cmd
        assert "--dangerously-bypass-approvals-and-sandbox" not in cmd

    def test_codex_default_unchanged(self) -> None:
        cmd = build_agent_command(tool="codex", model="gpt")
        assert cmd[cmd.index("--sandbox") + 1] == "danger-full-access"
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd

    def test_codex_command_structure(self) -> None:
        """Codex command should include exec, --json, --model, --sandbox, etc."""
        cmd = build_agent_command(tool="codex", model="o4-mini")

        assert cmd[0] == "codex"
        assert "exec" in cmd
        assert "--json" in cmd
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "o4-mini"
        assert "--sandbox" in cmd
        assert cmd[cmd.index("--sandbox") + 1] == "danger-full-access"
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd
        assert "--skip-git-repo-check" in cmd

    def test_claude_with_disallowed_tools(self) -> None:
        """Claude command with disallowed_tools should include --disallowedTools flag."""
        cmd = build_agent_command(
            tool="claude", model="sonnet", disallowed_tools="Edit,Write"
        )

        assert "--disallowedTools" in cmd
        assert cmd[cmd.index("--disallowedTools") + 1] == "Edit,Write"

    def test_claude_with_max_turns(self) -> None:
        """Claude command with max_turns should include --max-turns flag."""
        cmd = build_agent_command(tool="claude", model="sonnet", max_turns=5)

        assert "--max-turns" in cmd
        assert cmd[cmd.index("--max-turns") + 1] == "5"

    def test_claude_with_both_optional_flags(self) -> None:
        """Both disallowed_tools and max_turns should produce both flags."""
        cmd = build_agent_command(
            tool="claude",
            model="opus",
            disallowed_tools="Bash",
            max_turns=10,
        )

        assert "--disallowedTools" in cmd
        assert cmd[cmd.index("--disallowedTools") + 1] == "Bash"
        assert "--max-turns" in cmd
        assert cmd[cmd.index("--max-turns") + 1] == "10"

    def test_claude_without_optional_flags(self) -> None:
        """Claude command with no optional params should omit --disallowedTools and --max-turns."""
        cmd = build_agent_command(tool="claude", model="haiku")

        assert "--disallowedTools" not in cmd
        assert "--max-turns" not in cmd

    def test_codex_ignores_disallowed_tools_and_max_turns(self) -> None:
        """Codex path returns a fixed array; disallowed_tools and max_turns are not applied."""
        cmd_plain = build_agent_command(tool="codex", model="o4-mini")
        cmd_with_opts = build_agent_command(
            tool="codex",
            model="o4-mini",
            disallowed_tools="Edit",
            max_turns=5,
        )

        assert cmd_plain == cmd_with_opts
        assert "--disallowedTools" not in cmd_with_opts
        assert "--max-turns" not in cmd_with_opts

    def test_claude_max_turns_converted_to_string(self) -> None:
        """max_turns integer should be converted to a string in the command."""
        cmd = build_agent_command(tool="claude", model="sonnet", max_turns=42)

        idx = cmd.index("--max-turns")
        assert cmd[idx + 1] == "42"


class TestBuildLightweightCommand:
    def test_codex_includes_prompt_as_positional_arg(self) -> None:
        """Codex command should append the prompt as a positional argument."""
        cmd, cmd_input = build_lightweight_command(
            tool="codex", model="o4-mini", prompt="summarize this"
        )

        assert cmd[0] == "codex"
        assert "exec" in cmd
        assert "--json" in cmd
        assert cmd[cmd.index("--model") + 1] == "o4-mini"
        assert cmd[-1] == "summarize this"
        assert cmd_input is None

    def test_codex_includes_standard_flags(self) -> None:
        """Codex command should include sandbox and bypass flags."""
        cmd, _ = build_lightweight_command(tool="codex", model="o4-mini", prompt="test")

        assert "--sandbox" in cmd
        assert cmd[cmd.index("--sandbox") + 1] == "danger-full-access"
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd
        assert "--skip-git-repo-check" in cmd

    def test_claude_uses_pipe_flag(self) -> None:
        """Claude command should use -p flag with prompt inline."""
        cmd, cmd_input = build_lightweight_command(
            tool="claude", model="sonnet", prompt="explain this"
        )

        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "explain this" in cmd
        assert cmd[cmd.index("--model") + 1] == "sonnet"
        assert cmd_input is None

    def test_claude_lightweight_requests_json_envelope(self) -> None:
        """The one-shot claude spawn must ask for the JSON result envelope.

        Without ``--output-format json`` the CLI prints bare text, the seam
        has no usage to record, and every successful call with a non-trivial
        prompt is reclassified ``status=failed`` / $0 by the zero-usage guard
        (#11514 / #11515 / #11516 — 100% of issue_refinement, sampled_audit,
        sampled_audit_adjudicate rows in the live ledger).
        """
        cmd, _ = build_lightweight_command(
            tool="claude", model="sonnet", prompt="explain this"
        )

        assert "--output-format" in cmd
        assert cmd[cmd.index("--output-format") + 1] == "json"
        # The prompt stays in its positional slot right after ``-p`` so the
        # MockWorld fake's argv extraction is untouched.
        assert cmd[cmd.index("-p") + 1] == "explain this"

    def test_claude_lightweight_stdin_path_requests_json_envelope(self) -> None:
        large_prompt = "x" * 100_001
        cmd, cmd_input = build_lightweight_command(
            tool="claude", model="sonnet", prompt=large_prompt
        )

        assert cmd[cmd.index("--output-format") + 1] == "json"
        assert cmd[cmd.index("-p") + 1] == "-"
        assert cmd_input == large_prompt.encode()

    def test_codex_lightweight_has_no_claude_output_format_flag(self) -> None:
        cmd, _ = build_lightweight_command(
            tool="codex", model="o4-mini", prompt="summarize this"
        )

        assert "--output-format" not in cmd

    def test_input_none_for_short_prompts(self) -> None:
        """cmd_input should be None for short prompts (passed as CLI arg)."""
        _, codex_input = build_lightweight_command(
            tool="codex", model="o4-mini", prompt="test"
        )
        _, claude_input = build_lightweight_command(
            tool="claude", model="sonnet", prompt="test"
        )

        assert codex_input is None
        assert claude_input is None

    def test_large_prompt_uses_stdin(self) -> None:
        """Prompts over 100KB should be passed via stdin, not as CLI arg."""
        large_prompt = "x" * 150_000
        cmd, cmd_input = build_lightweight_command(
            tool="claude", model="sonnet", prompt=large_prompt
        )

        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "-" in cmd  # stdin marker
        assert large_prompt not in cmd  # prompt NOT in command args
        assert cmd_input == large_prompt.encode()

    def test_large_prompt_codex_still_inline(self) -> None:
        """Codex always uses positional arg regardless of prompt size."""
        large_prompt = "x" * 150_000
        cmd, cmd_input = build_lightweight_command(
            tool="codex", model="o4-mini", prompt=large_prompt
        )

        assert cmd[-1] == large_prompt
        assert cmd_input is None

    def test_boundary_prompt_stays_inline(self) -> None:
        """Prompt of exactly 100KB should remain as CLI arg (not stdin)."""
        boundary_prompt = "x" * 100_000
        cmd, cmd_input = build_lightweight_command(
            tool="claude", model="sonnet", prompt=boundary_prompt
        )

        assert boundary_prompt in cmd
        assert cmd_input is None

    def test_boundary_plus_one_uses_stdin(self) -> None:
        """Prompt of 100KB + 1 byte should switch to stdin."""
        over_prompt = "x" * 100_001
        cmd, cmd_input = build_lightweight_command(
            tool="claude", model="sonnet", prompt=over_prompt
        )

        assert over_prompt not in cmd
        assert cmd_input is not None

    def test_codex_does_not_mutate_shared_state(self) -> None:
        """Calling build_lightweight_command twice should not share list references."""
        cmd1, _ = build_lightweight_command(
            tool="codex", model="o4-mini", prompt="first"
        )
        cmd2, _ = build_lightweight_command(
            tool="codex", model="o4-mini", prompt="second"
        )

        assert cmd1[-1] == "first"
        assert cmd2[-1] == "second"
        assert cmd1 is not cmd2


class TestPluginDirFlags:
    def test_plugin_dir_flags_returns_empty_when_root_missing(
        self, tmp_path: Path
    ) -> None:
        """No flags when plugin root directory doesn't exist on disk."""
        from unittest.mock import patch

        import agent_cli

        with patch.object(
            agent_cli, "_PRE_CLONED_PLUGIN_ROOT", tmp_path / "does-not-exist"
        ):
            assert agent_cli._plugin_dir_flags() == []

    def test_plugin_dir_flags_includes_existing_subdirs(self, tmp_path: Path) -> None:
        """Flags should include subdirectories that exist under the root."""
        from unittest.mock import patch

        import agent_cli

        root = tmp_path / "plugins"
        root.mkdir()
        (root / "lightfactory").mkdir()

        with patch.object(agent_cli, "_PRE_CLONED_PLUGIN_ROOT", root):
            flags = agent_cli._plugin_dir_flags()

        assert flags == ["--plugin-dir", str(root / "lightfactory")]

    def test_plugin_dir_flags_excludes_files(self, tmp_path: Path) -> None:
        """Non-directory entries (files) under the root should be skipped."""
        from unittest.mock import patch

        import agent_cli

        root = tmp_path / "plugins"
        root.mkdir()
        (root / "real-plugin").mkdir()
        (root / "README.md").write_text("not a plugin dir")

        with patch.object(agent_cli, "_PRE_CLONED_PLUGIN_ROOT", root):
            flags = agent_cli._plugin_dir_flags()

        assert flags == ["--plugin-dir", str(root / "real-plugin")]

    def test_claude_agent_command_includes_plugin_dirs(self, tmp_path: Path) -> None:
        """build_agent_command for claude should include --plugin-dir flags."""
        from unittest.mock import patch

        import agent_cli

        root = tmp_path / "plugins"
        root.mkdir()
        (root / "superpowers").mkdir()

        with patch.object(agent_cli, "_PRE_CLONED_PLUGIN_ROOT", root):
            cmd = build_agent_command(tool="claude", model="sonnet")

        assert "--plugin-dir" in cmd
        assert cmd[cmd.index("--plugin-dir") + 1] == str(root / "superpowers")

    def test_codex_command_does_not_include_plugin_dirs(self, tmp_path: Path) -> None:
        """Codex commands should not include --plugin-dir flags."""
        from unittest.mock import patch

        import agent_cli

        root = tmp_path / "plugins"
        root.mkdir()
        (root / "superpowers").mkdir()

        with patch.object(agent_cli, "_PRE_CLONED_PLUGIN_ROOT", root):
            cmd = build_agent_command(tool="codex", model="o4-mini")

        assert "--plugin-dir" not in cmd

    def test_lightweight_claude_includes_plugin_dirs(self, tmp_path: Path) -> None:
        """build_lightweight_command for claude should include --plugin-dir flags."""
        from unittest.mock import patch

        import agent_cli

        root = tmp_path / "plugins"
        root.mkdir()
        (root / "lightfactory").mkdir()

        with patch.object(agent_cli, "_PRE_CLONED_PLUGIN_ROOT", root):
            cmd, _ = build_lightweight_command(
                tool="claude", model="sonnet", prompt="test"
            )

        assert "--plugin-dir" in cmd
        assert cmd[cmd.index("--plugin-dir") + 1] == str(root / "lightfactory")

    def test_pre_cloned_plugin_root_points_at_opt_plugins(self) -> None:
        """The constant should point at /opt/plugins (where Dockerfile bakes plugins)."""
        from agent_cli import _PRE_CLONED_PLUGIN_ROOT

        assert Path("/opt/plugins") == _PRE_CLONED_PLUGIN_ROOT


class TestContractAgentIsolation:
    """``isolate_user_settings`` shields strict-JSON contract agents (triage,
    judges, councils) from host user-level plugins/hooks.

    A user-installed superpowers plugin registers a ``SessionStart`` hook that
    injects "invoke a skill BEFORE any response, explore first" guidance into
    every headless ``claude -p`` spawn. That guidance derails a contract agent
    off its JSON output contract (it explores the repo instead of emitting the
    verdict), so the verdict parser finds nothing. Restricting settings to the
    ``project`` scope drops the user-level plugin/hook while leaving OAuth /
    keychain auth intact (unlike ``--bare``), and the pre-cloned ``--plugin-dir``
    flags are skipped so the same leak can't happen inside the Docker image.
    """

    def test_streaming_claude_isolation_restricts_setting_sources_to_project(
        self,
    ) -> None:
        cmd = build_agent_command(
            tool="claude", model="sonnet", isolate_user_settings=True
        )

        assert "--setting-sources" in cmd
        assert cmd[cmd.index("--setting-sources") + 1] == "project"

    def test_streaming_claude_isolation_skips_pre_cloned_plugin_dirs(
        self, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        import agent_cli

        root = tmp_path / "plugins"
        root.mkdir()
        (root / "superpowers").mkdir()

        with patch.object(agent_cli, "_PRE_CLONED_PLUGIN_ROOT", root):
            cmd = build_agent_command(
                tool="claude", model="sonnet", isolate_user_settings=True
            )

        assert "--plugin-dir" not in cmd

    def test_streaming_claude_default_omits_setting_sources(self) -> None:
        cmd = build_agent_command(tool="claude", model="sonnet")

        assert "--setting-sources" not in cmd

    def test_streaming_non_claude_ignores_isolation(self) -> None:
        cmd = build_agent_command(tool="codex", model="gpt", isolate_user_settings=True)

        assert "--setting-sources" not in cmd

    def test_lightweight_claude_isolation_sets_project_and_drops_plugins(
        self, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        import agent_cli

        root = tmp_path / "plugins"
        root.mkdir()
        (root / "superpowers").mkdir()

        with patch.object(agent_cli, "_PRE_CLONED_PLUGIN_ROOT", root):
            cmd, _ = build_lightweight_command(
                tool="claude",
                model="sonnet",
                prompt="test",
                isolate_user_settings=True,
            )

        assert "--setting-sources" in cmd
        assert cmd[cmd.index("--setting-sources") + 1] == "project"
        assert "--plugin-dir" not in cmd

    def test_lightweight_claude_default_omits_setting_sources(self) -> None:
        cmd, _ = build_lightweight_command(tool="claude", model="sonnet", prompt="test")

        assert "--setting-sources" not in cmd
