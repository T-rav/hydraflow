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


@dataclass(frozen=True)
class MockWorldSeed:
    """Serializable initial state for a MockWorld run."""

    # List of (slug, path) pairs registered into RepoRegistryStore.
    repos: list[tuple[str, str]] = field(default_factory=list)

    # Each issue is a dict with keys: number, title, body, labels[].
    issues: list[dict[str, Any]] = field(default_factory=list)

    # Per-issue seeded comments, keyed by issue number. Each entry is a dict
    # with keys: login, body, created_at (all optional — FakeGitHub.from_seed
    # fills sensible defaults for callers that only care about body). Lets a
    # scenario seed comments from distinct authors at distinct timestamps
    # (e.g. human-steering directive sequences that need a real
    # created_at high-water-mark), which a bare list[str] can't express.
    comments: dict[int, list[dict[str, Any]]] = field(default_factory=dict)

    # Each PR is a dict with keys: number, issue_number, branch,
    # ci_status, merged, labels[].
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
    # - ``shape_council``: ``{issue: {"<round_num>": "consensus"|"split"}}`` —
    #   round map consumed by ``ExpertCouncil.vote`` / ``vote_diversified``.
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
        # issue number (JSON string → int). The ``shape_council`` payload's
        # inner-inner key is the round number, also needing string→int.
        if "phase_scripts" in data:
            coerced: dict[str, dict[int, Any]] = {}
            for phase, by_issue in data["phase_scripts"].items():
                inner: dict[int, Any] = {}
                for k, raw_v in by_issue.items():
                    if phase == "shape_council" and isinstance(raw_v, dict):
                        v: Any = {int(rk): rv for rk, rv in raw_v.items()}
                    else:
                        v = raw_v
                    inner[int(k)] = v
                coerced[phase] = inner
            data["phase_scripts"] = coerced
        return cls(**data)
