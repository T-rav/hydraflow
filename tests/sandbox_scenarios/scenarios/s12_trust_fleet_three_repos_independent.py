"""s12 — 3 repos in registry, each with 1 issue; all process independently."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s12_trust_fleet_three_repos_independent"
DESCRIPTION = "Multi-repo fleet: 3 repos process independently."


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
    def _merged(payload: dict, n: int) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or item.get("issue_number") != n:
                continue
            outcome = item.get("outcome") or {}
            if isinstance(outcome, dict) and outcome.get("outcome") == "merged":
                return True
        return False

    for n in (1, 2, 3):
        await api.wait_until(
            "/api/issues/history?limit=500",
            lambda p, _n=n: _merged(p, _n),
            timeout=180.0,
        )

    def _all_repos_registered(payload: dict) -> bool:
        repos = payload.get("repos") if isinstance(payload, dict) else None
        if not isinstance(repos, list):
            return False
        slugs = {
            item.get("repo")
            for item in repos
            if isinstance(item, dict) and isinstance(item.get("repo"), str)
        }
        return {"acme/repo-a", "acme/repo-b", "acme/repo-c"} <= slugs

    await api.wait_until("/api/repos", _all_repos_registered, timeout=30.0)
