"""Factory validation: every lightweight LLM spawn detects credit exhaustion (WS-2.2).

The lightweight (``run_simple``) spawn path NEVER raises ``CreditExhaustedError``
— credit-out arrives as ``rc != 0`` TEXT. So a module on that path that does not
detect credit (via the ``run_lightweight_agent`` helper, which scans + raises, or
its own ``raise_if_credit_exhausted`` / ``is_credit_exhaustion`` scan) misclassifies
a billing signal as a generic failure and burns attempt budget — the
``run-simple-agent-spawn-no-credit-detection`` finding from the dark-factory audit.

This ratchet enforces the CLAUDE.md subprocess-runner contract on the lightweight
path. ``_GRANDFATHERED`` must stay EMPTY — the audited gap is fully closed.

Ref: ADR-0086, ``docs/wiki/dark-factory.md`` §6, ``src/exception_classify.py``.
"""

from __future__ import annotations

from tests._spawn_audit import iter_module_facts

# A module is on the lightweight LLM spawn path if it builds a lightweight
# command directly OR routes through the run_lightweight_agent helper.
_LIGHTWEIGHT_MARKERS = frozenset({"build_lightweight_command", "run_lightweight_agent"})

# Calls that satisfy "this module detects credit exhaustion on the run_simple path".
_CREDIT_DETECTORS = frozenset(
    {
        "run_lightweight_agent",  # helper scans stdout/stderr + raises CreditExhaustedError
        "raise_if_credit_exhausted",  # shared scan helper
        "is_credit_exhaustion",  # manual scan
    }
)

# runner_utils DEFINES the helper + the scan — the contract home, not a bypass.
_CONTRACT_HOME = frozenset({"runner_utils.py"})

# MUST stay empty: every lightweight LLM spawner detects credit exhaustion.
_GRANDFATHERED: frozenset[str] = frozenset()


def _lightweight_modules_missing_credit_detection() -> set[str]:
    """Return lightweight-path modules that never detect credit exhaustion."""
    offenders: set[str] = set()
    for facts in iter_module_facts():
        if facts.name in _CONTRACT_HOME:
            continue
        if (facts.calls & _LIGHTWEIGHT_MARKERS) and not (
            facts.calls & _CREDIT_DETECTORS
        ):
            offenders.add(facts.name)
    return offenders


def test_every_lightweight_spawn_detects_credit() -> None:
    offenders = sorted(_lightweight_modules_missing_credit_detection() - _GRANDFATHERED)
    assert not offenders, (
        "These modules spawn an LLM via the lightweight (run_simple) path but never "
        f"detect credit exhaustion: {offenders}. run_simple surfaces credit-out as "
        "rc!=0 TEXT (it never raises), so reraise_on_credit_or_bug alone is a no-op — "
        "add a raise_if_credit_exhausted() scan or route through "
        "runner_utils.run_lightweight_agent."
    )


def test_credit_grandfather_list_is_empty() -> None:
    assert frozenset() == _GRANDFATHERED, (
        "_GRANDFATHERED must stay empty — every lightweight LLM spawner detects "
        f"credit. Found exemptions: {sorted(_GRANDFATHERED)}"
    )


def test_lightweight_helper_keeps_credit_contract() -> None:
    """Guard against gutting: run_lightweight_agent must keep its credit detection."""
    facts = {f.name: f for f in iter_module_facts()}
    runner_utils = facts["runner_utils.py"]
    assert {"raise_if_credit_exhausted", "reraise_on_credit_or_bug"} <= (
        runner_utils.calls
    ), (
        "run_lightweight_agent must keep credit detection (raise_if_credit_exhausted "
        "scan + reraise_on_credit_or_bug); removing it silently reopens the gap for "
        "every caller that relies on the helper."
    )


def test_central_subprocess_runner_reraises_credit() -> None:
    """The central subprocess runner must propagate credit/auth, not swallow it."""
    facts = {f.name: f for f in iter_module_facts()}
    base = facts.get("base_subprocess_runner.py")
    assert base is not None, "base_subprocess_runner.py not found in src/"
    assert "reraise_on_credit_or_bug" in base.calls, (
        "BaseSubprocessRunner.run must call reraise_on_credit_or_bug so credit/auth "
        "signals propagate instead of collapsing to crashed=True."
    )
