"""Regression for #9639: PrinciplesAuditLoop must use the LLM watchdog timeout.

PrinciplesAuditLoop has no LONG_LLM_CYCLE = True (cannot modify the protected
file), but runs ``make audit-json`` once per repo per cycle. Multi-repo
deployments can push a single cycle past the 2-hour default watchdog, causing
tick_error_ratio = 1.0 and a TrustFleetSanityLoop escalation.

Fix: service_registry.py injects a ``timeout_cb`` returning
``loop_watchdog_llm_seconds`` (4 h) via a per-loop LoopDeps instance, giving
the loop the LLM bound without touching the protected source file.
"""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


def test_principles_audit_loop_has_no_long_llm_cycle() -> None:
    """Guard: if LONG_LLM_CYCLE is ever added to the protected file, the
    service_registry workaround can be removed — but until then this test
    confirms the workaround is necessary."""
    text = (SRC / "principles_audit_loop.py").read_text()
    assert "LONG_LLM_CYCLE" not in text, (
        "PrinciplesAuditLoop now declares LONG_LLM_CYCLE. "
        "The service_registry.py timeout_cb workaround (#9639) can be removed "
        "in favour of the class-level flag — update both sides together."
    )


def test_service_registry_creates_principles_audit_deps() -> None:
    """service_registry.py must construct a dedicated LoopDeps for PrinciplesAuditLoop."""
    text = (SRC / "service_registry.py").read_text()
    assert "_principles_audit_deps" in text, (
        "service_registry.py no longer creates _principles_audit_deps. "
        "PrinciplesAuditLoop would fall back to loop_deps with no timeout_cb, "
        "getting only the 2-hour default watchdog and failing multi-repo cycles (#9639)."
    )


def test_service_registry_injects_llm_timeout_for_principles_audit() -> None:
    """The per-loop LoopDeps must wire timeout_cb to loop_watchdog_llm_seconds."""
    text = (SRC / "service_registry.py").read_text()
    assert "loop_watchdog_llm_seconds" in text and "timeout_cb" in text, (
        "service_registry.py is missing the timeout_cb → loop_watchdog_llm_seconds "
        "injection for PrinciplesAuditLoop (#9639). Without it the loop gets the "
        "2-hour default watchdog and will timeout on multi-repo audit cycles."
    )


def test_principles_audit_loop_uses_custom_deps() -> None:
    """PrinciplesAuditLoop must be constructed with _principles_audit_deps, not loop_deps."""
    text = (SRC / "service_registry.py").read_text()
    idx = text.find("PrinciplesAuditLoop(")
    assert idx != -1, (
        "PrinciplesAuditLoop construction not found in service_registry.py"
    )
    call_block = text[idx : idx + 300]
    assert "_principles_audit_deps" in call_block, (
        "PrinciplesAuditLoop is not using _principles_audit_deps in service_registry.py. "
        "It would inherit the default LoopDeps with no timeout_cb, allowing the 2-hour "
        "watchdog to fire on multi-repo audit cycles (#9639)."
    )
