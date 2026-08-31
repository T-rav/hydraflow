"""The per-tool error breakdown was structurally empty end-to-end.

`TraceCollector` never populated `tool_errors` by tool name (it only ever
wrote the literal key `"__stream__"`), so `trace_rollup.write_phase_rollup`
aggregated an always-empty dict. Nothing caught it because every test built
`TraceToolProfile(tool_errors=...)` by hand — the field was pinned at the
model level and never at the collector level.

This pins the whole chain: collector → subprocess-N.json → rollup.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tests.helpers import ConfigFactory
from trace_collector import TraceCollector  # noqa: E402
from trace_rollup import write_phase_rollup  # noqa: E402


def test_failed_tool_call_surfaces_in_the_phase_rollup(tmp_path: Path):
    config = ConfigFactory.create()
    config.data_root = tmp_path

    collector = TraceCollector(
        issue_number=7,
        phase="implement",
        source="implementer",
        subprocess_idx=0,
        run_id=1,
        config=config,
        event_bus=None,
    )
    collector.record(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Bash",
                            "input": {"command": "make quality"},
                        }
                    ]
                },
            }
        )
    )
    collector.record(
        json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t1",
                            "is_error": True,
                            "content": "make: *** [quality] Error 1",
                        }
                    ]
                },
            }
        )
    )
    collector.finalize(success=False)

    summary = write_phase_rollup(
        config=config, issue_number=7, phase="implement", run_id=1
    )

    assert summary is not None
    assert summary.tools.tool_errors == {"Bash": 1}
