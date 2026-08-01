"""Tests for arch.generators.ai_system_inventory (CH-7, #9735).

The inventory enumerates every autonomous decision-maker — background
loops from the orchestrator registry plus the pipeline workers from the
dashboard worker defs — and must be fully derived from the checkout: no
hand-maintained loop list, fail-loud when a registry loop is missing from
its source data, byte-stable output for drift CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arch.extractors.loops import extract_loops
from arch.generators.ai_system_inventory import (
    collect_inventory,
    render_ai_system_inventory,
)

# ---------------------------------------------------------------------------
# Synthetic-tree fixtures
# ---------------------------------------------------------------------------

_SYNTHETIC_TREE: dict[str, str] = {
    "src/orchestrator.py": """
        class Orchestrator:
            def __init__(self, svc):
                bg_loop_registry: dict[str, BaseBackgroundLoop] = {
                    "widget": svc.widget_loop,
                    "gadget": svc.gadget_loop,
                }
    """,
    "src/service_registry.py": """
        class ServiceRegistry:
            widget_loop: WidgetLoop
            gadget_loop: GadgetLoop
    """,
    "src/dashboard_routes/_control_routes.py": """
        _bg_worker_defs = [
            ("widget", "Widget", "Runs widget maintenance."),
            ("gadget", "Gadget", "Keeps gadgets fresh."),
        ]
    """,
    "src/config.py": """
        _ENV_COMBO_OVERRIDES: list[tuple[str, str, str]] = [
            ("HYDRAFLOW_WIDGET", "widget_tool", "widget_model"),
        ]

        class HydraFlowConfig:
            widget_tool: str = "claude"
            widget_model: str = "opus"
            gadget_model: str = "haiku"
    """,
    "src/widget_loop.py": """
        from base_background_loop import BaseBackgroundLoop

        class WidgetLoop(BaseBackgroundLoop):
            LONG_LLM_CYCLE = True

            async def _do_work(self):
                model = self._config.widget_model
                # escalates to the hydraflow-hitl queue on failure
                return {"status": "ok"}
    """,
    "src/gadget_helper.py": """
        def helper(config):
            return config.gadget_model
    """,
    "src/gadget_loop.py": """
        from base_background_loop import BaseBackgroundLoop
        from gadget_helper import helper

        class GadgetLoop(BaseBackgroundLoop):
            async def _do_work(self):
                return {"status": "ok"}
    """,
    "docs/arch/functional_areas.yml": """
        areas:
          caretaking:
            label: Caretaking
            description: synthetic
            loops:
              - WidgetLoop
              - GadgetLoop
    """,
}


@pytest.fixture
def synthetic_repo(fixture_src_tree) -> Path:
    return fixture_src_tree(_SYNTHETIC_TREE)


def _collect(repo_root: Path):
    loops = extract_loops(repo_root / "src")
    return collect_inventory(loops, repo_root=repo_root)


def _render(repo_root: Path) -> str:
    loops = extract_loops(repo_root / "src")
    return render_ai_system_inventory(loops, repo_root=repo_root)


# ---------------------------------------------------------------------------
# Synthetic tree — row derivation
# ---------------------------------------------------------------------------


def test_synthetic_rows_cover_registry_loops(synthetic_repo: Path):
    rows = _collect(synthetic_repo)
    assert rows is not None
    assert [(r.worker, r.kind) for r in rows] == [
        ("gadget", "loop"),
        ("widget", "loop"),
    ]


def test_synthetic_loop_row_fields(synthetic_repo: Path):
    rows = _collect(synthetic_repo)
    assert rows is not None
    widget = next(r for r in rows if r.worker == "widget")
    assert widget.class_name == "WidgetLoop"
    assert widget.area == "Caretaking"
    assert widget.model_fields == ["widget_model"]
    assert widget.long_llm_cycle is True
    assert "HITL escalation" in widget.oversight
    assert widget.purpose == "Runs widget maintenance."


def test_synthetic_model_role_found_via_one_hop_import(synthetic_repo: Path):
    """GadgetLoop references gadget_model only via its imported helper —
    the one-hop scan must attribute it."""
    rows = _collect(synthetic_repo)
    assert rows is not None
    gadget = next(r for r in rows if r.worker == "gadget")
    assert gadget.model_fields == ["gadget_model"]
    assert gadget.long_llm_cycle is False


# ---------------------------------------------------------------------------
# Synthetic tree — fail-loud contract
# ---------------------------------------------------------------------------


def test_missing_worker_def_fails_loudly(synthetic_repo: Path):
    routes = synthetic_repo / "src/dashboard_routes/_control_routes.py"
    routes.write_text(
        '_bg_worker_defs = [\n    ("widget", "Widget", "Runs widget maintenance."),\n]\n'
    )
    with pytest.raises(RuntimeError, match="gadget"):
        _collect(synthetic_repo)


def test_missing_functional_area_fails_loudly(synthetic_repo: Path):
    fa = synthetic_repo / "docs/arch/functional_areas.yml"
    fa.write_text(
        "areas:\n  caretaking:\n    label: Caretaking\n"
        "    description: synthetic\n    loops:\n      - WidgetLoop\n"
    )
    with pytest.raises(RuntimeError, match="GadgetLoop"):
        _collect(synthetic_repo)


def test_missing_service_registry_annotation_fails_loudly(synthetic_repo: Path):
    sr = synthetic_repo / "src/service_registry.py"
    sr.write_text("class ServiceRegistry:\n    widget_loop: WidgetLoop\n")
    with pytest.raises(RuntimeError, match="gadget_loop"):
        _collect(synthetic_repo)


def test_unknown_pipeline_worker_fails_loudly(synthetic_repo: Path):
    routes = synthetic_repo / "src/dashboard_routes/_control_routes.py"
    routes.write_text(
        "_bg_worker_defs = [\n"
        '    ("widget", "Widget", "Runs widget maintenance."),\n'
        '    ("gadget", "Gadget", "Keeps gadgets fresh."),\n'
        '    ("mystery", "Mystery", "Unmapped pipeline worker."),\n'
        "]\n"
    )
    with pytest.raises(RuntimeError, match="mystery"):
        _collect(synthetic_repo)


def test_placeholder_when_orchestrator_missing(synthetic_repo: Path):
    (synthetic_repo / "src/orchestrator.py").unlink()
    md = _render(synthetic_repo)
    assert "awaiting" in md
    assert "{{ARCH_FOOTER}}" in md


# ---------------------------------------------------------------------------
# Live tree — the real inventory
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_rows(real_repo_root: Path):
    loops = extract_loops(real_repo_root / "src")
    return collect_inventory(loops, repo_root=real_repo_root)


@pytest.fixture(scope="module")
def live_md(real_repo_root: Path) -> str:
    loops = extract_loops(real_repo_root / "src")
    return render_ai_system_inventory(loops, repo_root=real_repo_root)


@pytest.fixture(scope="module")
def real_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_live_every_registry_loop_present(live_rows):
    assert live_rows is not None
    loop_rows = [r for r in live_rows if r.kind == "loop"]
    workers = {r.worker for r in loop_rows}
    # Spot-check well-known registry keys across the fleet.
    assert {
        "pr_unsticker",
        "report_issue",
        "fitness_scorecard",
    } <= workers
    assert len(loop_rows) >= 50


def test_live_pipeline_workers_present(live_rows):
    pipeline = {r.worker for r in live_rows if r.kind == "pipeline"}
    assert {"triage", "plan", "implement", "review"} <= pipeline


def test_live_model_role_attribution(live_rows):
    by_worker = {r.worker: r for r in live_rows}
    assert "report_issue_model" in by_worker["report_issue"].model_fields
    assert "adr_review_model" in by_worker["adr_reviewer"].model_fields
    assert "triage_model" in by_worker["triage"].model_fields
    assert "planner_model" in by_worker["plan"].model_fields
    assert "review_model" in by_worker["review"].model_fields
    assert "model" in by_worker["implement"].model_fields


def test_live_long_llm_cycle_flags(live_rows):
    by_worker = {r.worker: r for r in live_rows}
    assert by_worker["report_issue"].long_llm_cycle is True
    assert by_worker["disturbance_dampener"].long_llm_cycle is True
    assert by_worker["convergence_oscillation"].long_llm_cycle is False


def test_live_md_structure(live_md: str):
    assert live_md.startswith("# AI System Inventory")
    assert "## Background loops" in live_md
    assert "## Pipeline workers" in live_md
    assert "## Model roles" in live_md
    assert "ADR-0049" in live_md
    assert "{{ARCH_FOOTER}}" in live_md


def test_live_md_is_deterministic(real_repo_root: Path):
    assert _render(real_repo_root) == _render(real_repo_root)
