# src/auto_tighten/models.py
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

Measurement = float | dict[str, int] | list[str]


class CoverageRecord(BaseModel):
    timestamp: str
    coverage_percent: float
    commit_sha: str
    run_id: str


class FileEdit(BaseModel):
    path: str
    new_text: str


class Observation(BaseModel):
    ts: str
    ratchet_id: str
    current: Any
    baseline: Any
    direction: str  # "tighter" | "looser" | "same"


class ConfirmedTightening(BaseModel):
    ratchet_id: str
    floor: Any
    file_edits: list[FileEdit]
    dedup_key: str
    evidence: str
