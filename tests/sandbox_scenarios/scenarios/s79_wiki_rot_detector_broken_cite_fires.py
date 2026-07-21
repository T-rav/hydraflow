"""s79 — WikiRotDetectorLoop actively files a finding for a seeded broken cite.

Closes the read-side gap #10133 PIECE 2 left open: ``MockWorldSeed`` had no
way to express a repo-wiki entry at all, so every wiki_rot_detector scenario
had to hand-mock the ``wiki_store`` port (see
``tests/scenarios/test_wiki_rot_detector_scenario.py``) — the seed-driven
active-trigger path was untested end-to-end in either loader. The new
``repo_wiki_fixtures`` seed field is routed through a REAL
``RepoWikiStore.ingest`` call (``mockworld.sandbox_main.
materialize_wiki_fixtures``), which is what guarantees the fixture lands in
the STRUCTURED ``WikiEntry`` shape ``WikiRotDetectorLoop`` consumes since
issue #9936 (``source_type``/``source_issue``/``fixed_in_pr``/``code_refs``
as modeled fields, not a raw markdown blob the loop would fall back to
whole-file regex parsing for).

The fixture is ingested under a MANAGED repo slug (not the sandbox's own —
``config.repo`` is EMPTY in the air-gapped image, no ``.git`` is shipped, so
``WikiRotDetectorLoop``'s ``is_self`` check can never be true there
regardless of slug — see ``MockWorldSeed.repo_wiki_fixtures``). Its
``content`` embeds a ``path.py:symbol`` cite pointing at a module that does
not exist on disk, verified via the loop's non-self ``verify_cite_grep``
path (no ``is_self`` gate) — a genuinely broken cite the loop must actually
detect and file, not just an idle scan. The entry ALSO carries
``fixed_in_pr``/``code_refs`` (the "shipped claim" shape #9598/#9936
modeled) for structural completeness, even though that pass only verifies
on the self-repo path and does not fire here.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s79_wiki_rot_detector_broken_cite_fires"
DESCRIPTION = (
    "WikiRotDetectorLoop files a hydraflow-find + wiki-rot issue for a "
    "seeded structured WikiEntry whose cite does not resolve on disk, not "
    "just a heartbeat."
)

_SLUG = "acme/wiki-fixture-repo"
_TITLE = "Sandbox fixture: broken cite"
_BROKEN_CITE = "src/wiki_rot_sandbox_fixture_module.py:wiki_rot_sandbox_fixture_symbol"


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["wiki_rot_detector"],
        cycles_to_run=2,
        repo_wiki_fixtures=[
            {
                "repo_slug": _SLUG,
                "title": _TITLE,
                "content": (
                    "Claims a fix shipped in #9999 via "
                    f"`{_BROKEN_CITE}` — that module does not exist on "
                    "disk, so the loop's cite-verification pass reliably "
                    "reports this entry's cite broken."
                ),
                "source_type": "manual",
                "source_issue": 9999,
                "fixed_in_pr": "#9999",
                "code_refs": [_BROKEN_CITE],
            }
        ],
    )


async def assert_outcome(api, page) -> None:
    """A wiki_rot_detector cycle files a finding for the seeded broken cite."""

    def _fired(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "wiki_rot_detector"
            and (e.get("data", {}).get("details") or {}).get("issues_filed", 0) >= 1
            for e in events
        )

    events_payload = await api.wait_until("/api/events", _fired, timeout=90.0)

    wiki_rot_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "wiki_rot_detector"
    ]
    assert any(
        (e.get("data", {}).get("details") or {}).get("issues_filed", 0) >= 1
        for e in wiki_rot_events
    ), (
        "Expected wiki_rot_detector to file a finding for the seeded "
        f"broken cite; worker events: {wiki_rot_events!r}"
    )
