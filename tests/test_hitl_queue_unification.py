"""Guard: ONE HITL-escalation queue, ONE home per trust-fleet label (#11145/#11139).

The 2026-08-14 idle run exposed two divergent HITL queues: config-sourced
writers filed `hydraflow-hitl-escalation` while most caretakers and BOTH
pollers used the bare `hitl-escalation` — escalations on the prefixed queue
were invisible to auto-agent pre-flight and detector calibration. The merge
ruling: the bare literal is the queue root (it matches every live escalation
issue and both readers); the config default follows reality.
"""

from __future__ import annotations

import re
from pathlib import Path

from config import HydraFlowConfig
from trust_fleet_anomaly_detectors import (
    HITL_QUEUE_LABEL,
    TRUST_LOOP_ANOMALY_LABEL,
)

_SRC = Path(__file__).parent.parent / "src"


def test_config_defaults_follow_the_merged_queue() -> None:
    cfg = HydraFlowConfig()
    assert cfg.hitl_escalation_label == [HITL_QUEUE_LABEL]
    assert HITL_QUEUE_LABEL in cfg.research_escalation_labels


def test_prefixed_queue_label_is_extinct_in_src() -> None:
    # The second queue must never come back: no source file may re-introduce
    # the prefixed literal (issues carrying it would be invisible to both
    # pollers).
    offenders = [
        str(p.relative_to(_SRC))
        for p in _SRC.rglob("*.py")
        if '"hydraflow-hitl-escalation"' in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"{offenders} re-introduce the prefixed HITL-escalation label — the "
        "queues were merged onto the bare root (#11145); use "
        "config.hitl_escalation_label or HITL_QUEUE_LABEL."
    )


def test_anomaly_label_has_one_home() -> None:
    # #11139: consumers import TRUST_LOOP_ANOMALY_LABEL; a re-literaled copy
    # outside the canonical home (+ the loop's docstrings) is drift that
    # silently blanks a reader on rename. Docstrings/comments excluded by
    # matching only quoted literals.
    canonical = _SRC / "trust_fleet_anomaly_detectors.py"
    offenders = []
    for p in _SRC.rglob("*.py"):
        if p == canonical:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(rf"[\"']{re.escape(TRUST_LOOP_ANOMALY_LABEL)}[\"']", line):
                offenders.append(f"{p.relative_to(_SRC)}:{i}")
    assert offenders == [], (
        f"{offenders} re-literal the trust-loop-anomaly label — import "
        "TRUST_LOOP_ANOMALY_LABEL from trust_fleet_anomaly_detectors (#11139)."
    )
