"""Generate docs/arch/generated/ai_system_inventory.md (CH-7, #9735).

An EU-AI-Act-style inventory of every autonomous decision-maker in the
factory: the background loops registered in the orchestrator plus the
pipeline workers exposed on the dashboard. Each row carries the config
model role(s) the worker resolves, its ``LONG_LLM_CYCLE`` watchdog flag,
and the human-oversight signals detected in its source.

Derivation — nothing here is a hand-maintained list:

* ``src/orchestrator.py`` — the ``bg_loop_registry`` dict literal is the
  authoritative loop registry (worker key → ``svc.<attr>``).
* ``src/service_registry.py`` — ``ServiceRegistry`` annotations resolve
  each ``svc`` attribute to its loop class.
* ``src/dashboard_routes/_control_routes.py`` — ``_bg_worker_defs``
  supplies the human-readable purpose per worker and defines the pipeline
  workers (defs entries that are not registry loops).
* ``docs/arch/functional_areas.yml`` — loop class → functional area.
* ``src/config.py`` — ``_ENV_COMBO_OVERRIDES`` (the role registry) and the
  ``HydraFlowConfig`` ``*_model`` field names used for detection.
* Loop/phase source modules — model-role and oversight detection.

Model-role detection scans the worker's source module plus its direct
(one-hop) src-local imports for config ``*_model`` field references; the
implementation role (the bare ``model`` field) is matched as a
``config.model`` attribute read. ``src/config.py`` and
``src/service_registry.py`` are excluded from scan scope (they define and
wire the fields rather than resolve them).

Fail-loud contract: when the orchestrator registry exists but a registry
loop is missing from any of its source datasets (worker defs, service
annotations, extractor output, functional-area map, pipeline-source map),
generation raises ``RuntimeError`` so drift CI cannot silently publish an
incomplete inventory. When the registry sources themselves are absent
(synthetic fixture trees), a placeholder body is emitted instead.

Determinism: every input is a file in the checkout — no clock, no
network, no git-history windowing — so the emitted body is byte-stable
and drift-checkable.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from arch._functional_areas_schema import load_functional_areas
from arch._models import LoopInfo

# Pipeline workers (``_bg_worker_defs`` entries that are not registry
# loops) mapped to the source file(s) where the phase's decision-making
# lives. This maps metadata for a derived list — the LIST of pipeline
# workers still comes from ``_bg_worker_defs``, and an unmapped worker
# fails generation loudly.
_PIPELINE_WORKER_SOURCES: dict[str, tuple[str, ...]] = {
    "triage": ("src/triage_phase.py",),
    "plan": ("src/plan_phase.py",),
    # ``implement`` names every module of the phase package plus the
    # agent-runner module: the coding-agent spawn (the ``model`` resolution)
    # lives one module deeper than the phase, and the phase itself is a package
    # of per-stage mixins (Refs #11547). The oversight scan reads exactly these
    # files, so listing only the spine would drop the HITL/PR signals that live
    # in ``_abort.py`` / ``_pr.py`` and silently shrink the rendered row.
    "implement": (
        "src/implement_phase/_abort.py",
        "src/implement_phase/_beads.py",
        "src/implement_phase/_build.py",
        "src/implement_phase/_common.py",
        "src/implement_phase/_flow.py",
        "src/implement_phase/_phase.py",
        "src/implement_phase/_pr.py",
        "src/implement_phase/_screen.py",
        "src/implement_phase/_spec_review.py",
        "src/agent/_claude_md.py",
        "src/agent/_commit.py",
        "src/agent/_context.py",
        "src/agent/_plan.py",
        "src/agent/_prequality.py",
        "src/agent/_prompts.py",
        "src/agent/_quality.py",
        "src/agent/_runner.py",
        "src/agent/_skills.py",
    ),
    "review": ("src/review_phase/_phase.py",),
    "review_insights": ("src/review_insights.py",),
    "pipeline_poller": (),  # orchestrator-internal snapshot poller — no LLM
}

# Modules excluded from scan scope: they define/wire the config fields.
_SCAN_EXCLUDED_MODULES = frozenset({"config", "service_registry"})

_IMPLEMENT_MODEL_RE = re.compile(r"(?:_config|config|cfg)\.model\b")
_HITL_RE = re.compile(r"hitl", re.IGNORECASE)
_PR_GATE_RE = re.compile(
    r"generate_and_open_pr|open_automated_pr|pr_opener|create_pr|auto_pr"
)


@dataclass(frozen=True)
class InventoryRow:
    """One autonomous decision-maker in the rendered inventory."""

    worker: str
    kind: str  # "loop" | "pipeline"
    purpose: str
    class_name: str | None = None
    area: str | None = None
    model_fields: list[str] = field(default_factory=list)
    long_llm_cycle: bool | None = None
    oversight: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Source parsing (all AST/text — nothing imports runtime modules)
# ---------------------------------------------------------------------------


def _parse_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _assigned_value(node: ast.stmt, name: str) -> ast.expr | None:
    """Return the value expr when *node* assigns to *name* (Assign/AnnAssign)."""
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.value if node.target.id == name else None
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == name for t in node.targets
    ):
        return node.value
    return None


def _parse_bg_loop_registry(orchestrator_py: Path) -> dict[str, str]:
    """worker key → ``svc`` attribute name, from the dict literal."""
    for node in ast.walk(_parse_tree(orchestrator_py)):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = _assigned_value(node, "bg_loop_registry")
        if not isinstance(value, ast.Dict):
            continue
        out: dict[str, str] = {}
        for key, val in zip(value.keys, value.values, strict=True):
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and isinstance(val, ast.Attribute)
            ):
                out[key.value] = val.attr
        if out:
            return out
    raise RuntimeError(
        f"{orchestrator_py}: no bg_loop_registry dict literal found — "
        "the AI system inventory cannot be derived"
    )


def _first_name(node: ast.expr) -> str | None:
    """First identifier in an annotation (handles quoted / X | None forms)."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            return sub.id
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            return sub.value
    return None


