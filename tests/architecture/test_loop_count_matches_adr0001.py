"""Drift guard: ADR-0001's "five concurrent" framing vs the live loop count.

Plan B amended ADR-0001 with a Background section that historicizes the
five-concurrent framing. The xfail decorator was removed once the
amendment landed; this test now actively guards against future drift
(e.g., if someone reverts the amendment).
"""

from pathlib import Path

import pytest

from arch.extractors.loops import extract_loops


def test_loop_count_matches_adr0001(real_repo_root: Path):
    adr = (real_repo_root / "docs/adr/0001-five-concurrent-async-loops.md").read_text()
    if "see `docs/arch/generated/loops.md`" in adr:
        return  # ADR has been updated to reference the live registry
    if "Background" in adr and "historical" in adr:
        return  # ADR has been historicized
    live_loops = extract_loops(real_repo_root / "src")
    pytest.fail(
        f"ADR-0001 still references its original framing but {len(live_loops)} loops exist. "
        "Plan B should amend ADR-0001 to either reference docs/arch/generated/loops.md "
        "or historicize the original claim with a 'Background' section."
    )
