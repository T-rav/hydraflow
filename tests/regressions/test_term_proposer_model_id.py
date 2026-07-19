"""Regression: term_proposer_runtime used retired model claude-sonnet-4-5.

ClaudeCLIClient hardcoded the stale model ID, causing every tick of
TermProposerLoop to fail with a CLI error (issue #9223, tick_error_ratio=1.0).

The default must always resolve to the current active Sonnet. It now uses the
``sonnet`` alias, which the Claude CLI resolves to the latest Sonnet — so this
pin no longer goes stale on each model bump (previously pinned to the literal
claude-sonnet-4-6, which broke when that model was retired).
"""

from __future__ import annotations

import inspect


def test_claude_cli_client_default_model_is_current() -> None:
    from term_proposer_runtime import ClaudeCLIClient

    sig = inspect.signature(ClaudeCLIClient.__init__)
    default_model = sig.parameters["model"].default
    assert default_model == "sonnet", (
        f"ClaudeCLIClient default model is {default_model!r}; "
        "must be the 'sonnet' alias (the CLI resolves it to the current Sonnet, "
        "so it never goes stale on a model bump)"
    )