def _parse_service_annotations(service_registry_py: Path) -> dict[str, str]:
    """ServiceRegistry attribute name → annotated class name."""
    for node in _parse_tree(service_registry_py).body:
        if not (isinstance(node, ast.ClassDef) and node.name == "ServiceRegistry"):
            continue
        out: dict[str, str] = {}
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                cls = _first_name(stmt.annotation)
                if cls:
                    out[stmt.target.id] = cls
        return out
    raise RuntimeError(
        f"{service_registry_py}: no ServiceRegistry class found — "
        "the AI system inventory cannot be derived"
    )


def _parse_bg_worker_defs(control_routes_py: Path) -> dict[str, tuple[str, str]]:
    """worker key → (label, description), from ``_bg_worker_defs``."""
    for node in ast.walk(_parse_tree(control_routes_py)):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = _assigned_value(node, "_bg_worker_defs")
        if not isinstance(value, ast.List):
            continue
        out: dict[str, tuple[str, str]] = {}
        for elt in value.elts:
            if isinstance(elt, ast.Tuple) and len(elt.elts) == 3:
                key, label, desc = (
                    e.value if isinstance(e, ast.Constant) else None for e in elt.elts
                )
                if (
                    isinstance(key, str)
                    and isinstance(label, str)
                    and isinstance(desc, str)
                ):
                    out[key] = (label, desc)
        return out
    raise RuntimeError(
        f"{control_routes_py}: no _bg_worker_defs list found — "
        "the AI system inventory cannot be derived"
    )


