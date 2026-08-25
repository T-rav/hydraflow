"""P6 — Agents, loops, and label state machine (ADR-0044).

All five checks are conditional on `ctx.is_orchestration_repo`. Non-orchestration
repos see them as NA — the principle is informational for those projects, not a
conformance bar.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import CheckContext, Finding, Status
from ..registry import register
from ._helpers import finding


def _na_if_not_orchestration(ctx: CheckContext, check_id: str) -> Finding | None:
    if ctx.is_orchestration_repo:
        return None
    return finding(
        check_id,
        Status.NA,
        "not an orchestration repo — P6 is informational for this shape",
    )


@register("P6.1")
def _orchestrator_with_concurrent_loops(ctx: CheckContext) -> Finding:
    if (skip := _na_if_not_orchestration(ctx, "P6.1")) is not None:
        return skip
    orch = ctx.src_module("orchestrator")
    if not orch.exists():
        return finding("P6.1", Status.FAIL, f"{ctx.rel(orch)} missing")
    text = orch.read_text(encoding="utf-8", errors="replace")
    if "asyncio.gather" in text or "asyncio.TaskGroup" in text:
        return finding("P6.1", Status.PASS)
    return finding(
        "P6.1",
        Status.FAIL,
        f"{ctx.rel(orch)} has no asyncio.gather / TaskGroup — concurrent loop shape missing",
    )


_LABEL_FIELD_RE = re.compile(
    r"\b\w*_label\s*:\s*(str|list\[str\])\s*=\s*Field", re.MULTILINE
)


@register("P6.2")
def _labels_centralised(ctx: CheckContext) -> Finding:
    if (skip := _na_if_not_orchestration(ctx, "P6.2")) is not None:
        return skip
    config = ctx.src_module("config")
    if not config.exists():
        return finding("P6.2", Status.FAIL, f"{ctx.rel(config)} missing")
    text = config.read_text(encoding="utf-8", errors="replace")
    matches = _LABEL_FIELD_RE.findall(text)
    if len(matches) >= 4:
        return finding(
            "P6.2",
            Status.PASS,
            f"{len(matches)} *_label config fields",
        )
    return finding(
        "P6.2",
        Status.FAIL,
        f"only {len(matches)} *_label config fields — labels not centralised",
    )


@register("P6.3")
def _base_background_loop_class(ctx: CheckContext) -> Finding:
    if (skip := _na_if_not_orchestration(ctx, "P6.3")) is not None:
        return skip
    path = ctx.src_module("base_background_loop")
    if not path.exists():
        return finding(
            "P6.3",
            Status.FAIL,
            f"{ctx.rel(path)} missing — BaseBackgroundLoop not defined",
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    if re.search(r"class\s+BaseBackgroundLoop\b", text):
        return finding("P6.3", Status.PASS)
    return finding("P6.3", Status.FAIL, "BaseBackgroundLoop class not found")


_CHECKPOINT_MARKERS = (
    "service_registry",
    "orchestrator",
    "constants.js",
    "_common.py",
    "_interval",
)


@register("P6.4")
def _wiring_completeness_test(ctx: CheckContext) -> Finding:
    if (skip := _na_if_not_orchestration(ctx, "P6.4")) is not None:
        return skip
    tests_dir = ctx.root / "tests"
    if not tests_dir.is_dir():
        return finding("P6.4", Status.FAIL, "tests/ missing")
    candidates = [p for p in tests_dir.rglob("*.py") if _mentions_wiring(p)]
    if not candidates:
        return finding(
            "P6.4",
            Status.FAIL,
            "no wiring-completeness test found (looking for file mentioning loop + wiring)",
        )
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = sum(1 for marker in _CHECKPOINT_MARKERS if marker in text)
        if hits >= 4:
            return finding(
                "P6.4",
                Status.PASS,
                f"{path.name} covers {hits}/5 checkpoints",
            )
    names = ", ".join(sorted({p.name for p in candidates})[:3])
    return finding(
        "P6.4",
        Status.WARN,
        f"wiring test(s) found ({names}) but none cover ≥4 of the 5 checkpoints",
    )


def _mentions_wiring(path: Path) -> bool:
    name = path.name.lower()
    if "wiring" in name or "registration" in name:
        return True
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "loop_wiring" in text or "wiring_completeness" in text


_SWAP_LABEL_RE = re.compile(
    r"def\s+(swap_pipeline_labels|swap_labels|atomic_label_swap)\b"
)


@register("P6.5")
def _atomic_label_swap(ctx: CheckContext) -> Finding:
    if (skip := _na_if_not_orchestration(ctx, "P6.5")) is not None:
        return skip
    candidates = [
        ctx.src_module("pr_manager"),
        # PRManager's label surface was extracted to its own mixin module in
        # the Refs #11547 god-class decomposition; the helper is reachable
        # unchanged as PRManager.swap_pipeline_labels, but this probe greps
        # files rather than following inheritance.
        ctx.src_module("pr_manager_labels"),
        ctx.src_module("label_manager"),
        ctx.src_module("labels"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _SWAP_LABEL_RE.search(text):
            return finding(
                "P6.5",
                Status.PASS,
                f"atomic swap helper in {ctx.rel(path)}",
            )
    probed = ", ".join(ctx.rel(path) for path in candidates)
    return finding(
        "P6.5",
        Status.FAIL,
        "no swap_pipeline_labels / swap_labels / atomic_label_swap function "
        f"found (tried {probed})",
    )
