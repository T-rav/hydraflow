"""MockWorldSeed — serializable initial state for a sandbox scenario.

A scenario module's `seed()` function returns this dataclass. The host-side
harness serializes via `to_json()` and writes the result to a file that
the docker container's `mockworld.sandbox_main` entrypoint reads on boot.

Pure data; no methods that take a live FakeGitHub. The Fake adapters'
own `from_seed(seed)` classmethods construct themselves from this payload.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

#: Pre-rename ``phase_scripts`` keys → their current spelling. Seed JSON is
#: authored outside this repo, so a seed written before the ADR-0053
#: single-meaning rename ("Council" → "Ensemble" for the adversarial planning
#: ensemble) must keep working. Canonicalized in :meth:`MockWorldSeed.from_json`.
LEGACY_PHASE_SCRIPT_KEYS: dict[str, str] = {"shape_council": "shape_ensemble"}


@dataclass(frozen=True)
class MockWorldSeed:
    """Serializable initial state for a MockWorld run."""

    # List of (slug, path) pairs registered into RepoRegistryStore.
    repos: list[tuple[str, str]] = field(default_factory=list)

    # Each issue is a dict with keys: number, title, body, labels[], and
    # optionally state ("open" default / "closed"). A closed seed issue lets a
    # scenario exercise closed-issue reads (e.g. workspace_gc's is-it-safe-to-GC
    # check, epic_sweeper's are-all-children-done sweep) without driving the
    # whole pipeline to close it first (#9543).
    #
    # Also optionally ``updated_at`` (ISO-8601 string, #9544): overrides
    # ``FakeIssue``'s hard-coded ``2026-01-01T00:00:00Z`` default so a
    # scenario can seed a genuinely FRESH or genuinely STALE issue relative to
    # real wall-clock ``datetime.now(UTC)`` — needed for time-triggered loops
    # like ``stale_issue_gc`` (previously every seeded issue read as equally
    # stale, making the "fresh issue is skipped" branch untestable). Both
    # loaders (``FakeGitHub.from_seed`` for sandbox_main +
    # ``MockWorld.apply_seed`` for the in-process harness) thread this through
    # ``FakeGitHub.add_issue``. Absent key = no-op, back-compat preserved.
    issues: list[dict[str, Any]] = field(default_factory=list)

    # Per-issue seeded comments, keyed by issue number. Each entry is a dict
    # with keys: login, body, created_at (all optional — FakeGitHub.from_seed
    # fills sensible defaults for callers that only care about body). Lets a
    # scenario seed comments from distinct authors at distinct timestamps
    # (e.g. human-steering directive sequences that need a real
    # created_at high-water-mark), which a bare list[str] can't express.
    comments: dict[int, list[dict[str, Any]]] = field(default_factory=dict)

    # Each PR is a dict with keys: number, issue_number, branch,
    # ci_status, merged, labels[], and optionally mergeable (True default).
    # ``mergeable: false`` seeds a CONFLICTING PR so merge_state_watcher's
    # rebase/escalate path has something to act on (#9543).
    prs: list[dict[str, Any]] = field(default_factory=list)

    # Per-phase scripted LLM responses. Outer key is phase name
    # ("triage", "plan", "implement", "review", "fix_ci"); inner key is
    # issue number; value is a list of result dicts that get popped per
    # invocation.
    scripts: dict[str, dict[int, list[Any]]] = field(default_factory=dict)

    # Per-(issue, role) scripted advisor responses. Outer key is issue
    # number; inner key is the advisor role (``"pre_flight"`` /
    # ``"mid_flight"`` / ``"post_verify"``); value is a list of payloads
    # (typically JSON strings shaped like ``PostVerifyResult`` /
    # ``ReviewPlan``) that get popped per advisor invocation.
    #
    # Lives in its own field instead of ``scripts`` because the FakeLLM
    # advisor runner is keyed by a compound (issue, role) — the 2-arg
    # ``script_<phase>(issue, results)`` shape used by the loader for
    # ``scripts`` can't carry the role axis. Default empty for
    # back-compat with every existing seed payload.
    advisor_scripts: dict[int, dict[str, list[Any]]] = field(default_factory=dict)

    # ADR-0063 phase-level scripted outcomes (W3a/W3b/W4/W5).
    #
    # Shape per inner key:
    #
    # - ``discover``: ``{issue: [{"coherent": bool, "queries_required": [...],
    #   "summary": str, "findings": [...]}, ...]}`` — FIFO consumed by
    #   ``DiscoverRunner._evaluate_brief``.
    # - ``plan_review``: ``{issue: [{"verdict": "accept"|"reject",
    #   "gaps": [...]}, ...]}`` — FIFO consumed by ``PlanReviewer.review``.
    # - ``shape_ensemble``: ``{issue: {"<round_num>": "consensus"|"split"}}`` —
    #   round map consumed by ``ExpertEnsemble.vote`` / ``vote_diversified``.
    # - ``implement_spec_review``: ``{issue: [{"compliant": bool,
    #   "gaps": [...], "reasoning": str}, ...]}`` — FIFO consumed by
    #   ``DefaultSpecComplianceReviewer.review``.
    #
    # The loader in :mod:`mockworld.sandbox_main` translates these into the
    # corresponding ``FakeLLM.script_*`` calls. Default empty for back-compat
    # with every pre-W3a/W3b/W4/W5 scenario.
    phase_scripts: dict[str, dict[int, Any]] = field(default_factory=dict)

    # Pre-seed the auto-agent attempt counter per issue → count. Lets a
    # scenario start an issue at `auto_agent_max_attempts` (exhausted) so the
    # decompose-or-escalate terminal fires on the first tick, rather than
    # burning real auto-agent attempts to reach the cap. Applied to state by
    # sandbox_main. Empty = no pre-seeded counters (default; unaffected).
    auto_agent_attempts: dict[int, int] = field(default_factory=dict)

    # Caretaker-loop tick interval (seconds) in the sandbox. Default 60 matches
    # the historical hard-coded cadence; a long multi-hop scenario (e.g. s55's
    # depth-2 nested decompose) lowers it so its many pipeline stages advance
    # fast enough to finish within CI's slower runners. Applied by sandbox_main
    # via WorkerRegistryCallbacks.get_interval.
    sandbox_loop_interval: int = 60

    # How many ticks each enabled loop fires before assertions run.
    cycles_to_run: int = 4

    # Subset of loops to enable. None = all registered loops.
    loops_enabled: list[str] | None = None

    # Enable ADR-0042 staging mode (#10309): flips ``config.staging_enabled``
    # at boot via ``sandbox_main.apply_seed_config_overrides`` so
    # ``StagingPromotionLoop`` runs its real cut→monitor→merge path instead of
    # returning ``staging_disabled``. The s82 full-machine smoke seeds this
    # true; the default keeps every other scenario in the historical no-op —
    # enabling it globally (e.g. compose env) would have every scenario's
    # promotion loop minting rc/* FakePRs and shifting PR numbering under
    # scenarios that assert on it. Per-scenario, like ``loops_enabled``.
    staging_enabled: bool = False

    # (conclusion, url) for the main-branch CI status returned by
    # FakeGitHub.get_latest_ci_status().  Defaults to green so all existing
    # scenarios are unaffected.  CIMonitorLoop sandbox scenarios set this to
    # ("failure", "<run_url>") to drive the red-CI path.
    main_branch_ci_status: tuple[str, str] = ("success", "")

    # Artificial real-time delay (seconds) inside FakePlannerRunner.plan()
    # before it returns. Defaults to 0.0 (no-op — every existing scenario's
    # FakeLLM timing is unaffected). A scenario that needs an issue to stay
    # inside the real IssueStore "active" window (store_lifecycle's
    # mark_active/mark_complete bracket, populated while PlanPhase awaits
    # this call) for a sustained, real wall-clock duration — rather than the
    # near-instantaneous default — sets this to a positive value. See
    # s52_human_steering_directive.py, which needs HumanSteeringLoop's
    # 60-second-interval tick to reliably observe the issue as active;
    # without an artificial hold the plan-fails-forever tight loop's actual
    # active window is only milliseconds long even though it dominates the
    # loop logically, making a live snapshot miss it far more often than a
    # naive duty-cycle estimate would suggest.
    plan_hold_seconds: float = 0.0

    # Prompt self-refinement air-gap seam (#9724). SkillPromptEvalLoop's refine
    # path spawns two subprocesses that ``runners=fake_llm`` does NOT cover: the
    # weekly corpus backstop (``_run_corpus`` → ``make trust-adversarial``) and
    # the one-shot refine synthesis (``_refine_llm_complete`` → a real ``claude``
    # via ``run_lightweight_agent`` — the s51/#9796 real-claude-wedge class).
    # A scenario that drives the refine path (s56) scripts the corpus result
    # list here so ``_run_corpus`` returns a PASS→FAIL regression instead of
    # shelling out. Each dict carries ``{case_id, skill, expected_catcher,
    # status, ...}`` (same shape ``make trust-adversarial FORMAT=json`` emits).
    # Both loaders (sandbox_main + the in-process harness) leave the production
    # ``_run_corpus`` untouched when this is empty (every other scenario).
    skill_prompt_corpus_cases: list[dict[str, Any]] = field(default_factory=list)

    # Scripted raw refine-LLM response for the same seam. The loop parses a
    # ```diff fence out of this text (``parse_patch_response``); a scenario
    # supplies the full fenced response so refine synthesis never reaches a real
    # ``claude``. Only consumed when ``skill_prompt_corpus_cases`` is non-empty.
    skill_prompt_refine_patch: str = ""

    # Branch-protection rulesets served by ``FakeGitHub.fetch_rulesets`` for the
    # ``branch_protection_auditor`` loop (ADR-0082, #9644). Keyed by ruleset name
    # (e.g. ``"main protect"`` / ``"staging protect"``); each value is the ruleset
    # config dict shaped like GitHub's ``/repos/{repo}/rulesets/{id}`` response
    # (``name`` / ``target`` / ``enforcement`` / ``conditions`` / ``rules``).
    #
    # In production the auditor fetches live rulesets via ``gh_fetch_rulesets``
    # (a ``gh api`` shell-out) — unreachable on the air-gapped sandbox network.
    # Seeding this field lets a scenario stand up a *drifted* (or clean) live
    # ruleset so the auditor produces an observable drift outcome without any
    # real network fetch. All keys/values are JSON-native (string keys, list/dict
    # values), so no ``from_json`` coercion is needed. Default empty:
    # ``FakeGitHub.fetch_rulesets`` returns ``{}``, leaving every existing seed
    # payload unchanged.
    rulesets: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Stale worktrees pre-registered in StateTracker for the ``workspace_gc``
    # loop (#9543). Each entry is a dict with keys ``number`` (issue number)
    # and optionally ``branch`` (defaults to ``agent/issue-<number>``). Both
    # loaders (sandbox_main + the in-process harness) register the worktree in
    # ``state.active_workspaces``/``active_branches`` at boot, so a GC cycle
    # sees a tracked workspace whose issue state decides collection. Pair each
    # entry with a ``state: "closed"`` issue of the same number to drive the
    # collect path. All values are JSON-native; default empty leaves every
    # existing seed payload unchanged.
    stale_workspaces: list[dict[str, Any]] = field(default_factory=list)

    # Scripted gate-activation proposals for the ``gate_activator`` loop
    # (#9543). Each entry carries ``ActivationProposal`` kwargs (``name`` /
    # ``dimension`` / ``required_on`` / ``workflow`` / ``job`` /
    # ``make_target``). In production the detector reads the repo's real
    # ``gates.toml``/workflows/Makefile — all steady-state (no planned gates)
    # in the baked sandbox image, so the file-a-proposal path can never fire.
    # When non-empty, both loaders swap the loop's detector for one returning
    # these proposals (composition-root DI on the existing ``detector=``
    # injection point). Default empty: production detector untouched.
    gate_activations: list[dict[str, Any]] = field(default_factory=list)

    # Expired run-artifact directories materialized at boot for the
    # ``runs_gc`` loop (#9543). Each entry is a dict with keys ``issue``
    # (issue number) and optionally ``age_days`` (default 90 — far beyond any
    # realistic ``artifact_retention_days``). Both loaders create
    # ``<runs>/<issue>/<timestamp>/`` with the timestamp back-dated by
    # ``age_days``, so a purge cycle has a genuinely expired artifact to
    # delete (RunRecorder derives artifact age from the directory name).
    # Default empty: no directories are created.
    expired_run_dirs: list[dict[str, Any]] = field(default_factory=list)

    # EpicState records upserted into StateTracker at boot (#9643). Each entry
    # is an ``EpicState``-shaped payload (``epic_number`` required; every other
    # key optional — see ``models.EpicState``), with one seed-only extra:
    # ``last_activity_age_days`` (numeric). The materializer pops that key and
    # back-dates ``last_activity`` to ``now - age_days`` as a tz-AWARE ISO
    # timestamp, so seeds stay time-independent (no hard-coded date that rots)
    # and never hit the naive-timestamp footgun (``EpicManager._is_stale``
    # swallows the naive/aware ``TypeError`` and reads the epic as fresh).
    # Age the entry past ``epic_stale_days`` and EpicMonitorLoop's
    # ``check_stale_epics`` genuinely fires (s71). Keep ``child_issues`` empty
    # unless every child is also seeded — ``refresh_cache`` builds child detail
    # through the fetcher. Both loaders (sandbox_main + the in-process harness)
    # apply this before the loops boot. Default empty: no state written,
    # every existing seed payload unchanged.
    epic_states: list[dict[str, Any]] = field(default_factory=list)

    # Health trend artifacts written to disk at boot (#9643) — the JSONL/JSON
    # history ``HealthMonitorLoop.compute_trend_metrics`` reads. Fixed key
    # allowlist (unknown keys raise ``ValueError`` — fail-closed, a typo'd
    # artifact name must not silently seed nothing):
    #
    # - ``"outcomes"``: list[dict] appended row-by-row to
    #   ``config.memory_dir/outcomes.jsonl`` (rows like ``{"outcome":
    #   "failure"}``; < 20% ``success`` drives the first_pass_rate_low
    #   auto-adjustment, s72).
    # - ``"item_scores"``: dict written to ``config.memory_dir/item_scores.json``.
    # - ``"harness_failures"``: list[dict] appended to
    #   ``config.repo_memory_dir/harness_failures.jsonl`` (repo-scoped — NOT
    #   the flat memory_dir; mirrors ``HealthMonitorLoop._failures_path``).
    #
    # Default empty: no files created, every existing seed payload unchanged.
    health_metrics: dict[str, Any] = field(default_factory=dict)

    # Materialize an explicitly empty, healthy PromptTelemetry source before
    # sandbox loops boot. FakeLLM replaces every direct LLM runner in the
    # air-gapped sandbox, so a gateway-only scenario can truthfully have zero
    # direct inference rows; the coverage collector still requires the source
    # file to exist before treating that zero as observed rather than missing.
    # The loader verifies the audit chain and writes the same durable health
    # marker production telemetry uses. It never injects a spend row and
    # refuses to clear an existing degraded/corrupt source. Default False:
    # every scenario that does not assert gateway coverage is unchanged.
    prompt_telemetry_source_initialized: bool = False

    # Persisted worker heartbeats seeded into StateTracker at boot (#9643,
    # absorbed from #9904). Keyed by worker name; each value takes ``status``
    # (default "running"), ``age_seconds`` (numeric, relative — the
    # materializer back-dates ``last_run`` to ``now - age_seconds``, tz-aware)
    # and ``details`` (dict). An aged entry gives HealthMonitorLoop's
    # dead-man-switch reads (``_check_worker_staleness`` /
    # ``_check_sanity_loop_staleness`` via ``state.get_worker_heartbeats()``)
    # genuine history to judge. Note: the restart-then-escalate sweep also
    # needs a live BGWorkerManager with the worker registered — seeding only a
    # heartbeat exercises the read path, not a full stall escalation. Default
    # empty: no heartbeats written, every existing seed payload unchanged.
    worker_heartbeats: dict[str, dict[str, Any]] = field(default_factory=dict)

    # IssueRefinementLoop (spec #9957) air-gap seam. The loop reads the WHOLE
    # open backlog via ``PRPort.list_open_issues`` (Faked) and then spends one
    # structured LLM call per duplicate candidate / priority target — and THAT
    # call shells out to a real ``claude`` via ``run_lightweight_agent`` in
    # production (the #9796 real-claude-wedge class that hangs the air-gapped
    # sandbox). A scenario (s57) seeds a backlog here so the refinement loop has
    # real issues to reason about, and scripts the raw dup-verdict JSON in
    # ``issue_refinement_verdicts`` so judgment never reaches a real ``claude``.
    #
    # Each backlog entry is a dict with keys ``number`` / ``title`` / ``body`` /
    # ``labels`` / ``updated_at`` (all JSON-native — no ``from_json`` coercion
    # needed). ``sandbox_main`` seeds them into FakeGitHub as open issues when
    # non-empty; empty (every other scenario) leaves the backlog untouched.
    #
    # Note: kept distinct from the generic ``issues`` field on purpose — those
    # feed the whole pipeline (triage/discover/...) when they carry lifecycle
    # labels, whereas a refinement backlog is deliberately label-free so ONLY
    # the backlog-wide refinement sweep sees it (the pipeline's store refresh
    # pulls only ``hydraflow-*``-labelled issues).
    issue_refinement_backlog: list[dict[str, Any]] = field(default_factory=list)

    # Scripted raw dup-judgment LLM responses for the same seam, consumed FIFO
    # (one per judged dup candidate; the last is reused if the loop asks for
    # more). Each is the full raw text the loop's ``refinement_llm.complete``
    # would return — a JSON verdict object; a ```json fence is fine, since
    # ``parse_dup_verdict`` is fence-tolerant. Only consumed when
    # ``issue_refinement_backlog`` is non-empty. Priority-scoring calls on the
    # SAME seam are answered with a benign ``{"priority":"none"}`` no-op inside
    # ``sandbox_main`` (an unlabelled issue skips a ``none`` verdict), so a
    # scenario's observable is a single dup proposal, not a relabel storm.
    issue_refinement_verdicts: list[str] = field(default_factory=list)

    # BGWorkerManager's registered-loop SET, materialized at boot (#10086).
    # Keyed by worker name; each value optionally carries
    # ``interval_seconds`` (default 60) and ``cycle_timeout_seconds``
    # (default 60) for a lightweight duck-typed loop stand-in registered
    # into a real ``BGWorkerManager`` (see
    # ``mockworld.sandbox_main.materialize_registered_workers``).
    #
    # ``HealthMonitorLoop._check_worker_staleness`` (the generic restart-
    # first/escalate dead-man-switch) only considers names present in
    # ``bg_workers.registered_loop_names()`` — a seeded ``worker_heartbeats``
    # entry alone (#9643/#9904) never traverses that filter, so the stall
    # sweep's restart/escalate path was previously unreachable end-to-end.
    # Pair a name here with a matching stale entry in ``worker_heartbeats``
    # to drive the escalation. Default empty: no ``BGWorkerManager`` is
    # constructed and ``HealthMonitorLoop._bg_workers`` stays unset, so every
    # existing scenario (including plain ``worker_heartbeats`` usages that
    # only exercise the read path) is unaffected.
    registered_workers: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Seeded BACKGROUND_WORKER_STATUS event HISTORY, materialized onto disk at
    # boot (#10133, deferred from #9544). ``TrustFleetSanityLoop._collect_
    # window_metrics`` computes its 24h ticks/repair/error window via
    # ``EventBus.load_events_since`` — a DISK read (``EventLog.load``), NOT
    # the in-memory ``EventBus._history`` list that ``/api/events`` falls back
    # to. The sandbox's shared bus has historically been a bare ``EventBus()``
    # with no ``EventLog`` attached, so that read returned ``None`` (coerced
    # to ``[]`` by the loop) regardless of what a scenario seeded — the
    # issues_per_hour / repair_ratio / tick_error_ratio breach paths had no
    # active-trigger coverage. Keyed by worker name; each entry is a dict
    # with ``age_seconds`` (numeric, relative — mirrors ``worker_heartbeats``;
    # the materializer back-dates the row's timestamp from boot so the seed
    # never rots), ``status`` (default "ok") and ``details`` (dict, default
    # ``{}`` — the same shape ``BaseBackgroundLoop._execute_cycle`` publishes,
    # e.g. ``{"filed": 20}`` for issues_per_hour or ``{"failed": 5}`` for
    # repair_ratio). Both loaders (``sandbox_main.materialize_worker_status_
    # history`` / ``MockWorld._wire_seed_loop_seams``) only attach a real
    # ``EventLog`` to the loop's event bus when this field is non-empty —
    # every other scenario keeps the historical no-log ``EventBus()``,
    # unaffected. Default empty: no rows written, no EventLog attached.
    worker_status_history: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    # Repo-wiki fixture entries, materialized into a REAL ``RepoWikiStore``
    # at boot via ``RepoWikiStore.ingest`` (#10133, PIECE 2). Each entry is a
    # dict with keys ``repo_slug`` (required — the wiki repo to ingest under),
    # ``title`` (required), ``content`` (default ``""``), ``source_type``
    # (default ``"manual"``), ``source_issue`` (optional int), ``fixed_in_pr``
    # (optional str — a PR reference like ``"#8715"``) and ``code_refs``
    # (optional list of ``path.py:symbol`` strings). Routing the fixture
    # through the store's own ``ingest`` — rather than hand-writing topic-page
    # markdown — is what GUARANTEES the STRUCTURED ``WikiEntry`` shape
    # ``WikiRotDetectorLoop`` consumes since issue #9936
    # (``source_type``/``source_issue``/``fixed_in_pr``/``code_refs`` as
    # modeled fields, not an unstructured whole-file blob): it is the same
    # production writer the real ingest pipeline uses.
    #
    # Deliberately keyed by an explicit ``repo_slug`` per entry rather than
    # always targeting the running config's own ``config.repo`` (self-repo):
    # in the air-gapped sandbox ``config.repo`` is EMPTY (no ``.git`` in the
    # image — see ``mockworld.sandbox_main._apply_sandbox_config_overrides``
    # docstring), so ``WikiRotDetectorLoop``'s ``is_self`` check
    # (``slug == self_slug and bool(self_slug)``) can never be true there
    # regardless of which slug a fixture uses. A fixture ingested under any
    # OTHER (managed-repo-shaped) slug is scanned via the loop's non-self
    # path (``verify_cite_grep`` against ``config.repo_root`` — no
    # ``is_self`` gate), which is what actually drives the per-cite
    # broken-cite fire end-to-end in the sandbox; a cite embedded in
    # ``content`` (e.g. ``` `path/to.py:missing_symbol` ```) that does not
    # resolve on disk is what makes the entry "broken" (mirrors
    # ``fixed_in_pr``/``code_refs`` shipped-claim entries, which only verify
    # on the self-repo path). Both loaders (``sandbox_main.
    # materialize_wiki_fixtures`` / ``MockWorld._wire_seed_loop_seams``)
    # ingest into the SAME wiki_root the real (read-only) ``repo_wiki_store``
    # reads from — see ``sandbox_main.resolve_self_wiki_root``. Default
    # empty: no wiki content is written, every existing seed payload
    # unchanged.
    repo_wiki_fixtures: list[dict[str, Any]] = field(default_factory=list)

    # Scripted credit-exhaustion signal for the credit-pause path (#10570).
    # There is no FakeLLM path that emits a credit-exhaustion signal, so the
    # orchestrator's global credit pause (``credits_paused_until`` + the
    # ``SYSTEM_ALERT`` banner) and its clear-via-control-endpoint resume have no
    # docker-tier coverage. When set, ``sandbox_main`` arms the FakeLLM plan
    # runner so the FIRST ``planners.plan`` call for the given issue raises a
    # ``CreditExhaustedError`` — the air-gapped stand-in for the Claude CLI
    # terminating on a weekly-limit cap. The plan phase propagates it to
    # ``_supervise_loops`` (``phase_utils.run_refilling_pool`` treats it as
    # fatal), which pauses every loop. Keys:
    #   - ``issue`` (int, required): the plan-queue issue whose ``plan`` raises.
    #     Seed a matching ``hydraflow-plan``-labelled issue so the plan loop
    #     actually reaches it.
    #   - ``message`` (str, optional): the raw credit text carried on the error;
    #     defaults to the weekly-limit wording. Cosmetic — the SYSTEM_ALERT's
    #     ``resume_at`` comes from ``resume_at`` below, not from parsing this.
    #   - ``resume_at`` (str, optional): ISO-8601 timestamp the pause runs until;
    #     omit to let the orchestrator apply its default (~5h) fallback. A
    #     scenario passes an explicit FUTURE value so ``credits_paused_until`` is
    #     deterministically non-null within the scenario's polling window.
    #   - ``authoritative`` (bool, optional, default True): tags the signal as
    #     originating from the subprocess's own termination (#10558) so the
    #     orchestrator pauses directly, bypassing the live availability probe
    #     (which cannot see a weekly-quota exhaustion and would otherwise refute
    #     the signal as a false positive on the air-gapped network).
    # Only consumed by ``sandbox_main`` (Tier-2). The credit pause is an
    # orchestrator-supervision behavior the flat in-process parity harness
    # (``MockWorld.run_pipeline``) cannot model, so the scenario opts out of
    # Tier-1 (``IN_PROCESS = False``) and the orchestrator supervision is covered
    # in-process by ``tests/test_credit_pause.py``. Default None: no signal,
    # every existing seed payload unchanged.
    credit_exhaustion: dict[str, Any] | None = None

    def to_json(self) -> str:
        """Serialize to JSON for cross-process transfer."""
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> MockWorldSeed:
        """Deserialize from JSON string."""
        data = json.loads(raw)
        # asdict() converts tuples to lists; coerce repos and ci status back.
        if "repos" in data:
            data["repos"] = [tuple(r) for r in data["repos"]]
        if "main_branch_ci_status" in data:
            data["main_branch_ci_status"] = tuple(data["main_branch_ci_status"])
        # JSON keys are strings; coerce script issue keys back to int.
        if "scripts" in data:
            data["scripts"] = {
                phase: {int(k): v for k, v in by_issue.items()}
                for phase, by_issue in data["scripts"].items()
            }
        # Same coercion for advisor_scripts (issue is the OUTER key here).
        if "advisor_scripts" in data:
            data["advisor_scripts"] = {
                int(issue): by_role
                for issue, by_role in data["advisor_scripts"].items()
            }
        # Same coercion for comments (issue is the OUTER key here).
        if "comments" in data:
            data["comments"] = {
                int(issue): comment_list
                for issue, comment_list in data["comments"].items()
            }
        # phase_scripts (ADR-0063): outer key is phase name, inner key is
        # issue number (JSON string → int). The ``shape_ensemble`` payload's
        # inner-inner key is the round number, also needing string→int.
        if "phase_scripts" in data:
            coerced: dict[str, dict[int, Any]] = {}
            for raw_phase, by_issue in data["phase_scripts"].items():
                # Seed files are authored outside this repo and outlive it.
                # ``shape_council`` is the pre-rename spelling of
                # ``shape_ensemble``; canonicalize on read so an older seed
                # keeps scripting the same fake instead of falling through
                # sandbox_main's unknown-phase branch as a silent no-op.
                phase = LEGACY_PHASE_SCRIPT_KEYS.get(str(raw_phase), str(raw_phase))
                inner: dict[int, Any] = {}
                for k, raw_v in by_issue.items():
                    if phase == "shape_ensemble" and isinstance(raw_v, dict):
                        v: Any = {int(rk): rv for rk, rv in raw_v.items()}
                    else:
                        v = raw_v
                    inner[int(k)] = v
                coerced[phase] = inner
            data["phase_scripts"] = coerced
        return cls(**data)
