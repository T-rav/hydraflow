"""Regression: shared caretaker spawns inherit maintenance routing.

The queue-clear profile routes maintenance work through the gateway while the
fleet ratchet is intentionally off. These clients used to inherit the GLM model
but silently default their transport back to native Claude, which rejects the
model before any gateway request is made.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from config import HydraFlowConfig
from execution import SimpleResult
from intervention_tally_loop import _CLIClassifier
from issue_refinement_loop import _CLIRefinementLLM
from sampled_audit_loop import _CLIAdjudicatorLLM, _CLIAuditLLM
from skill_prompt_eval_loop import _CLIRefineLLM


def test_only_shared_caretakers_omit_lightweight_provider() -> None:
    src_root = Path(__file__).resolve().parents[2] / "src"
    omitted: Counter[str] = Counter()
    for path in src_root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if name == "run_lightweight_agent" and not any(
                keyword.arg == "provider" for keyword in node.keywords
            ):
                omitted[path.relative_to(src_root).as_posix()] += 1

    assert omitted == Counter(
        {
            "issue_refinement_loop.py": 1,
            "sampled_audit_loop.py": 2,
            "intervention_tally_loop.py": 1,
            "skill_prompt_eval_loop.py": 1,
        }
    )


@pytest.mark.asyncio
async def test_shared_caretakers_inherit_gateway_with_background_model_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = HydraFlowConfig(
        maintenance_provider="gateway",
        background_tool="claude",
        background_model="glm-5.2",
        triage_provider="gateway",
        report_issue_model="opus",
        gateway_fleet_ratchet_enabled=False,
    )
    calls: list[tuple[str, str, str, str]] = []

    async def _capture_cli(**kwargs: Any) -> SimpleResult:
        calls.append(
            (
                kwargs["source"],
                kwargs["provider"],
                kwargs["tool"],
                kwargs["model"],
            )
        )
        return SimpleResult(stdout="{}", returncode=0)

    monkeypatch.setattr("runner_utils._claude_cli_complete", _capture_cli)
    monkeypatch.setattr(
        "runner_utils.gate_prompt",
        lambda prompt, **_kwargs: SimpleNamespace(prompt=prompt),
    )
    monkeypatch.setattr(
        "runner_utils.record_inference_telemetry",
        lambda *_args, **_kwargs: None,
    )

    await _CLIAuditLLM(config).audit(prompt="audit")
    await _CLIAdjudicatorLLM(config).adjudicate(prompt="adjudicate")
    await _CLIRefinementLLM(config).complete("refine")
    await _CLIClassifier(config).complete("classify")
    await _CLIRefineLLM(config).complete("skill")

    assert calls == [
        ("sampled_audit", "gateway", "claude", "glm-5.2"),
        ("sampled_audit_adjudicate", "gateway", "claude", "glm-5.2"),
        ("issue_refinement", "gateway", "claude", "glm-5.2"),
        ("intervention_tally", "gateway", "claude", "glm-5.2"),
        ("skill_prompt_refine", "gateway", "claude", "glm-5.2"),
    ]


@pytest.mark.asyncio
async def test_cached_caretaker_clients_resolve_live_model_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = HydraFlowConfig(
        maintenance_provider="gateway",
        maintenance_model="sonnet",
    )
    models: list[str] = []

    async def _capture_cli(**kwargs: Any) -> SimpleResult:
        models.append(kwargs["model"])
        return SimpleResult(stdout="{}", returncode=0)

    monkeypatch.setattr("runner_utils._claude_cli_complete", _capture_cli)
    monkeypatch.setattr(
        "runner_utils.gate_prompt",
        lambda prompt, **_kwargs: SimpleNamespace(prompt=prompt),
    )
    monkeypatch.setattr(
        "runner_utils.record_inference_telemetry",
        lambda *_args, **_kwargs: None,
    )
    clients = (
        _CLIAuditLLM(config),
        _CLIAdjudicatorLLM(config),
        _CLIRefinementLLM(config),
        _CLIClassifier(config),
    )

    await clients[0].audit(prompt="audit")
    await clients[1].adjudicate(prompt="adjudicate")
    await clients[2].complete("refine")
    await clients[3].complete("classify")
    object.__setattr__(config, "maintenance_model", "glm-5.2")
    await clients[0].audit(prompt="audit")
    await clients[1].adjudicate(prompt="adjudicate")
    await clients[2].complete("refine")
    await clients[3].complete("classify")

    assert models == ["sonnet"] * 4 + ["glm-5.2"] * 4
