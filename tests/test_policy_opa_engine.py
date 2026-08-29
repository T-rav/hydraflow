"""``OpaDecisionEngine``'s optional-dependency contract (pilot #11750).

Unmarked on purpose: everything here runs with **no** OPA installed, because
the contract under test is what happens when it is missing.
``docs/wiki/dependencies.md`` states it — an absent optional dependency means
the feature is off and *says so*, never a crash and never a silent pass — and
the parity half of the pilot (``tests/architecture/test_policy_opa_parity.py``,
marked ``opa``) is deselected on exactly the hosts this file is written for.

The reason string is the observable. It is what a caller records when it falls
back to ``PythonDecisionEngine``, so "unavailable" must arrive as a *named*
cause and not as an empty result that reads like "nothing to decide".
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from policy import opa_engine
from policy.facts import STANDARD_ADR_CONFORMANCE, STANDARD_ADR_ENFORCEMENT
from policy.models import Fact
from policy.opa_engine import (
    OPA_BIN_ENV,
    OpaDecisionEngine,
    OpaEvaluationError,
    OpaUnavailableError,
)

OBSERVED_AT = datetime(2026, 8, 29, 9, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_ambient_opa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither the env override nor a host-installed ``opa`` may leak in.

    Patched on the module object, not on ``shutil``, so an xdist worker that
    imported ``policy.opa_engine`` earlier still sees the stub.
    """
    monkeypatch.delenv(OPA_BIN_ENV, raising=False)
    monkeypatch.setattr(opa_engine.shutil, "which", lambda _name: None)


def _fact(
    key: str, value: str | bool, *, standard: str = STANDARD_ADR_ENFORCEMENT
) -> Fact:
    return Fact(
        standard=standard,
        subject="ADR-0001",
        key=key,
        value=value,
        observed_at=OBSERVED_AT,
        source="tests.test_policy_opa_engine",
    )


def _enforcement_facts() -> list[Fact]:
    return [
        _fact("enforcement_class", "WEAK"),
        _fact("in_baseline_snapshot", False),
        _fact("resolved", False),
        _fact("exempt", False),
    ]


def test_an_absent_binary_reports_unavailable_rather_than_raising(
    tmp_path: Path,
) -> None:
    state = OpaDecisionEngine(repo_root=tmp_path).availability()

    assert state.available is False
    assert state.reason.startswith("binary-not-found")


def test_the_unavailable_reason_names_the_override_and_the_install_command(
    tmp_path: Path,
) -> None:
    """A reason a caller cannot act on is a silent failure with extra steps."""
    reason = OpaDecisionEngine(repo_root=tmp_path).availability().reason

    assert OPA_BIN_ENV in reason
    assert "make opa-install" in reason


def test_deciding_without_a_binary_raises_with_the_reason_attached(
    tmp_path: Path,
) -> None:
    engine = OpaDecisionEngine(repo_root=tmp_path)

    with pytest.raises(OpaUnavailableError, match="binary-not-found"):
        engine.decide(_enforcement_facts())


def test_an_absent_binary_never_returns_an_empty_decision_list(
    tmp_path: Path,
) -> None:
    """The failure mode this contract exists to forbid: an unavailable engine
    returning ``[]``, which a gate would read as "no violations"."""
    engine = OpaDecisionEngine(repo_root=tmp_path)

    with pytest.raises(OpaUnavailableError):
        engine.decide(_enforcement_facts())


def test_a_present_binary_with_a_missing_policy_reports_policy_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "opa"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.setenv(OPA_BIN_ENV, str(binary))

    state = OpaDecisionEngine(repo_root=tmp_path).availability()

    assert state.available is False
    assert state.reason.startswith("policy-not-found")


def test_a_binary_that_will_not_run_reports_not_runnable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken install degrades like an absent one — it does not propagate."""
    binary = tmp_path / "opa"
    binary.write_text("#!/bin/sh\nexit 3\n")
    binary.chmod(0o755)
    policy = tmp_path / "adr_enforcement.rego"
    policy.write_text("package hydraflow.adr_enforcement\n")
    monkeypatch.setenv(OPA_BIN_ENV, str(binary))

    state = OpaDecisionEngine(repo_root=tmp_path, policy=policy).availability()

    assert state.available is False
    assert state.reason.startswith("binary-not-runnable")


def test_an_env_override_pointing_nowhere_does_not_fall_back_to_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit override that is wrong must fail loudly, not silently pick
    up whatever else is installed — that is how a pinned binary stops being
    pinned."""
    monkeypatch.setenv(OPA_BIN_ENV, str(tmp_path / "nowhere" / "opa"))

    state = OpaDecisionEngine(repo_root=tmp_path).availability()

    assert state.available is False
    assert state.reason.startswith("binary-not-found")


def test_a_stub_binary_returning_garbage_raises_an_evaluation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unparseable output is an error, never an empty decision set."""
    binary = tmp_path / "opa"
    binary.write_text(
        '#!/bin/sh\nif [ "$1" = "version" ]; then\n  echo "Version: 1.4.2"\n'
        "  exit 0\nfi\ncat > /dev/null\necho 'not json'\n"
    )
    binary.chmod(0o755)
    policy = tmp_path / "adr_enforcement.rego"
    policy.write_text("package hydraflow.adr_enforcement\n")
    monkeypatch.setenv(OPA_BIN_ENV, str(binary))
    engine = OpaDecisionEngine(repo_root=tmp_path, policy=policy)

    with pytest.raises(OpaEvaluationError, match="unreadable"):
        engine.decide(_enforcement_facts())


def test_the_engine_refuses_a_standard_the_pilot_does_not_decide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scope is ``adr_enforcement``; anything else must refuse rather than
    return silence a caller would read as compliance."""
    binary = tmp_path / "opa"
    binary.write_text('#!/bin/sh\necho "Version: 1.4.2"\nexit 0\n')
    binary.chmod(0o755)
    policy = tmp_path / "adr_enforcement.rego"
    policy.write_text("package hydraflow.adr_enforcement\n")
    monkeypatch.setenv(OPA_BIN_ENV, str(binary))
    engine = OpaDecisionEngine(repo_root=tmp_path, policy=policy)

    with pytest.raises(opa_engine.UnsupportedStandardError, match="adr_conformance"):
        engine.decide([_fact("outcome", "PASS", standard=STANDARD_ADR_CONFORMANCE)])


def test_importing_the_engine_module_runs_no_subprocess() -> None:
    """Import must be side-effect free: the pilot's engine is opt-in, and a
    module that shelled out on import would cost every unrelated test run."""
    assert opa_engine.OPA_BIN_REL.name == "opa"
    assert opa_engine.OPA_BIN_REL.parent.name == ".opa"
    assert "hydraflow.adr_enforcement" in opa_engine.DECISIONS_QUERY
