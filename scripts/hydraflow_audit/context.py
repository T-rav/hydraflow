"""Detect the shape of the target repo so conditional checks return NA cleanly.

A non-orchestration repo does not have an `orchestrator` module; P6 and related
orchestration-only checks mark themselves NA when run against it. A repo
without a UI directory skips browser E2E checks. Detection is intentionally
simple — the audit is about conformance, not cleverness.

Shape detection resolves modules through `CheckContext.src_module` /
`src_dir` rather than a flat `src/<name>.py` literal: the greenfield kernel
writer stamps `src/<pkg>/`, and a flat probe reads every repo it creates as
"not an orchestration repo, no UI" — turning P6 into a silent NA instead of a
verdict (#11709).
"""

from __future__ import annotations

from pathlib import Path

from .models import CheckContext


def build(root: Path) -> CheckContext:
    ctx = CheckContext(root=root)
    ctx.is_orchestration_repo = _detect_orchestration(ctx)
    ctx.has_ui = _detect_ui(ctx)
    return ctx


def _detect_orchestration(ctx: CheckContext) -> bool:
    candidates = [
        ctx.src_module("orchestrator"),
        ctx.src_module("base_background_loop"),
    ]
    return any(p.exists() for p in candidates)


def _detect_ui(ctx: CheckContext) -> bool:
    return (ctx.root / "ui").is_dir() or ctx.src_dir("ui").is_dir()
