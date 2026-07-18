"""Regression: term_proposer_runtime used retired model claude-sonnet-4-5.

ClaudeCLIClient hardcoded the stale model ID, causing every tick of
TermProposerLoop to fail with a CLI error (issue #9223, tick_error_ratio=1.0).

PR #9785 moved the default off a pinned version literal onto the "sonnet"
tier alias, which the CLI resolves to the current active Sonnet model —
so the default no longer goes stale when a model is retired.
"""

from __future__ import annotations

import inspect


def test_claude_cli_client_default_model_is_current() -> None:
    from term_proposer_runtime import ClaudeCLIClient

    sig = inspect.signature(ClaudeCLIClient.__init__)
    default_model = sig.parameters["model"].default
    assert default_model == "sonnet", (
        f"ClaudeCLIClient default model is {default_model!r}; "
        "expected the 'sonnet' tier alias so it never goes stale when a "
        "pinned version is retired"
    )
