"""Regression pin for the split-HITL-queue defect (#11145/#11146/#11139).

Before the fix, config-sourced writers (`hitl_escalation_label` default
`["hydraflow-hitl-escalation"]`) filed onto a queue NEITHER poller read —
both auto-agent pre-flight and detector calibration list the bare
`hitl-escalation` label — so those escalations sat permanently invisible.
The 2026-08-14 idle run surfaced the split. The merge ruling: the bare
literal is the queue root; config defaults follow reality; the trust-fleet
labels live in ONE canonical home (`trust_fleet_anomaly_detectors`).

Structural one-home/extinction guards live in
`tests/test_hitl_queue_unification.py`; this pin locks the user-visible
contract — what a default-config writer files is what the pollers read.
"""

from __future__ import annotations

from config import HydraFlowConfig
from trust_fleet_anomaly_detectors import HITL_QUEUE_LABEL


def test_default_config_writers_file_onto_the_polled_queue() -> None:
    cfg = HydraFlowConfig()
    assert HITL_QUEUE_LABEL == "hitl-escalation"
    assert cfg.hitl_escalation_label == [HITL_QUEUE_LABEL]
    assert HITL_QUEUE_LABEL in cfg.research_escalation_labels
