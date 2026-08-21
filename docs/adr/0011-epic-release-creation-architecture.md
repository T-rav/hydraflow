# ADR-0011: Epic Release Creation Architecture

**Status:** Accepted
**Date:** 2026-03-01
**Enforcement:** enforced
**Enforced by:**
pytest:tests/test_epic.py
pytest:tests/test_release.py

> **Corrected 2026-08-21 (#11569).** The original text (PR #1690) described
> release creation as firing automatically from the epic-close path, gated by
> `config.release_on_epic_close`. PR #2689 removed both the gate and the call
> months before this correction, so the ADR described a trigger that did not
> exist and misdirected #11517 and #11520. The text below states the current
> truth; the original placement rationale is preserved under *Alternatives
> considered*. Nothing in this ADR means "closing an epic mints a tag" — it
> does not.

## Context

HydraFlow needs a way to mint a version tag and a GitHub Release for a
completed epic: extract a version, create a git tag on the right commit,
create the Release with a changelog, and persist release state for
crash-recovery and dashboard reporting.

**Where the primitive lives** was decided in 2026-03 and is unchanged. The
candidates were `PostMergeHandler` (runs per PR merge; no view of the parent
epic's completion), `EpicCompletionChecker` (already knows the epic title,
sub-issue list, and completion status), and `EpicManager._try_auto_close()`
(the entry point that fires when any child completes). The primitive went
into `EpicCompletionChecker` as `_create_release_for_epic()`.

**Whether anything calls it** has changed since. PR #1690 wired the primitive
into the epic-close path behind the opt-in flag `release_on_epic_close`. PR
#2689 ("Remove 8 feature flags") deleted that flag as an unused feature and
removed the call with it. Today:

- `EpicCompletionChecker._do_close_epic()` (reached via
  `EpicManager._try_auto_close()` → `close_specific_epic()`) updates the epic
  body, applies the fixed label, posts the close comment, and closes the
  issue. It does **not** call `_create_release_for_epic()`; its
  `release_url = ""` / `generated_changelog = ""` locals are inert scaffolding
  left behind by the removed call.
  `tests/test_release.py::TestEpicCompletionWithRelease::test_no_release_on_epic_close`
  pins this: closing an epic must not call `create_tag()` or
  `create_release()`.
- The dashboard **Release** action (`EpicManager.trigger_release()` →
  `_execute_release()` → `release_epic()`) merges the epic's bundled child PRs
  in order and flips `EpicState.released` (ADR-0012). It does not tag or
  create a GitHub Release.
- `_create_release_for_epic()` therefore has **no production caller**; only
  tests drive it.

#11517 (PR #11576) found that the primitive tagged the factory checkout
`HEAD` — which under ADR-0042 is `staging` or an agent branch, never the
promoted `main` — and fixed it to resolve and tag the promoted `main` SHA.
#11569 found that this ADR still described the #1690 wiring, which cost an
implementer a detour (#11517) and had the v1.0.0 cut (#11520) planning on an
automatic path that does not exist.

## Decision

1. **The release primitive lives in the epic subsystem, as
   `EpicCompletionChecker._create_release_for_epic()`.** Release-creation
   logic is not placed in `PostMergeHandler` or any other per-PR handler.
   (Unchanged from the original decision.)

2. **The primitive is not attached to any automatic trigger.** Epic close
   closes the epic and nothing else; the dashboard release action merges the
   bundle and nothing else. Neither mints a tag or a GitHub Release. This is
   the state PR #2689 left and the state `test_no_release_on_epic_close`
   enforces. The former `config.release_on_epic_close` gate no longer exists.

3. **Releases are cut manually**, by an operator, against the promoted
   `main` SHA (ADR-0042) — never against `staging`, an agent branch, or a
   worktree `HEAD`:

   ```bash
   git fetch origin main
   MAIN_SHA=$(git rev-parse origin/main)        # the promoted SHA, after the RC landed
   git tag vX.Y.Z "$MAIN_SHA"
   git push origin vX.Y.Z
   gh release create vX.Y.Z --title "Release vX.Y.Z" --notes-file CHANGELOG-vX.Y.Z.md
   ```

   The v1.0.0 cut (#11520) is the first planned use of this recipe; that
   issue owns the version bump, the CHANGELOG section, and the wiki
   `release-policy` entry.

4. **Any future automatic trigger goes through the primitive, never around
   it.** A caller that re-attaches release creation — to epic close, to the
   dashboard release action, or to a new operator action — must:
   - call `_create_release_for_epic()` rather than `create_tag()` /
     `create_release()` directly, so the tag ref, version source, changelog,
     and state persistence stay in one place;
   - take its version from `config.release_version_source` (today only
     `epic_title` is implemented; `milestone` and `manual` log a warning and
     fall back to `epic_title`);
   - tag the SHA returned by
     `PRManager.resolve_remote_branch_sha(config.main_branch)` and pass it
     explicitly as `create_tag(tag, ref=...)` — no caller tags `HEAD`;
   - ship with a MockWorld scenario proving the tag ref (as
     `tests/scenarios/test_epic_release_tag_ref_scenario.py` does for the
     primitive), and amend Decision 2 of this ADR to name the trigger.

   Which trigger to choose (epic close vs. an explicit operator action) is a
   product decision that has not been made; see *Alternatives considered* §4.

The primitive's call chain (post-#11517):

```
<no production caller today — see Decision 2; tests drive it directly>
  └─ EpicCompletionChecker._create_release_for_epic(epic_number, epic_title, sub_issues)
       ├─ extract_version_from_title(epic_title)                  # "" → return, no side effects
       ├─ _generate_epic_changelog(epic_number, sub_issues, version)
       ├─ PRManager.resolve_remote_branch_sha(config.main_branch)  # None → skip, fail-closed
       ├─ PRManager.create_tag(tag, ref=<promoted main sha>)       # False → skip release
       ├─ PRManager.create_release(tag, "Release <tag>", changelog)
       └─ StateTracker.upsert_release(Release(...))
```

Key implementation details:

1. **Tag and release are separate operations.** `PRManager.create_tag()`
   creates and pushes a git tag; `PRManager.create_release()` creates the
   GitHub Release referencing that tag. This two-step approach allows
   partial-failure handling (tag created but release failed).

2. **Version extraction from epic title.** The `extract_version_from_title()`
   utility parses a semver-like version from the epic's title. If no version
   is found, the primitive returns without side effects. The
   `release_version_source` config field exists for alternative sources, but
   only `epic_title` is implemented.

3. **Release state persisted in `StateData.releases`.** The `Release` model is
   stored in a `dict[str, Release]` keyed by epic number (as string). This
   enables crash-recovery (re-check release existence before retrying) and
   dashboard reporting.

4. **Tags target the promoted `main` SHA (#11517).** The primitive fetches and
   resolves `origin/<main_branch>` at release time via
   `PRManager.resolve_remote_branch_sha()` and passes the result as
   `create_tag(tag, ref=...)`. `ref` is keyword-only with no default, so no
   caller can fall back to `HEAD` by omission; an unresolvable `origin/main`
   skips the release fail-closed.

5. **Dry-run support.** `resolve_remote_branch_sha()`, `create_tag()` and
   `create_release()` in `PRManager` respect the global `dry_run` flag,
   logging intent without executing (`resolve_remote_branch_sha()` returns
   the symbolic `origin/<main_branch>` so dry-run logs still name the target).

## Consequences

**Positive:**
- A release cannot be minted by accident: nothing fires automatically, and
  the primitive refuses to tag anything but the promoted `main` SHA.
- `PostMergeHandler` remains focused on single-PR lifecycle; epic-level
  concerns stay in the epic subsystem.
- State persistence enables idempotent retries and dashboard visibility.
- The two-step tag/release flow allows fine-grained error handling and logging.
- Tags target the promoted `main` SHA (`origin/<main_branch>` per ADR-0042,
  fetched and resolved at release time via
  `PRManager.resolve_remote_branch_sha`), never the factory checkout `HEAD` —
  which under ADR-0042 is `staging` or an agent branch. `create_tag`'s `ref`
  is keyword-only with no default, and an unresolvable `origin/main` skips the
  release fail-closed (#11517).

**Trade-offs:**
- Every release is an operator action until a trigger is chosen and wired.
  An epic titled `[Epic] v1.2.0 …` closing does **not** produce a `v1.2.0`
  tag, whatever its title says.
- The primitive is exercised only by tests, so regressions in it surface
  through `tests/test_release.py` and the tag-ref scenario, not from live
  use. The `release_url` / `generated_changelog` locals in `_do_close_epic()`
  are dead scaffolding (cleanup candidate noted in #11569).
- When a trigger is wired, release creation will still depend on a version
  being parseable from the epic title; epics without a version string
  produce no release (by design, but could surprise users).
- Two separate `gh` calls (tag + release) instead of a single atomic
  operation means a tag could exist without a corresponding release on
  transient failure.

## Alternatives considered

1. **Hook into `PostMergeHandler` directly.**
   Rejected: would require each merge handler to track epic-level state and
   detect "last child" completion — duplicating logic already in
   `EpicCompletionChecker`.

2. **Use `gh release create --target main` for atomic tag+release.**
   Not adopted: keeping tag creation separate (`git tag` + `git push`) gives
   explicit control over the tag ref and clearer error attribution. The
   `gh release create` command can still reference an existing tag.

3. **Dedicated `ReleaseManager` service.**
   Not adopted at this stage: the release logic is compact enough to live in
   `EpicCompletionChecker`. A separate service can be extracted if release
   workflows grow more complex (e.g., artifact uploads, multi-repo
   coordination).

4. **Re-wire the primitive to epic close as part of the #11569 correction.**
   Not done: PR #2689 removed that wiring deliberately, and re-attaching it
   is a product decision about *when* HydraFlow releases (on epic close, on
   the dashboard release action, or only on explicit operator request — cf.
   #11520) rather than a documentation fix. Until that decision is recorded
   here, Decision 2 stands: no automatic trigger.

## Related

- Source memory: Issue #1682 — *[Memory] Epic release creation architecture*
- `src/epic.py:EpicManager._try_auto_close`, `src/epic.py:EpicCompletionChecker._create_release_for_epic` — the epic-close entry point (which has **not** called the release primitive since PR #2689) and the release primitive itself
- `src/pr_manager.py:PRManager.resolve_remote_branch_sha` — resolves the promoted `main` SHA the tag targets (#11517)
- `src/pr_manager.py:PRManager.create_tag`, `src/pr_manager.py:PRManager.create_release` — the two-step tag-then-release operations
- `src/models.py:Release`, `src/models.py:StateData.releases` — the release model and where release state is persisted
- PR #1690 — *feat: create GitHub Release with changelog when epic closes* (original wiring, since removed)
- PR #2689 — *Remove 8 feature flags* (deleted `release_on_epic_close` and the epic-close call)
- #11517 / PR #11576 — tag the promoted `main` SHA, never the factory checkout `HEAD`
- #11520 — v1.0.0 cut; first planned use of the manual recipe in Decision 3
- #11569 — this correction
- ADR-0012 (Epic Merge Coordination Architecture) — owns the dashboard release (bundle-merge) action
- ADR-0042 (Two-tier branch model with automated release-candidate promotion) — defines the promoted `main` the tag targets

> **Symbol-granular citations (per #9176).** These files are extremely
> high-churn shared modules; citing them at bare *file* granularity made
> the `adr_touchpoint_auditor` flag ADR-0011 as drifted on *any* change to
> them, even changes unrelated to epic-release creation. The citations
> above name the specific symbols this ADR is responsible for, so drift
> only fires when one of those symbols actually changes.
