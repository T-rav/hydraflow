"""Regression pin for issue #9555: heavy-make timeouts are knobs, not constants.

Two trust-fleet caretaker loops invoke heavy ``make`` targets whose healthy
runtime scales with corpus/repo size. Their subprocess bounds were hardcoded
module constants:

- ``skill_prompt_eval_loop._ADVERSARIAL_TIMEOUT_SECONDS = 3600``
  (bounds ``make trust-adversarial`` and the live refine-validation runner)
- ``principles_audit_loop._AUDIT_TIMEOUT_SECONDS = 1800``
  (bounds ``make audit-json``)

A hardcoded bound is a lose-lose: too low silently degrades the loop to a
permanent no-op (false timeout every tick); too high weakens wedged-child
protection. #9555 converted BOTH into operator-tunable ``HydraFlowConfig``
knobs surfaced on the System tab (settings_registry) and re-read from the live
config at every invocation:

- ``skill_prompt_eval_adversarial_timeout_seconds`` (default 3600, ge=60,
  le=21600)
- ``principles_audit_timeout_seconds`` (default 1800, ge=60, le=21600)

Per the heavy-make-tunable vs fixed-tier convention, ONLY the heavy make-class
bounds became knobs; incidental ``gh``/``git`` tier constants (e.g.
``principles_audit_loop._GIT_TIMEOUT_SECONDS = 120``) intentionally stay fixed.

This pin fails if a future change reverts a converted site to a hardcoded
module constant, drops a knob from the config model or the settings registry,
or lets the env-override table default drift from the Field default (which
silently disables the boot-time override). It also pins the #9580 follow-up
(closed into #9555): ``staging_bisect_runtime_cap_seconds`` must stay
operator-visible in the settings registry.
"""

from __future__ import annotations

import annotated_types as at

# The constants #9555 converted. A revert reintroduces the name.
_CONVERTED = {
    "skill_prompt_eval_loop": "_ADVERSARIAL_TIMEOUT_SECONDS",
    "principles_audit_loop": "_AUDIT_TIMEOUT_SECONDS",
}

# knob field -> (default, ge, le)
_KNOBS = {
    "skill_prompt_eval_adversarial_timeout_seconds": (3600, 60, 21600),
    "principles_audit_timeout_seconds": (1800, 60, 21600),
}


def test_converted_constants_do_not_come_back() -> None:
    import importlib

    for module_name, const in _CONVERTED.items():
        module = importlib.import_module(module_name)
        assert not hasattr(module, const), (
            f"{module_name}.{const} is back — #9555 converted this hardcoded "
            f"heavy-make timeout into a HydraFlowConfig knob; do not revert "
            f"it to a module constant"
        )


def test_knob_fields_exist_with_pinned_defaults_and_bounds() -> None:
    from config import HydraFlowConfig

    for field, (default, ge, le) in _KNOBS.items():
        info = HydraFlowConfig.model_fields.get(field)
        assert info is not None, f"HydraFlowConfig.{field} was removed (#9555)"
        assert info.default == default, (
            f"{field} default changed from {default} to {info.default}; the "
            f"default must preserve the pre-#9555 constant's behaviour"
        )
        bounds = {type(m): m for m in info.metadata if isinstance(m, at.Ge | at.Le)}
        assert bounds.get(at.Ge) and bounds[at.Ge].ge == ge, (
            f"{field} lost its ge={ge} floor (guards the too-low permanent "
            f"no-op failure mode)"
        )
        assert bounds.get(at.Le) and bounds[at.Le].le == le, (
            f"{field} lost its le={le} ceiling (guards the too-high weak "
            f"protection failure mode)"
        )


def test_loops_read_the_knob_not_a_literal() -> None:
    """Each converted call site passes the live config attribute."""
    import inspect

    import principles_audit_loop
    import skill_prompt_eval_loop

    skill_src = inspect.getsource(skill_prompt_eval_loop)
    assert (
        skill_src.count(
            "timeout=self._config.skill_prompt_eval_adversarial_timeout_seconds"
        )
        == 2
    ), (
        "skill_prompt_eval_loop must bound BOTH adversarial-eval subprocess "
        "sites (_run_corpus and _validate_candidate) with the config knob"
    )

    audit_src = inspect.getsource(principles_audit_loop)
    assert "self._config.principles_audit_timeout_seconds" in audit_src, (
        "principles_audit_loop must bound `make audit-json` with the config knob"
    )
    # The fixed gh/git tier is deliberate — the incidental git call stays 120s.
    assert principles_audit_loop._GIT_TIMEOUT_SECONDS == 120


def test_knobs_are_registered_for_the_system_tab() -> None:
    from settings_registry import SETTINGS, mutable_field_names

    for field in _KNOBS:
        assert field in mutable_field_names(), (
            f"{field} dropped from settings_registry.SETTINGS — the knob "
            f"would be silently non-PATCHable and invisible on the System tab"
        )
        assert SETTINGS[field].live is True, (
            f"{field} must stay live=True: the loops re-read it from config "
            f"at every subprocess invocation"
        )
    # #9580 (closed into #9555): the pre-existing bisect cap must stay visible.
    assert "staging_bisect_runtime_cap_seconds" in mutable_field_names(), (
        "staging_bisect_runtime_cap_seconds dropped from the settings "
        "registry — #9580 made runtime caps operator-visible"
    )


def test_env_override_rows_match_field_defaults() -> None:
    """A drifted table default silently disables the boot-time env override."""
    from config import _ENV_INT_OVERRIDES, HydraFlowConfig

    rows = {name: default for name, _env, default in _ENV_INT_OVERRIDES}
    for field, (default, _ge, _le) in _KNOBS.items():
        assert field in rows, f"{field} lost its _ENV_INT_OVERRIDES row"
        assert rows[field] == HydraFlowConfig.model_fields[field].default == default
