"""Shape pins for the cached sandbox image build + the dispatch lane (#11601).

Workflow YAML cannot be proven by running it, so the invariants that would fail
*silently* are pinned from the parsed YAML here.

Three of them are silent-failure shapes, not style preferences:

* **The cache can be thrown away with no red anywhere.** `docker compose` only
  builds a service whose image is absent, and the harness rebuilds every
  service before each scenario against a builder that does not share buildx's
  cache. So a lane that pre-builds the agent image but then lists `hydraflow`
  in its compose-build call, or forgets the `SANDBOX_BUILD_SERVICES` export,
  is green, correct, and exactly as slow as before.
* **The cache ref is mutable and shared.** A `pull_request` job that can write
  it is a cache-poisoning sink in a public repo. Only push/schedule lanes may
  pass `push-cache: 'true'`, and they are enumerated.
* **The fast-subset scenario list lives in three places.** ci.yml's required
  lane, the dispatch workflow, and the scenario README. It drifted before —
  the README claimed "s01, s06 only" for six scenarios longer than that was
  true. The list is not consolidated because doing so would rewrite the body
  of a REQUIRED check; it is held identical by test instead.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT))

from scripts.sandbox_scenario import DEFAULT_BUILD_SERVICES  # noqa: E402

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
ACTION_PATH = REPO_ROOT / ".github" / "actions" / "build-agent-image" / "action.yml"
COMPOSE_PATH = REPO_ROOT / "docker-compose.sandbox.yml"
SCENARIO_README = REPO_ROOT / "tests" / "sandbox_scenarios" / "README.md"
SCENARIO_DIR = REPO_ROOT / "tests" / "sandbox_scenarios" / "scenarios"
DISPATCH_WORKFLOW = WORKFLOW_DIR / "sandbox-dispatch.yml"
CI_WORKFLOW = WORKFLOW_DIR / "ci.yml"
AGENT_IMAGE_WORKFLOW = WORKFLOW_DIR / "build-agent-image.yml"

#: How a job invokes the shared cached build.
ACTION_USES = "./.github/actions/build-agent-image"

#: The expression the composite action must use to name the cache ref. A step
#: OUTPUT, not `env.` — GITHUB_ENV propagation into a composite step's `with:`
#: is not a contract worth betting the cache on.
CACHE_REF_EXPR = "steps.resolve.outputs.cache-ref"

#: The compose service whose image the composite action pre-builds. Any lane
#: that pre-builds it must NOT ask compose to build it again.
PREBUILT_SERVICE = "hydraflow"

#: `"<workflow>:<job>" -> why this context may WRITE the shared cache ref`.
#: Every entry must be a push- or schedule-only context — never a
#: `pull_request` one. Adding a row is a reviewed decision.
CACHE_WRITERS: dict[str, str] = {
    "ci.yml:post-merge-smoke": (
        "runs on `push` to staging/main — already-merged, already-reviewed "
        "code. The primary refresher: every merge republishes the cache."
    ),
    "ci.yml:sandbox-nightly": (
        "runs on `schedule` against `main` via the default-branch workflow; "
        "never executes PR-authored code."
    ),
}

_COMPOSE_BUILD_RE = re.compile(
    r"docker compose\s+-f\s+docker-compose\.sandbox\.yml\s+build\s+(?P<services>.+)"
)
_FOR_LOOP_RE = re.compile(r"^\s*for s in (?P<names>[^;]+); do", re.MULTILINE)
_SCENARIO_NAME_RE = re.compile(r"\bs\d+_[a-z0-9_]+\b")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    """YAML 1.1 coerces the bare key ``on`` to boolean ``True`` — read both."""
    raw = workflow.get("on")
    if raw is None:
        raw = workflow.get(True)
    return raw if isinstance(raw, dict) else {}


def _steps(job: dict) -> list[dict]:
    return [s for s in (job.get("steps") or []) if isinstance(s, dict)]


def _all_jobs() -> list[tuple[str, str, dict]]:
    """(workflow file name, job key, job dict) for the whole fleet."""
    out: list[tuple[str, str, dict]] = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        for job_name, job in (_load(path).get("jobs") or {}).items():
            if isinstance(job, dict):
                out.append((path.name, job_name, job))
    return out


def _uses_cached_build(job: dict) -> bool:
    return any(str(s.get("uses", "")) == ACTION_USES for s in _steps(job))


def _compose_built_services(job: dict) -> list[str]:
    """Services every `docker compose … build` step in *job* asks for."""
    services: list[str] = []
    for step in _steps(job):
        for match in _COMPOSE_BUILD_RE.finditer(str(step.get("run", ""))):
            services.extend(match.group("services").split())
    return services


def _job_permissions(job: dict) -> dict:
    perms = job.get("permissions")
    return perms if isinstance(perms, dict) else {}


def _fast_subset_from_run_bodies(path: Path) -> list[str]:
    """The `for s in …; do` scenario list in *path* (exactly one expected)."""
    matches = _FOR_LOOP_RE.findall(path.read_text(encoding="utf-8"))
    assert len(matches) == 1, f"expected exactly one fast-subset loop in {path.name}"
    return matches[0].split()


@pytest.fixture(scope="module")
def action() -> dict:
    return _load(ACTION_PATH)


@pytest.fixture(scope="module")
def action_steps(action: dict) -> list[dict]:
    return [s for s in (action["runs"].get("steps") or []) if isinstance(s, dict)]


@pytest.fixture(scope="module")
def build_step(action_steps: list[dict]) -> dict:
    matches = [
        s
        for s in action_steps
        if str(s.get("uses", "")).startswith("docker/build-push-action@")
    ]
    assert len(matches) == 1, "expected exactly one build-push-action step"
    return matches[0]


class TestCompositeActionExists:
    def test_action_file_is_a_composite_action(self, action: dict) -> None:
        assert action["runs"]["using"] == "composite"

    def test_it_builds_the_agent_dockerfile(self, build_step: dict) -> None:
        assert (build_step.get("with") or {}).get("file") == "Dockerfile.agent"

    def test_it_loads_the_image_into_the_local_daemon(self, build_step: dict) -> None:
        # Without `load`, buildx's container driver keeps the result inside
        # buildkit and compose would find no image to boot.
        assert (build_step.get("with") or {}).get("load") is True


class TestLayerCacheIsRealAndRefreshable:
    def test_cache_is_imported_from_a_registry_ref(self, build_step: dict) -> None:
        cache_from = str((build_step.get("with") or {}).get("cache-from", ""))
        assert "type=registry" in cache_from
        assert CACHE_REF_EXPR in cache_from

    @pytest.mark.parametrize(
        ("fragment", "why"),
        [
            (
                "mode=max",
                "mode=min caches only the final stage, and every expensive layer "
                "(apt, NodeSource, npm -g, uv sync) lives in the `base`/`tools` "
                "stages the runtime stage only COPY --from's — i.e. mode=min "
                "would cache none of what this fixes",
            ),
            (
                "ignore-error=true",
                "the build has already succeeded by the time the export runs, so "
                "a quota/permission/registry blip must not red a verification lane",
            ),
            (
                "inputs.push-cache",
                "the export must stay gated on the input, or a pull_request lane "
                "would write the shared mutable ref",
            ),
        ],
    )
    def test_cache_export_directives(
        self, build_step: dict, fragment: str, why: str
    ) -> None:
        cache_to = str((build_step.get("with") or {}).get("cache-to", ""))
        assert fragment in cache_to, why

    def test_import_and_export_name_the_same_ref(self, build_step: dict) -> None:
        with_block = build_step.get("with") or {}
        assert CACHE_REF_EXPR in str(with_block.get("cache-to", ""))
        assert CACHE_REF_EXPR in str(with_block.get("cache-from", ""))

    def test_cache_gating_uses_a_step_output_not_an_outcome(
        self, build_step: dict
    ) -> None:
        # Composite action steps expose `steps.<id>.outputs` but NOT
        # `steps.<id>.outcome` (and support no `continue-on-error`). Gating on
        # `.outcome` inside a composite silently evaluates to '' — which would
        # blank `cache-from` and disable the cache with nothing red anywhere.
        with_block = build_step.get("with") or {}
        for key in ("cache-from", "cache-to"):
            expr = str(with_block.get(key, ""))
            assert "steps.ghcr-login.outputs.ok" in expr, key
            assert ".outcome" not in expr, key

    def test_manifest_references_no_context_composite_actions_lack(self) -> None:
        # GitHub template-evaluates EVERY `${{ }}` in an action manifest —
        # including inside a `description:` string, which reads like prose and
        # is nobody's idea of live wiring. `secrets` does not exist in
        # composite-action metadata, so a description that quotes
        # `${{ secrets.GITHUB_TOKEN }}` as documentation fails the action at
        # LOAD time ("Unrecognized named-value: 'secrets'") and takes every
        # sandbox lane down with it. actionlint does not evaluate manifest
        # descriptions, so nothing local catches this — CI did, once.
        raw = ACTION_PATH.read_text(encoding="utf-8")
        expressions = re.findall(r"\$\{\{(.+?)\}\}", raw, re.DOTALL)
        assert expressions, "sanity: the manifest should contain expressions"
        forbidden = ("secrets.", "secrets[", "env.", "needs.", "matrix.")
        offenders = [
            e.strip() for e in expressions if any(token in e for token in forbidden)
        ]
        assert not offenders, (
            "composite-action manifests have no `secrets`/`env`/`needs`/"
            f"`matrix` context; these expressions fail at load time: {offenders}"
        )

    def test_buildx_does_not_write_the_actions_cache(
        self, action_steps: list[dict]
    ) -> None:
        # docker/setup-buildx-action defaults `cache-binary: true`, storing the
        # buildx binary in the GitHub Actions cache. That write is an
        # `actions/cache-poisoning/poisonable-step` sink for the dispatch lane,
        # which checks out an operator-chosen ref with default-branch
        # privilege — CodeQL flagged it on #11621, the same rule as alert #108.
        # The layer cache this action exists for is a REGISTRY cache and is
        # unaffected by turning this off.
        buildx = [
            s
            for s in action_steps
            if str(s.get("uses", "")).startswith("docker/setup-buildx-action@")
        ]
        assert buildx, "sanity: the action must still set up buildx"
        for step in buildx:
            assert (step.get("with") or {}).get("cache-binary") is False

    def test_no_composite_step_uses_continue_on_error(
        self, action_steps: list[dict]
    ) -> None:
        # Unsupported key in composite action metadata — the runner rejects it.
        assert not [s for s in action_steps if "continue-on-error" in s]

    def test_login_failure_degrades_instead_of_failing_the_lane(
        self, action_steps: list[dict]
    ) -> None:
        login = next(s for s in action_steps if s.get("id") == "ghcr-login")
        run = str(login["run"])
        assert "ok=true" in run and "ok=false" in run
        # Credentials never interpolated into the shell body.
        assert "${{" not in run

    def test_export_is_gated_on_the_push_cache_input(self, build_step: dict) -> None:
        cache_to = str((build_step.get("with") or {}).get("cache-to", ""))
        assert "inputs.push-cache" in cache_to

    def test_at_least_one_lane_actually_writes_the_cache(self) -> None:
        # A read-only fleet means the ref is never refreshed and the cache
        # rots into permanent misses — the "key that never invalidates" shape,
        # inverted.
        assert CACHE_WRITERS
        writers = {
            f"{wf}:{job_name}"
            for wf, job_name, job in _all_jobs()
            for step in _steps(job)
            if str(step.get("uses", "")) == ACTION_USES
            and str((step.get("with") or {}).get("push-cache", "")).lower() == "true"
        }
        assert writers == set(CACHE_WRITERS)


class TestCacheWritePrivilegeIsNotReachableFromAPullRequest:
    def test_declared_writers_are_push_or_schedule_only_contexts(self) -> None:
        for key in CACHE_WRITERS:
            wf_name, job_name = key.split(":")
            job = _load(WORKFLOW_DIR / wf_name)["jobs"][job_name]
            condition = str(job.get("if", ""))
            assert (
                "github.event_name == 'push'" in condition
                or "github.event_name == 'schedule'" in condition
            ), f"{key} may write the cache but its `if:` does not exclude PRs"

    def test_writers_request_packages_write(self) -> None:
        for key in CACHE_WRITERS:
            wf_name, job_name = key.split(":")
            job = _load(WORKFLOW_DIR / wf_name)["jobs"][job_name]
            assert _job_permissions(job).get("packages") == "write", key

    def test_non_writers_never_request_packages_write(self) -> None:
        offenders = [
            f"{wf}:{job_name}"
            for wf, job_name, job in _all_jobs()
            if _uses_cached_build(job)
            and f"{wf}:{job_name}" not in CACHE_WRITERS
            and _job_permissions(job).get("packages") == "write"
        ]
        assert not offenders, f"cache-reading lanes over-privileged: {offenders}"

    def test_every_consumer_requests_at_least_packages_read(self) -> None:
        offenders = [
            f"{wf}:{job_name}"
            for wf, job_name, job in _all_jobs()
            if _uses_cached_build(job)
            and _job_permissions(job).get("packages") not in ("read", "write")
        ]
        assert not offenders, (
            f"jobs pulling the cache without packages perms: {offenders}"
        )

    def test_every_consumer_passes_the_token(self) -> None:
        for wf, job_name, job in _all_jobs():
            for step in _steps(job):
                if str(step.get("uses", "")) != ACTION_USES:
                    continue
                token = str((step.get("with") or {}).get("token", ""))
                assert "secrets.GITHUB_TOKEN" in token, f"{wf}:{job_name}"


class TestPrebuiltImageIsActuallyUsed:
    """The two couplings that make the cache save time instead of look cached."""

    def test_compose_pins_the_tag_the_action_loads(self, action: dict) -> None:
        tag = action["inputs"]["tag"]["default"]
        compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
        assert compose["services"][PREBUILT_SERVICE]["image"] == tag

    def test_the_action_tells_the_harness_to_skip_the_prebuilt_service(
        self, action_steps: list[dict]
    ) -> None:
        exports = [
            str(s.get("run", ""))
            for s in action_steps
            if "SANDBOX_BUILD_SERVICES" in str(s.get("run", ""))
        ]
        assert len(exports) == 1, "expected exactly one SANDBOX_BUILD_SERVICES export"
        assert f"{PREBUILT_SERVICE} " not in exports[0]
        assert not exports[0].rstrip().endswith(PREBUILT_SERVICE)

    def test_exported_services_are_the_defaults_minus_the_prebuilt_one(
        self, action_steps: list[dict]
    ) -> None:
        # Derived from the harness's own list, so adding a compose service
        # without updating the export fails here rather than booting a lane
        # against an image that was never built.
        export = next(
            str(s["run"])
            for s in action_steps
            if "SANDBOX_BUILD_SERVICES" in str(s.get("run", ""))
        )
        match = re.search(r'SANDBOX_BUILD_SERVICES=([^"\n]+)', export)
        assert match, export
        exported = tuple(match.group(1).split())
        expected = tuple(s for s in DEFAULT_BUILD_SERVICES if s != PREBUILT_SERVICE)
        assert exported == expected

    def test_no_lane_rebuilds_the_prebuilt_service_via_compose(self) -> None:
        offenders = [
            f"{wf}:{job_name}"
            for wf, job_name, job in _all_jobs()
            if _uses_cached_build(job)
            and PREBUILT_SERVICE in _compose_built_services(job)
        ]
        assert not offenders, (
            "these lanes pre-build the agent image and then throw it away by "
            f"asking compose to rebuild it: {offenders}"
        )

    def test_every_sandbox_building_lane_uses_the_cached_build(self) -> None:
        # The inverse guard: a lane that boots the sandbox stack without the
        # composite action has no `hydraflow-agent-sandbox:local` image at all.
        offenders = [
            f"{wf}:{job_name}"
            for wf, job_name, job in _all_jobs()
            if _compose_built_services(job) and not _uses_cached_build(job)
        ]
        assert not offenders, f"sandbox lanes not using the cached build: {offenders}"

    def test_the_sweep_is_not_vacuous(self) -> None:
        consumers = [
            f"{wf}:{job_name}"
            for wf, job_name, job in _all_jobs()
            if _uses_cached_build(job)
        ]
        assert len(consumers) >= 5, consumers


class TestDispatchWorkflow:
    @pytest.fixture(scope="class")
    def dispatch(self) -> dict:
        return _load(DISPATCH_WORKFLOW)

    @pytest.fixture(scope="class")
    def dispatch_job(self, dispatch: dict) -> dict:
        jobs = dispatch["jobs"]
        assert len(jobs) == 1, "the dispatch lane is one job by design"
        return next(iter(jobs.values()))

    def test_manual_only_so_it_can_never_gate_a_pr(self, dispatch: dict) -> None:
        assert set(_triggers(dispatch)) == {"workflow_dispatch"}

    def test_declares_both_inputs(self, dispatch: dict) -> None:
        inputs = _triggers(dispatch)["workflow_dispatch"]["inputs"]
        assert set(inputs) == {"ref", "scenario"}

    def test_ref_defaults_to_the_default_branch(self, dispatch: dict) -> None:
        inputs = _triggers(dispatch)["workflow_dispatch"]["inputs"]
        assert inputs["ref"]["default"] == "staging"

    def test_scenario_defaults_to_the_fast_subset(self, dispatch: dict) -> None:
        inputs = _triggers(dispatch)["workflow_dispatch"]["inputs"]
        assert inputs["scenario"]["default"] == "fast"

    def test_concurrency_group_resolves_input_defaults(self, dispatch: dict) -> None:
        # `github.event.inputs.*` carries only what the caller explicitly sent,
        # so a CLI/API dispatch omitting a field yields '' rather than the
        # declared default — and two runs that ARE the same (ref, scenario)
        # land in different concurrency groups. The `inputs` context resolves
        # defaults and is available to workflow-level `concurrency`.
        group = str((dispatch.get("concurrency") or {}).get("group", ""))
        assert "github.event.inputs" not in group
        assert "inputs.ref" in group and "inputs.scenario" in group

    def test_it_runs_the_sandbox_harness(self, dispatch_job: dict) -> None:
        bodies = " ".join(str(s.get("run", "")) for s in _steps(dispatch_job))
        assert "scripts/sandbox_scenario.py run" in bodies

    def test_verdict_reaches_the_job_summary(self, dispatch_job: dict) -> None:
        summary = [
            s
            for s in _steps(dispatch_job)
            if "GITHUB_STEP_SUMMARY" in str(s.get("run", ""))
        ]
        assert summary, "the dispatch lane must print its verdict to the summary"
        # always(): a red run is exactly when the operator needs the tail.
        assert all(str(s.get("if", "")).strip() == "always()" for s in summary)

    def test_the_operator_ref_is_never_interpolated_into_a_shell_body(
        self, dispatch_job: dict
    ) -> None:
        # Script-injection hygiene: dispatch inputs travel through `env:`.
        for step in _steps(dispatch_job):
            assert "${{ inputs." not in str(step.get("run", "")), step

    def test_it_cannot_write_the_shared_cache(self, dispatch_job: dict) -> None:
        assert _job_permissions(dispatch_job).get("packages") == "read"
        for step in _steps(dispatch_job):
            if str(step.get("uses", "")) == ACTION_USES:
                assert "push-cache" not in (step.get("with") or {})

    def test_pull_request_refs_are_refused_before_checkout(
        self, dispatch_job: dict
    ) -> None:
        # The real cache-poisoning vector: `refs/pull/N/merge` is fetchable
        # from this repo, and for a FORK PR it is outsider-controlled code
        # that would run here with default-branch privilege. The guard must
        # run BEFORE the checkout — once the tree is on disk, `pip install -e`
        # alone executes repo-authored build hooks.
        steps = _steps(dispatch_job)
        guard = next(
            (i for i, s in enumerate(steps) if "refs/pull/*" in str(s.get("run", ""))),
            None,
        )
        assert guard is not None, "no pull-request-ref guard in the dispatch lane"
        checkout = next(
            i
            for i, s in enumerate(steps)
            if str(s.get("uses", "")).startswith("actions/checkout@")
        )
        assert guard < checkout, "the ref guard must precede the checkout"
        assert "exit 1" in str(steps[guard]["run"])

    def test_the_guard_step_needs_no_checkout(self, dispatch_job: dict) -> None:
        # It must not depend on the repo it is guarding against.
        steps = _steps(dispatch_job)
        guard = next(s for s in steps if "refs/pull/*" in str(s.get("run", "")))
        assert "git " not in str(guard["run"])


class TestFastSubsetHasOneMeaning:
    """ci.yml (required lane), the dispatch workflow, and the README must agree."""

    @pytest.fixture(scope="class")
    def ci_fast_subset(self) -> list[str]:
        return _fast_subset_from_run_bodies(CI_WORKFLOW)

    def test_ci_fast_subset_is_non_trivial(self, ci_fast_subset: list[str]) -> None:
        # Sanity: a parse that degraded to [] would make every check below
        # pass vacuously.
        assert len(ci_fast_subset) >= 2, ci_fast_subset

    def test_dispatch_fast_subset_matches_ci(self, ci_fast_subset: list[str]) -> None:
        assert _fast_subset_from_run_bodies(DISPATCH_WORKFLOW) == ci_fast_subset

    def test_readme_documents_the_list_ci_actually_runs(
        self, ci_fast_subset: list[str]
    ) -> None:
        lines = [
            line
            for line in SCENARIO_README.read_text(encoding="utf-8").splitlines()
            if line.startswith("- **fast**")
        ]
        assert len(lines) == 1, "expected one `- **fast**` line in the scenario README"
        assert _SCENARIO_NAME_RE.findall(lines[0]) == ci_fast_subset

    def test_every_fast_scenario_module_exists(self, ci_fast_subset: list[str]) -> None:
        missing = [
            n for n in ci_fast_subset if not (SCENARIO_DIR / f"{n}.py").is_file()
        ]
        assert not missing, f"fast subset names with no scenario module: {missing}"


class TestImageSizeGateSurvives:
    """Caching changes how the image is built, never what ships in it."""

    def test_the_2gb_rc_gate_is_still_enforced(self) -> None:
        raw = AGENT_IMAGE_WORKFLOW.read_text(encoding="utf-8")
        assert "-gt 2048" in raw
        assert "exceeds 2GB limit" in raw

    def test_the_size_gate_job_still_builds_the_agent_dockerfile(self) -> None:
        build_job = _load(AGENT_IMAGE_WORKFLOW)["jobs"]["build"]
        files = [
            (s.get("with") or {}).get("file")
            for s in _steps(build_job)
            if str(s.get("uses", "")).startswith("docker/build-push-action@")
        ]
        assert files and all(f == "Dockerfile.agent" for f in files)
