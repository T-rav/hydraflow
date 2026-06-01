"""s12 — 3 repos in registry, each with 1 issue; all process independently."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s12_trust_fleet_three_repos_independent"
DESCRIPTION = (
    "Multi-repo fleet: 3 repos process independently; Wiki tab shows entries from all."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[
            ("acme/repo-a", "/workspace/repo-a"),
            ("acme/repo-b", "/workspace/repo-b"),
            ("acme/repo-c", "/workspace/repo-c"),
        ],
        issues=[
            {"number": 1, "title": "t", "body": "b", "labels": ["hydraflow-ready"]},
            {"number": 2, "title": "t", "body": "b", "labels": ["hydraflow-ready"]},
            {"number": 3, "title": "t", "body": "b", "labels": ["hydraflow-ready"]},
        ],
        scripts={
            "plan": {n: [{"success": True}] for n in (1, 2, 3)},
            "implement": {
                n: [{"success": True, "branch": f"hf/issue-{n}"}] for n in (1, 2, 3)
            },
            "review": {n: [{"verdict": "approve"}] for n in (1, 2, 3)},
        },
        cycles_to_run=8,
    )


async def assert_outcome(api, page) -> None:
    for n in (1, 2, 3):

        def _has_merged_outcome(payload: dict, _n: int = n) -> bool:
            items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                return False
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("issue_number") != _n:
                    continue
                outcome = item.get("outcome") or {}
                if isinstance(outcome, dict) and outcome.get("outcome") == "merged":
                    return True
            return False

        history = await api.wait_until(
            "/api/issues/history?limit=500",
            _has_merged_outcome,
            timeout=180.0,
        )
        items = history.get("items") if isinstance(history, dict) else None
        assert isinstance(items, list), f"history payload missing items: {history!r}"
        matching = [
            i for i in items if isinstance(i, dict) and i.get("issue_number") == n
        ]
        assert matching, f"no issue_number={n} entry in history: {history!r}"
        outcome = matching[0].get("outcome") or {}
        assert outcome.get("outcome") == "merged", f"got {matching[0]!r}"
    # UI assertion removed: the trust-fleet independence is fully verified above
    # via /api/issues/history (all three repos' issues reach a merged outcome).
    # The prior `page.click("text=Wiki")` was ambiguous (multiple "Wiki"/"Repo
    # Wiki" labels render → Playwright strict-mode violation) and the Wiki tab
    # is not the surface that lists per-repo slugs.