def _parse_role_table(config_py: Path) -> list[tuple[str, str, str]]:
    """(env combo, tool field, model field) rows from ``_ENV_COMBO_OVERRIDES``."""
    for node in ast.walk(_parse_tree(config_py)):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = _assigned_value(node, "_ENV_COMBO_OVERRIDES")
        if not isinstance(value, ast.List):
            continue
        out: list[tuple[str, str, str]] = []
        for elt in value.elts:
            if isinstance(elt, ast.Tuple) and len(elt.elts) == 3:
                parts = [
                    e.value
                    for e in elt.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
                if len(parts) == 3:
                    out.append((parts[0], parts[1], parts[2]))
        return out
    return []


def _parse_model_field_names(config_py: Path) -> list[str]:
    """``HydraFlowConfig`` field names ending in ``_model``, sorted."""
    for node in _parse_tree(config_py).body:
        if not (isinstance(node, ast.ClassDef) and node.name == "HydraFlowConfig"):
            continue
        return sorted(
            stmt.target.id
            for stmt in node.body
            if isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id.endswith("_model")
        )
    raise RuntimeError(
        f"{config_py}: no HydraFlowConfig class found — "
        "the AI system inventory cannot be derived"
    )


# ---------------------------------------------------------------------------
# Scan scope (module + one-hop src-local imports)
# ---------------------------------------------------------------------------


def _resolve_local_module(dotted: str, src_dir: Path) -> list[Path]:
    """Every file ``dotted`` names: one module, or a whole package.

    A package resolves to ALL of its modules, not just ``__init__.py``. Under
    the god-class recipe (#11547) a decomposed module's ``__init__`` is a
    re-export facade with no logic left in it, so resolving ``import
    pr_unsticker`` to that facade shrinks the one-hop scan to nothing and the
    rendered row silently loses every model role the class actually resolves
    — the same "stops seeing its subject when a module becomes a package"
    failure as #11673, but in a generator, where the only symptom is a table
    cell quietly turning into a dash.
    """
    parts = dotted.split(".")
    as_file = src_dir.joinpath(*parts).with_suffix(".py")
    if as_file.is_file():
        return [as_file]
    as_pkg = src_dir.joinpath(*parts) / "__init__.py"
    if as_pkg.is_file():
        return sorted(as_pkg.parent.rglob("*.py"))
    return []


def _one_hop_imports(module_path: Path, src_dir: Path) -> list[Path]:
    """src-local files imported directly by *module_path*, sorted."""
    try:
        tree = _parse_tree(module_path)
    except (OSError, SyntaxError):
        return []
    found: set[Path] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.update(_resolve_local_module(alias.name, src_dir))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module_path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                prefix = base.relative_to(src_dir).parts if base != src_dir else ()
            else:
                prefix = ()
            dotted_prefix = ".".join(prefix)
            module = node.module or ""
            dotted = f"{dotted_prefix}.{module}".strip(".") if dotted_prefix else module
            if dotted:
                found.update(_resolve_local_module(dotted, src_dir))
                for alias in node.names:
                    found.update(
                        _resolve_local_module(f"{dotted}.{alias.name}", src_dir)
                    )
    return sorted(
        p for p in found if p.stem not in _SCAN_EXCLUDED_MODULES or p.parent != src_dir
    )


def _scan_scope_text(entry_files: list[Path], src_dir: Path) -> str:
    """Concatenated source of the entry files plus their one-hop imports."""
    files: set[Path] = set()
    for entry in entry_files:
        if entry.is_file():
            files.add(entry)
            files.update(_one_hop_imports(entry, src_dir))
    return "\n".join(p.read_text() for p in sorted(files))


def _detect_model_fields(scope_text: str, model_field_names: list[str]) -> list[str]:
    hits = [
        name
        for name in model_field_names
        if re.search(rf"\b{re.escape(name)}\b", scope_text)
    ]
    if _IMPLEMENT_MODEL_RE.search(scope_text):
        hits.append("model")
    return sorted(hits)


def _detect_oversight(own_text: str) -> list[str]:
    signals: list[str] = []
    if _HITL_RE.search(own_text):
        signals.append("HITL escalation")
    if _PR_GATE_RE.search(own_text):
        signals.append("PR review + merge gate")
    return signals


def _class_long_llm_cycle(module_path: Path, class_name: str) -> bool:
    try:
        tree = _parse_tree(module_path)
    except (OSError, SyntaxError):
        return False
    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        for stmt in node.body:
            value = _assigned_value(stmt, "LONG_LLM_CYCLE")
            if isinstance(value, ast.Constant):
                return bool(value.value)
    return False


# ---------------------------------------------------------------------------
# Inventory assembly
# ---------------------------------------------------------------------------


def collect_inventory(
    loops: list[LoopInfo], *, repo_root: Path
) -> list[InventoryRow] | None:
    """Derive the inventory rows, or ``None`` when registry sources are absent."""
    repo_root = Path(repo_root).resolve()
    src_dir = repo_root / "src"
    orchestrator_py = src_dir / "orchestrator.py"
    control_routes_py = src_dir / "dashboard_routes" / "_control_routes.py"
    if not orchestrator_py.is_file() or not control_routes_py.is_file():
        return None

    config_py = src_dir / "config.py"
    fa_path = repo_root / "docs/arch/functional_areas.yml"
    if not config_py.is_file():
        raise RuntimeError(f"{config_py} missing — cannot derive model roles")
    if not fa_path.is_file():
        raise RuntimeError(f"{fa_path} missing — cannot derive functional areas")

    registry = _parse_bg_loop_registry(orchestrator_py)
    svc_classes = _parse_service_annotations(src_dir / "service_registry.py")
    worker_defs = _parse_bg_worker_defs(control_routes_py)
    model_field_names = _parse_model_field_names(config_py)
    fa = load_functional_areas(fa_path)
    area_by_class = {
        loop_cls: area.label for area in fa.areas.values() for loop_cls in area.loops
    }
    loops_by_class = {loop.name: loop for loop in loops}

    rows: list[InventoryRow] = []
    for worker in sorted(registry):
        svc_attr = registry[worker]
        if worker not in worker_defs:
            raise RuntimeError(
                f"registry loop {worker!r} missing from _bg_worker_defs — "
                "add it to the dashboard worker defs"
            )
        class_name = svc_classes.get(svc_attr)
        if class_name is None:
            raise RuntimeError(
                f"registry loop {worker!r}: ServiceRegistry has no annotation "
                f"for {svc_attr!r}"
            )
        loop_info = loops_by_class.get(class_name)
        if loop_info is None:
            raise RuntimeError(
                f"registry loop {worker!r}: class {class_name!r} not found by "
                "the loop extractor"
            )
        area = area_by_class.get(class_name)
        if area is None:
            raise RuntimeError(
                f"registry loop {worker!r}: class {class_name!r} missing from "
                "docs/arch/functional_areas.yml"
            )
        module_path = repo_root / loop_info.source_path
        own_text = module_path.read_text() if module_path.is_file() else ""
        scope_text = _scan_scope_text([module_path], src_dir)
        rows.append(
            InventoryRow(
                worker=worker,
                kind="loop",
                purpose=worker_defs[worker][1],
                class_name=class_name,
                area=area,
                model_fields=_detect_model_fields(scope_text, model_field_names),
                long_llm_cycle=_class_long_llm_cycle(module_path, class_name),
                oversight=_detect_oversight(own_text),
            )
        )

    for worker in sorted(set(worker_defs) - set(registry)):
        if worker not in _PIPELINE_WORKER_SOURCES:
            raise RuntimeError(
                f"pipeline worker {worker!r} (in _bg_worker_defs but not the "
                "loop registry) has no entry in _PIPELINE_WORKER_SOURCES — "
                "map its source module in arch/generators/ai_system_inventory.py"
            )
        entry_files = [repo_root / rel for rel in _PIPELINE_WORKER_SOURCES[worker]]
        own_text = "\n".join(p.read_text() for p in entry_files if p.is_file())
        scope_text = _scan_scope_text(entry_files, src_dir)
        rows.append(
            InventoryRow(
                worker=worker,
                kind="pipeline",
                purpose=worker_defs[worker][1],
                model_fields=_detect_model_fields(scope_text, model_field_names),
                long_llm_cycle=None,
                oversight=_detect_oversight(own_text),
            )
        )

    return rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_PLACEHOLDER = (
    "# AI System Inventory\n\n"
    "_(awaiting src/orchestrator.py bg_loop_registry and "
    "src/dashboard_routes/_control_routes.py — CH-7, #9735)_\n\n"
    "{{ARCH_FOOTER}}\n"
)

_HEADER = """# AI System Inventory

**Generated — do not edit.** Derived by `arch.runner` from
`src/orchestrator.py` (`bg_loop_registry`), `src/service_registry.py`
annotations, `src/dashboard_routes/_control_routes.py` (`_bg_worker_defs`),
`docs/arch/functional_areas.yml`, `src/config.py` role fields, and the
worker source modules. Every input is a file in the checkout, so the body
is byte-stable for drift CI.

This is the model-inventory view of the factory (SR 11-7 / EU-AI-Act-style
technical documentation): every autonomous decision-maker, the config
model role(s) it resolves, its watchdog class, and its human-oversight
points.

## Conventions

- **Kill-switch (ADR-0049):** every background loop gates its tick on the
  in-body enabled check (`if not self._enabled_cb(...)`), toggled live
  from the dashboard System tab and persisted in state. Enforced fleetwide
  by `tests/test_loop_kill_switch_completeness.py`, so it is stated once
  here rather than repeated per row.
- **Human oversight baseline:** all workers are kill-switchable and
  telemetered on the dashboard; loop-authored changes land as PRs behind
  branch protection. The *Oversight* column lists the additional signals
  detected in the worker's own source: `HITL escalation` (routes work to
  the human-in-the-loop label queue) and `PR review + merge gate` (output
  ships as a pull request).
- **Model role detection:** config `*_model` fields referenced in the
  worker's source module and its direct (one-hop) src-local imports; the
  implementation role (the bare `model` field) is matched as a
  `config.model` attribute read. `src/config.py` and
  `src/service_registry.py` are excluded from scan scope. `—` means no
  direct LLM role was detected (mechanical caretaker).
- **Long LLM cycle:** loops that set `LONG_LLM_CYCLE = True` earn the
  longer per-cycle watchdog bound (`loop_watchdog_llm_seconds`).
"""


def _fmt_models(model_fields: list[str]) -> str:
    return ", ".join(f"`{f}`" for f in model_fields) if model_fields else "—"


def _fmt_oversight(oversight: list[str]) -> str:
    return "; ".join(oversight) if oversight else "—"


def _fmt_cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_ai_system_inventory(loops: list[LoopInfo], *, repo_root: Path) -> str:
    """Render the inventory markdown (or a placeholder when sources are absent)."""
    rows = collect_inventory(loops, repo_root=repo_root)
    if rows is None:
        return _PLACEHOLDER

    role_table = _parse_role_table(Path(repo_root) / "src" / "config.py")

    parts: list[str] = [_HEADER]

    parts.append("\n## Model roles\n")
    parts.append(
        "\nRole registry from `config._ENV_COMBO_OVERRIDES` — each combo env"
        " var resolves a `(tool, model)` pair after the SYSTEM/BACKGROUND"
        " cascade (#9717 resolution).\n"
    )
    parts.append("\n| Env combo | Tool field | Model field |")
    parts.append("\n|---|---|---|")
    for env, tool_field, model_field in role_table:
        parts.append(f"\n| `{env}` | `{tool_field}` | `{model_field}` |")
    parts.append("\n")

    loop_rows = [r for r in rows if r.kind == "loop"]
    parts.append(f"\n## Background loops ({len(loop_rows)})\n")
    parts.append(
        "\n| Worker | Loop class | Area | Model role(s) | Long LLM cycle |"
        " Oversight | Purpose |"
    )
    parts.append("\n|---|---|---|---|---|---|---|")
    for r in loop_rows:
        long_cell = "✅" if r.long_llm_cycle else "—"
        parts.append(
            f"\n| `{r.worker}` | `{r.class_name}` | {_fmt_cell(r.area or '—')} |"
            f" {_fmt_models(r.model_fields)} | {long_cell} |"
            f" {_fmt_oversight(r.oversight)} | {_fmt_cell(r.purpose)} |"
        )
    parts.append("\n")

    pipeline_rows = [r for r in rows if r.kind == "pipeline"]
    parts.append(f"\n## Pipeline workers ({len(pipeline_rows)})\n")
    parts.append(
        "\nDashboard workers that are not background loops: the label-routed"
        " pipeline phases (ADR-0002) plus orchestrator-internal helpers."
        " Phases escalate to the HITL label queue on attempt exhaustion and"
        " their output merges only through the PR review + merge gates.\n"
    )
    parts.append("\n| Worker | Model role(s) | Oversight | Purpose |")
    parts.append("\n|---|---|---|---|")
    for r in pipeline_rows:
        parts.append(
            f"\n| `{r.worker}` | {_fmt_models(r.model_fields)} |"
            f" {_fmt_oversight(r.oversight)} | {_fmt_cell(r.purpose)} |"
        )
    parts.append("\n\n{{ARCH_FOOTER}}\n")
    return "".join(parts)
