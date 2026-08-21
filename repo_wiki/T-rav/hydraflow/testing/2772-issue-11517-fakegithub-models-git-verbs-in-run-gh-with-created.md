---
id: 2772
topic: testing
source_issue: 11517
source_phase: plan
created_at: 2026-08-21T09:19:56.754306+00:00
status: active
corroborations: 1
---

# FakeGitHub mirrors release tagging as explicit methods with a tags recorder

When `PRManager` gains git plumbing for releases, mirror it on `src/mockworld/fakes/fake_github.py` as **explicit methods with identical names and kwargs** — not as `git` verbs inside the generic `_run_gh` dispatcher:

- `resolve_remote_branch_sha(branch)` answers the head seeded via `set_branch_head(branch, sha | None)` (`None` = unresolvable, driving the fail-closed skip; unseeded → synthetic `sha-<branch>`), `create_tag(tag, *, ref)` records `tag -> ref` in a `tags` read-back (duplicate tag → `False`, like `git tag`), `create_release(tag, title, body)` records into `releases`.
- Wire the names onto `MockWorld._wire_targets`' PR-manager delegation list (`tests/scenarios/fakes/mock_world.py`) so harness paths hit the fake instead of an unwired `AsyncMock`.
- Every new adapter-surface method needs a cassette + dispatcher branch under `tests/trust/contracts/` (the cassette-surface parity gate forbids growing the grandfathered baseline); the dispatcher asserts the `tags`/`releases` side-effect, not just the bool.
- Scenario: `tests/scenarios/test_epic_release_tag_ref_scenario.py` asserts `world.github.tags == {"v1.0.0": <main sha>}` and that the unversioned / unresolvable cases leave `tags` empty.

**Why:** explicit methods keep the PRManager / FakeGitHub mirror checkable by name (conformance + parity gates); scenarios cannot assert ref-targeting without a recorder that keeps the `tag -> ref` pairing.
