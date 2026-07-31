"""ADR-0118 enforcement: no OpenTelemetry imports under ``src/``.

ADR-0118 supersedes ADR-0055 and removes the OTel/Honeycomb telemetry layer —
observability is the SRE agent's job (targeting New Relic), not instrumentation
woven into the loops. This guard fails if any ``opentelemetry`` import, or a
re-introduced ``telemetry.spans``/``telemetry.otel`` module, creeps back into
production code. Static AST scan only; never imports the modules.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BANNED_MODULE_PREFIXES = ("opentelemetry",)
_BANNED_MODULES = {
    "telemetry.spans",
    "telemetry.otel",
    "telemetry.subprocess_bridge",
    "telemetry.slugs",
}
_IGNORED_DIRS = {".venv", "node_modules", "__pycache__", "hydraflow.egg-info"}


def _is_banned(module: str) -> bool:
    return module in _BANNED_MODULES or any(
        module == p or module.startswith(f"{p}.") for p in _BANNED_MODULE_PREFIXES
    )


def test_no_opentelemetry_imports_in_src(real_repo_root: Path) -> None:
    """Production code carries no OTel dependency (ADR-0118)."""
    src = real_repo_root / "src"
    offenders: list[str] = []
    for py in src.rglob("*.py"):
        if _IGNORED_DIRS.intersection(py.parts):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = py.relative_to(real_repo_root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [
                    f"{rel}: import {a.name}" for a in node.names if _is_banned(a.name)
                ]
            elif isinstance(node, ast.ImportFrom) and _is_banned(node.module or ""):
                offenders.append(f"{rel}: from {node.module} import ...")

    assert offenders == [], (
        "OTel/Honeycomb was removed per ADR-0118 (observability belongs to the "
        "SRE agent, targeting New Relic). No opentelemetry / telemetry.spans "
        "imports are allowed under src/:\n  " + "\n  ".join(offenders)
    )
