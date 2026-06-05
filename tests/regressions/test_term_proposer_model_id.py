"""Regression: term_proposer_runtime used retired model claude-sonnet-4-5.

ClaudeCLIClient hardcoded the stale model ID, causing every tick of
TermProposerLoop to fail with a CLI error (issue #9223, tick_error_ratio=1.0).

The default must always match the current active Sonnet model in the fleet.
"""

from __future__ import annotations

import inspect


def test_claude_cli_client_default_model_is_current() -> None:
    from term_proposer_runtime import ClaudeCLIClient

    sig = inspect.signature(ClaudeCLIClient.__init__)
    default_model = sig.parameters["model"].default
    assert default_model == "claude-sonnet-4-6", (
        f"ClaudeCLIClient default model is {default_model!r}; "
        "update to the current active Sonnet model when models are retired"
    )
