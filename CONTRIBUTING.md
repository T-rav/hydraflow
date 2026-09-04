# Contributing to HydraFlow

HydraFlow is a delivery kernel that runs its own pipeline on itself. Most changes
here are made by agents under the same gates a human change passes, so the
conventions below are enforced by CI rather than by review etiquette — a change
that ignores them does not merge.

> **Project status.** Ownership and stewardship are transferring to 8th Light.
> See [Project Status](README.md#project-status) before planning substantial work.

## Before you start

Read [`CLAUDE.md`](CLAUDE.md) — it is the operating contract for this repository
and takes precedence over anything here. Then look up what you need rather than
reading everything:

| You need | Look in |
|---|---|
| Why something is built this way | [`docs/adr/`](docs/adr/README.md) — 149 decision records |
| How something behaves in practice | [`docs/wiki/`](docs/wiki/index.md) — patterns, gotchas, testing |
| Repo-wide rules | [`docs/standards/`](docs/standards/) — 10 standards |
| Live system topology | [the architecture site](https://t-rav.github.io/hydraflow/) — regenerated every PR |

Contradicting an Accepted ADR requires a new ADR superseding it, not a code
change that quietly diverges.

## The workflow

**1. Branch in a worktree.** Never commit to `main`, and never work in the main
checkout:

```bash
wt="$(scripts/hf_worktree.sh mywork fix/1234-short-description | tail -1)"
cd "$wt"
git rev-parse --abbrev-ref HEAD    # verify you are on the branch you meant
```

Use the helper rather than `git worktree add`: a bare `add` takes the directory
name verbatim, so a reused name silently lands you on a stale branch, and the
workspace collector cannot reap what it cannot find.

**2. Write the test first.** Bug fixes land with a regression test in
`tests/regressions/`. Load-bearing features ship the full pyramid — unit,
MockWorld scenario, and sandbox e2e. Skipping a layer is a procedural failure,
not a judgement call; see [`docs/standards/testing/`](docs/standards/testing/README.md).

**3. Prove the test is load-bearing.** A guard that passes for the wrong reason
is worse than no guard. Break the thing it guards and confirm the test reddens —
and confirm the mutation actually applied, because a no-op mutation reads exactly
like a caught one.

**4. Run the full suite.**

```bash
make quality
```

Not a targeted subset. `make quality` aborts at the first failing stage, so a
small failure count can mean a stage never ran — check for `[tests OK]` and
`make`'s own exit code, not just a green-looking test total.

**5. Open a PR against `staging`.**

```bash
gh pr create --base staging
```

`main` advances only through auto-promoted `rc/*` branches
([ADR-0042](docs/adr/0042-two-tier-branch-release-promotion.md)).

**6. Get fresh eyes on it.** Every PR gets a review pass before merge, not only
substantial ones. For substantial work, expect two or three iterations until a
pass finds nothing material.

## Things that will fail CI

- `git commit --no-verify` or `--no-hooks` — fix the issue instead
- A `fix(` commit with no `tests/regressions/` delta
- A parametrised guard over a module-level sequence that is not registered in
  `tests/architecture/guard_enumeration_registry.py`
- Rebaselining a shrink-only ratchet to make it green, rather than removing the
  need for the entry
- Stale generated artifacts — run `make arch-regen` and commit the result

## A note on the gates

The gates in this repository exist because each one caught something real, and
most encode a specific past failure. If one blocks you and looks wrong, read its
docstring and the issue it names before working around it: the rationale — and
usually the losing argument — is already written down.

## Reporting a vulnerability

See [`SECURITY.md`](SECURITY.md). Do not open a public issue for a security
report.
