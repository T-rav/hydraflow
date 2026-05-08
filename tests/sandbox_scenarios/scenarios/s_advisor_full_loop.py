"""s_advisor_full_loop — advisor pattern end-to-end (Tier-2).

T23 of the advisor-pattern feature. Tier-2 parity for
``tests/scenarios/test_pr_review_advisor_happy_path.py`` per ADR-0052
rule 3 (every sandbox scenario has a Tier-1 parity test).

End-to-end flow when the supporting wiring lands:

1. seed() registers issue 7 ("Add advisor wiring") with hydraflow-ready.
2. plan/implement/review scripts drive the in-process parity test
   (tests/scenarios/test_sandbox_parity.py) past "queued" — Tier-1
   passes today with no advisor wiring needed.
3. Tier-2 (sandbox) flow expects the executor to APPROVE and the
   PostVerifyAdvisor to APPROVE, ending with PR merged + the
   ``review_advisor`` worker card visible on the dashboard.

Why ``assert_outcome`` is skipped today
---------------------------------------

Two pieces of sandbox-side wiring are not yet in place:

a. ``src/mockworld/sandbox_main.py`` does not set
   ``reviewers._mockworld_fake_llm = fake_llm`` on the override
   reviewer. Without that sentinel, ``ReviewPhase._build_post_verify_runner``
   falls through to ``ReviewRunner._execute`` and tries to spawn a
   real Claude subprocess — which fails under the air-gapped sandbox
   network.

b. The seed-script loader in ``sandbox_main.main()``
   (``getattr(fake_llm, f"script_{phase}")(issue_number, results)``)
   is hard-wired to the 2-arg ``script_<phase>(issue_number, results)``
   shape. ``script_advisor`` requires the 3-arg form
   ``(issue_number, role, results)``, so seeded advisor scripts have
   nowhere to land in the Tier-2 boot path.

Both are tracked separately from T23 (this task is the Tier-2
*scenario*, not the Tier-2 advisor *infrastructure*). Activate this
scenario's ``assert_outcome`` body once both gaps close.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mockworld.seed import MockWorldSeed

NAME = "s_advisor_full_loop"
DESCRIPTION = (
    "Advisor pattern end-to-end: executor APPROVE + post-verify advisor APPROVE → "
    "PR merged, review_advisor worker card visible. SKIPPED until sandbox advisor "
    "wiring lands (see module docstring)."
)


def seed() -> MockWorldSeed:
    """Drive a single issue through the full pipeline.

    The plan/implement/review scripts are sufficient for the Tier-1
    parity test (``test_sandbox_parity.py``) to advance the issue
    past ``queued`` without touching the advisor seam at all. When
    the sandbox-side advisor wiring lands, an ``advisor`` entry in
    ``scripts`` will become loadable too.
    """
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": 7,
                "title": "Add advisor wiring",
                "body": "Wire PostVerifyAdvisor into ReviewPhase",
                "labels": ["hydraflow-ready"],
            },
        ],
        scripts={
            "plan": {7: [{"success": True, "task_count": 1}]},
            "implement": {7: [{"success": True, "branch": "hf/issue-7"}]},
            "review": {7: [{"verdict": "approve", "comments": []}]},
        },
        cycles_to_run=4,
    )


# Scripted advisor verdict the assert_outcome flow will use once the
# sandbox-side wiring lands. Pinned at module scope so the shape stays
# next to the seed and is reviewable today.
_ADVISOR_POST_VERIFY_APPROVE: str = json.dumps(
    {
        "verdict": "APPROVE",
        "reasoning": "Executor verdict matches diff intent.",
        "disagreements": [],
        "suggested_fix_direction": None,
    }
)


async def assert_outcome(api: Any, page: Any) -> None:
    """End-to-end assertions; skipped pending sandbox advisor wiring.

    When the wiring lands (see module docstring), this body will:

    1. Poll ``/api/issues/history`` until issue 7's outcome is ``merged``.
    2. Open the dashboard, confirm the Outcomes tab renders the merged
       row for issue 7.
    3. Assert ``[data-testid='worker-card-review_advisor']`` is visible
       on the System panel — proves the BACKGROUND_WORKERS registration
       (src/ui/src/constants.js) is rendered by the running stack.
    4. Confirm ``advisor_call_count_for("post_verify") == 1`` via an
       FakeLLM-introspection API once one is exposed (or via the
       per-PR ``review_logs/{pr}/advisor_session.jsonl`` artifact the
       PostVerifyAdvisor writes per spec §6).
    """
    pytest.skip(
        "Pending sandbox-side advisor wiring: "
        "(a) reviewers._mockworld_fake_llm sentinel in sandbox_main.py, "
        "(b) script_advisor (3-arg form) support in the seed-script loader. "
        "Tier-1 parity at tests/scenarios/test_pr_review_advisor_happy_path.py."
    )
    # Reference the scripted payload so static analysis doesn't flag it
    # as dead. This is the verdict the activated assert_outcome will
    # script via FakeLLM.script_advisor(7, "post_verify", [...]).
    _ = _ADVISOR_POST_VERIFY_APPROVE
    _ = api
    _ = page
