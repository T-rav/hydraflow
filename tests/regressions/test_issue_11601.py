"""Regression pins for the two CI-only defects in #11601's own PR (#11621).

Both were *action-load* failures: the composite action
`.github/actions/build-agent-image` never ran a single step, so every sandbox
lane died at "Build agent image" with the rest of the job skipped. Neither is
catchable locally — `actionlint` does not evaluate action-manifest
descriptions, and `make quality` does not load action manifests at all. CI
found both, one per push.

1. **An expression inside a `description:` string is still evaluated.**
   The `token` input documented its own usage by quoting the GITHUB_TOKEN
   secret expression in backticks. GitHub template-evaluates EVERY expression
   in a manifest — prose included — and the `secrets` context does not exist
   in composite-action metadata, so the action failed to load with
   "Unrecognized named-value: 'secrets'".

2. **The obvious fix reintroduced the same class.** The replacement prose
   explained the rule by writing empty braces as a placeholder. Empty braces
   are also an expression, and an invalid one: "An expression was expected".

The pin is therefore on the CLASS, not on either literal: no expression
braces anywhere in the manifest's prose. `test_sandbox_ci_cache.py` carries
the positive wiring assertions; this file exists so the two shapes that
actually broke can never come back.

Also pins the third #11621 CI finding, a CodeQL high
(`actions/cache-poisoning/poisonable-step`): `docker/setup-buildx-action`
defaults to storing the buildx binary in the GitHub Actions cache, which is a
cache WRITE in a job that checks out an operator-chosen ref with
default-branch privilege.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_PATH = REPO_ROOT / ".github" / "actions" / "build-agent-image" / "action.yml"
DISPATCH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "sandbox-dispatch.yml"

#: Any expression, including the empty `${{ }}` that produced defect 2. The
#: inner quantifier is deliberately `*` and not `+`: `+` is exactly what let
#: the empty-brace regression through the first version of this guard.
_EXPRESSION_RE = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))


def _description_strings(manifest: dict) -> list[tuple[str, str]]:
    """(where, text) for every description the manifest declares."""
    found: list[tuple[str, str]] = []
    if isinstance(manifest.get("description"), str):
        found.append(("action.description", manifest["description"]))
    for section in ("inputs", "outputs"):
        for name, spec in (manifest.get(section) or {}).items():
            if isinstance(spec, dict) and isinstance(spec.get("description"), str):
                found.append((f"{section}.{name}.description", spec["description"]))
    return found


def test_no_description_contains_an_expression(manifest: dict) -> None:
    # Defects 1 and 2, pinned as one class.
    offenders = [
        f"{where}: {text.strip()[:80]}"
        for where, text in _description_strings(manifest)
        if "${{" in text
    ]
    assert not offenders, (
        "action-manifest descriptions are template-evaluated; an expression in "
        "prose fails the action at LOAD time and skips every sandbox lane. "
        f"Describe it in words instead: {offenders}"
    )


def test_descriptions_are_actually_being_inspected(manifest: dict) -> None:
    # Sanity: a manifest refactor that renamed the sections would make the
    # guard above pass vacuously.
    found = dict(_description_strings(manifest))
    assert "inputs.token.description" in found
    assert len(found) >= 4


def test_no_empty_expression_anywhere_in_the_manifest() -> None:
    # Defect 2 specifically: `${{ }}` is syntactically an expression and an
    # invalid one. It cannot appear in prose OR in real wiring.
    raw = ACTION_PATH.read_text(encoding="utf-8")
    empties = [m for m in _EXPRESSION_RE.findall(raw) if not m.strip()]
    assert not empties, (
        "empty `${{ }}` fails the action with 'An expression was expected'"
    )


def test_manifest_expressions_use_only_contexts_composite_actions_have() -> None:
    # Defect 1 generalized: `secrets` is the one that bit, but `env`, `needs`
    # and `matrix` are equally absent from composite-action metadata.
    raw = ACTION_PATH.read_text(encoding="utf-8")
    expressions = _EXPRESSION_RE.findall(raw)
    assert expressions, "sanity: the manifest should still contain expressions"
    forbidden = ("secrets.", "secrets[", "env.", "needs.", "matrix.")
    offenders = [e.strip() for e in expressions if any(tok in e for tok in forbidden)]
    assert not offenders, (
        f"composite actions have no secrets/env/needs/matrix context: {offenders}"
    )


def test_buildx_binary_is_not_written_to_the_actions_cache() -> None:
    # CodeQL actions/cache-poisoning/poisonable-step (high). The dispatch lane
    # checks out an operator-chosen ref with default-branch privilege, so any
    # Actions-cache WRITE in it is poisonable. The registry layer cache this
    # action exists for is unaffected.
    manifest = yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))
    buildx = [
        s
        for s in manifest["runs"]["steps"]
        if str(s.get("uses", "")).startswith("docker/setup-buildx-action@")
    ]
    assert buildx, "sanity: the action must still set up buildx"
    assert all((s.get("with") or {}).get("cache-binary") is False for s in buildx)


def test_dispatch_checkout_names_no_ref() -> None:
    # THE cache-poisoning fix. `ref: <input>` made the dispatch job execute one
    # branch's code while holding write access to another branch's Actions
    # cache scope — the privilege mismatch CodeQL's rule is about. Checking out
    # the RUN'S OWN ref collapses the two, so the code that executes and the
    # cache scope it can write are the same branch.
    #
    # `cache-binary: false` alone did NOT clear it: any step executing the tree
    # holds the runtime cache token regardless of which actions are called.
    workflow = yaml.safe_load(DISPATCH_WORKFLOW.read_text(encoding="utf-8"))
    checkouts = [
        s
        for job in workflow["jobs"].values()
        for s in (job.get("steps") or [])
        if isinstance(s, dict)
        and str(s.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts, "sanity: the dispatch lane must still check out the repo"
    for step in checkouts:
        assert "ref" not in (step.get("with") or {}), (
            "the dispatch lane must check out its own run ref; naming a ref "
            "from an input reintroduces the cache-poisoning shape"
        )


def test_dispatch_ref_input_is_asserted_against_the_run_ref() -> None:
    # The `ref` input survives as an assertion of intent (the deliverable asks
    # for it, and a silent mismatch would verify the wrong branch). It must be
    # reconciled against github.ref_name before the checkout.
    workflow = yaml.safe_load(DISPATCH_WORKFLOW.read_text(encoding="utf-8"))
    steps = [
        s
        for job in workflow["jobs"].values()
        for s in (job.get("steps") or [])
        if isinstance(s, dict)
    ]
    guard = next(
        (i for i, s in enumerate(steps) if "RUN_REF" in str(s.get("env", ""))), None
    )
    assert guard is not None, "the ref interlock is gone"
    checkout = next(
        i
        for i, s in enumerate(steps)
        if str(s.get("uses", "")).startswith("actions/checkout@")
    )
    assert guard < checkout
    assert "exit 1" in str(steps[guard]["run"])
