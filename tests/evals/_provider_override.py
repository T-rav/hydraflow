"""Run an eval corpus against a candidate LLM backend, for comparison.

The evals build their component from the runtime ``HydraFlowConfig``, so they
respect each role's provider/model dials (the pluggable one-shot provider). To
A/B a candidate — e.g. "is DeepSeek via OpenRouter as good as Sonnet for
wiki-compile?" — set two env vars and re-run the same corpus:

    # baseline (defaults: claude)
    uv run pytest tests/evals/test_wiki_compile_evals.py -m evals -v

    # candidate
    HYDRAFLOW_EVAL_PROVIDER=openrouter \\
    HYDRAFLOW_EVAL_MODEL=deepseek/deepseek-chat \\
    uv run pytest tests/evals/test_wiki_compile_evals.py -m evals -v

Then compare the reported accuracy. Each eval fixture calls
:func:`apply_provider_override` with its role's dial field names.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

EVAL_PROVIDER_ENV = "HYDRAFLOW_EVAL_PROVIDER"
EVAL_MODEL_ENV = "HYDRAFLOW_EVAL_MODEL"


def eval_backend() -> tuple[str | None, str | None]:
    """The candidate (provider, model) from the environment, or (None, None)."""
    return (
        os.environ.get(EVAL_PROVIDER_ENV) or None,
        os.environ.get(EVAL_MODEL_ENV) or None,
    )


def apply_provider_override(
    config: HydraFlowConfig, *, provider_field: str, model_field: str
) -> HydraFlowConfig:
    """Override one role's provider/model dials from the eval env vars.

    A no-op when neither env var is set (the eval runs on the config default,
    i.e. the baseline). Mutates the frozen config in place via
    ``object.__setattr__`` and returns it for chaining.
    """
    provider, model = eval_backend()
    if provider is not None:
        object.__setattr__(config, provider_field, provider)
    if model is not None:
        object.__setattr__(config, model_field, model)
    return config


def backend_label() -> str:
    """Human-readable label of the backend under test, for eval reports."""
    provider, model = eval_backend()
    if provider is None and model is None:
        return "default (config dials)"
    return f"{provider or 'default'}:{model or 'default'}"
