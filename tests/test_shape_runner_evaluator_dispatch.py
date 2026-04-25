"""Spec §7 line 1616 — ShapeRunner evaluator dispatch wiring.

Mirror of ``tests/test_discover_runner_evaluator_dispatch.py`` for the
Shape phase. Full-coverage tests live in
``tests/test_shape_runner_evaluator.py``.
"""

from __future__ import annotations

import inspect


def test_shape_runner_module_imports() -> None:
    from shape_runner import ShapeRunner  # noqa: F401


def test_shape_runner_exposes_evaluator_attempt_cap_config() -> None:
    """Spec §4.10: ShapeRunner reads `max_shape_attempts` from config
    to bound the evaluator-retry loop."""
    from config import HydraFlowConfig

    field = HydraFlowConfig.model_fields.get("max_shape_attempts")
    assert field is not None, (
        "max_shape_attempts missing from HydraFlowConfig — "
        "ShapeRunner cannot bound its evaluator retries"
    )


def test_shape_runner_class_constructs_callable() -> None:
    from shape_runner import ShapeRunner

    assert inspect.isclass(ShapeRunner), (
        "ShapeRunner missing or not a class — evaluator dispatch has "
        "nowhere to plug into the runner"
    )
