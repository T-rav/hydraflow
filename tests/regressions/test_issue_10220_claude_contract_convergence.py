"""Regression: the claude adapter must be able to reach a clean drift tick.

Issue #10220: ``ContractRefreshLoop`` escalated "claude fake repair not
converging" after 3+ consecutive ticks of drift that never cleared. Root
causes, both fixed here:

1. ``tests/trust/contracts/claude_streams/stream_001_list_primes.jsonl`` is
   a permanent hand-authored StreamParser-corpus sample that
   ``record_claude_stream`` (which only ever sends the fixed "ping" prompt)
   can never regenerate. Diffing flagged its permanent absence from the
   recording as ``deleted_cassettes`` on *every* tick, so the claude
   adapter's fleet report was never empty and its consecutive-drift
   attempt counter (Task 18, ``ContractRefreshLoop._update_attempt_counters``)
   never reset.
2. The recorder wrote raw ``claude -p ping`` stdout verbatim: a
   host-installed plugin's ``SessionStart`` hook injected a multi-KB,
   ever-changing payload, and the live assistant response text differs on
   every call — neither of which is stable across ticks, so even without
   bug (1) a clean tick was effectively unreachable.

This test exercises the fix at the same level ``ContractRefreshLoop._do_work``
does: record (mocked/redacted) + diff the fleet, and asserts a clean tick is
achievable despite the extra committed sample and despite differing
assistant wording across two "recordings".
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from contract_diff import detect_fleet_drift
from contract_recording import CLAUDE_STREAM_FILENAME, record_claude_stream


def _record_ping(tmp_dir: Path, wording: str) -> list[Path]:
    stream = (
        '{"type": "assistant", "message": {"content": '
        f'[{{"type": "text", "text": "{wording}"}}]}}}}\n'
        f'{{"type": "result", "result": "{wording}"}}\n'
    )

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout=stream, stderr=""
        )

    with patch("contract_recording.subprocess.run", side_effect=fake_run):
        return record_claude_stream(tmp_stream_dir=tmp_dir)


def test_claude_adapter_reaches_clean_tick_despite_extra_baseline_sample_and_wording(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    committed_dir = repo_root / "tests/trust/contracts/claude_streams"
    committed_dir.mkdir(parents=True)

    # Seed the committed tree the way a prior successful refresh PR would
    # have left it: the recorder's own file already redacted, plus the
    # permanent hand-authored StreamParser-corpus sample the recorder never
    # touches.
    first_recording = _record_ping(tmp_path / "seed", wording="hello there")
    (committed_dir / CLAUDE_STREAM_FILENAME).write_bytes(
        first_recording[0].read_bytes()
    )
    (committed_dir / "stream_001_list_primes.jsonl").write_text(
        '{"type": "session", "session_id": "sess_001"}\n'
        '{"type": "result", "result": "The first three primes are 2, 3, 5."}\n',
        encoding="utf-8",
    )

    # A fresh recording with DIFFERENT live wording than what was committed.
    fresh_recording = _record_ping(
        tmp_path / "fresh", wording="a completely different reply"
    )

    fleet = detect_fleet_drift(
        {"claude": fresh_recording},
        repo_root,
        ignore_deleted_names={"claude": frozenset({"stream_001_list_primes.jsonl"})},
    )

    assert fleet.has_drift is False
    assert fleet.reports == []
