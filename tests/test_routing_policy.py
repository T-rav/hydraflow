"""The pure routing-policy core: identity, precedence, compatibility, explanation.

Every test here runs against :func:`explain` with no I/O, no clock, and no
patching — the point of a pure decision core is that its whole behaviour is a
function of its arguments.
"""

from __future__ import annotations

import pytest

from driver_contracts import ModelRequirement, ModelRequirementKind, WorkerRole
from hydraflow_gateway.accounts import AdministrativeState
from hydraflow_gateway.models import ProviderBinding, RepoClass
from hydraflow_gateway.routing_policy import (
    AccountAvailability,
    AccountRejectionReason,
    DecisionOutcome,
    DecisionReason,
    LegacyRoute,
    LegacyRouteMechanism,
    MatchReason,
    OnUnavailable,
    PolicySnapshot,
    PolicySource,
    PolicyValidationCode,
    PrecedenceLevel,
    RepoIdentity,
    RepoIdentityVersion,
    RequestFace,
    RequirementMapping,
    RouteContext,
    RouteTransport,
    RoutingAction,
    RoutingMatch,
    RoutingPolicy,
    SnapshotState,
    canonical_worker_role,
    canonicalize_repo,
    explain,
    explain_batch,
    hash_policies,
    matches_overlap,
    precedence_level,
    validate_policies,
)

_ANTHROPIC = AccountAvailability(
    account_id="legacy-anthropic",
    provider_binding=ProviderBinding.ANTHROPIC,
    configured=True,
)
_ZAI = AccountAvailability(
    account_id="legacy-zai-harness",
    provider_binding=ProviderBinding.ZAI_HARNESS,
    configured=True,
)

_CONCRETE_GLM = ModelRequirement(
    kind=ModelRequirementKind.CONCRETE_MODEL, value="glm-5.2"
)
_LITERAL_OPUS = ModelRequirement(
    kind=ModelRequirementKind.LITERAL_FAMILY, value="claude-opus"
)
_HIGH_REASONING = ModelRequirement(
    kind=ModelRequirementKind.CAPABILITY, value="high-reasoning"
)

_LEGACY = LegacyRoute(
    provider_binding=ProviderBinding.ANTHROPIC,
    account_id="legacy-anthropic",
    model="claude-opus-4-8",
    transport=RouteTransport.GATEWAY,
    mechanism=LegacyRouteMechanism.DEFAULT,
    mechanism_detail="default=claude",
)


def _context(**overrides: object) -> RouteContext:
    base: dict[str, object] = {
        "repo": RepoIdentity.from_canonical("acme/project-x"),
        "repo_class": RepoClass.CLIENT,
        "principal_id": "implementer",
        "worker_role": WorkerRole.IMPLEMENTER,
        "model_requirement": _CONCRETE_GLM,
        "request_face": RequestFace.AGENTIC,
        "accounts": (_ANTHROPIC, _ZAI),
        "legacy_route": _LEGACY,
    }
    base.update(overrides)
    return RouteContext(**base)  # type: ignore[arg-type]


def _snapshot(*policies: RoutingPolicy) -> PolicySnapshot:
    return PolicySnapshot(
        revision=7, policies=policies, content_hash=hash_policies(policies)
    )


def _zai_lock(
    policy_id: str = "project-x-zai",
    *,
    priority: int = 100,
    enabled: bool = True,
    **overrides: object,
) -> RoutingPolicy:
    action: dict[str, object] = {
        "provider_lock": ProviderBinding.ZAI_HARNESS,
        "requirement_map": (
            RequirementMapping(requirement=_HIGH_REASONING, effective_model="glm-5.3"),
        ),
        "allowed_patterns": ("glm-*",),
    }
    action.update(overrides)
    return RoutingPolicy(
        id=policy_id,
        enabled=enabled,
        priority=priority,
        match=RoutingMatch(repo_ids=("acme/project-x",)),
        action=RoutingAction(**action),  # type: ignore[arg-type]
    )


# --- Canonical repository identity ------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("Acme/Project-X", "acme/project-x", id="normalises-case"),
        pytest.param("a-b/c", "a-b/c", id="hyphen-in-owner-survives"),
        pytest.param("a/b-c", "a/b-c", id="hyphen-in-name-survives"),
    ],
)
def test_canonicalize_repo_accepts_an_exact_owner_repo(
    value: str, expected: str
) -> None:
    """Exactly one slash between two safe segments is the whole grammar."""
    assert canonicalize_repo(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("acme-project-x", id="a-runtime-slug-has-no-owner"),
        pytest.param("acme/project/x", id="two-slashes-is-not-owner-repo"),
        pytest.param("acme/../etc", id="path-traversal"),
        pytest.param("/project", id="empty-owner"),
        pytest.param("", id="empty"),
    ],
)
def test_canonicalize_repo_fails_closed_on_anything_ambiguous(value: str) -> None:
    """Ambiguity returns None rather than a guess a policy would treat as fact."""
    assert canonicalize_repo(value) is None


def test_two_distinct_repos_collide_on_the_lossy_runtime_slug() -> None:
    """The collision this phase exists to refuse to paper over."""
    left = RepoIdentity.from_canonical("a-b/c")
    right = RepoIdentity.from_canonical("a/b-c")

    assert left.runtime_slug == right.runtime_slug


def test_an_identity_recovered_from_a_runtime_slug_is_marked_legacy_lossy() -> None:
    """A slug cannot name an owner, so the identity says it does not know one."""
    identity = RepoIdentity.from_runtime_slug("a-b-c")

    assert identity.version is RepoIdentityVersion.LEGACY_LOSSY


def test_a_legacy_lossy_identity_never_satisfies_an_exact_repo_policy() -> None:
    """The collision cannot become a routing decision."""
    decision = explain(
        _context(repo=RepoIdentity.from_runtime_slug("acme-project-x")),
        _snapshot(_zai_lock()),
    )

    assert decision.explanation.considered[0].reason is (
        MatchReason.REPO_IDENTITY_NOT_CANONICAL
    )


def test_a_non_canonical_repo_id_in_a_policy_is_a_validation_error() -> None:
    """A policy cannot declare a repo identity the resolver could never match."""
    policy = RoutingPolicy(id="bad", match=RoutingMatch(repo_ids=("acme-project-x",)))

    codes = [issue.code for issue in validate_policies([policy])]

    assert PolicyValidationCode.NON_CANONICAL_REPO_ID in codes


# --- The canonical role join ------------------------------------------------


def test_canonical_worker_role_matches_the_adr_0137_catalog_exactly() -> None:
    """The vocabulary is ADR-0137's; this module does not extend it."""
    assert canonical_worker_role("Implementer") is WorkerRole.IMPLEMENTER


def test_canonical_worker_role_refuses_to_guess_a_loop_name_into_a_role() -> None:
    """``adr_reviewer`` is a loop, not a worker role, and stays unmapped."""
    assert canonical_worker_role("adr_reviewer") is None


# --- Precedence -------------------------------------------------------------


@pytest.mark.parametrize(
    ("match", "expected"),
    [
        pytest.param(
            RoutingMatch(
                repo_ids=("a/b",),
                roles=(WorkerRole.IMPLEMENTER,),
                model_requirements=(_CONCRETE_GLM,),
            ),
            PrecedenceLevel.REPO_ROLE_REQUIREMENT,
            id="repo-role-requirement",
        ),
        pytest.param(
            RoutingMatch(repo_ids=("a/b",), roles=(WorkerRole.IMPLEMENTER,)),
            PrecedenceLevel.REPO_ROLE,
            id="repo-role",
        ),
        pytest.param(
            RoutingMatch(repo_ids=("a/b",)),
            PrecedenceLevel.REPO_ANY_ROLE,
            id="repo-any-role",
        ),
        pytest.param(
            RoutingMatch(
                repo_classes=(RepoClass.CLIENT,), roles=(WorkerRole.IMPLEMENTER,)
            ),
            PrecedenceLevel.CLASS_ROLE,
            id="class-role",
        ),
        pytest.param(
            RoutingMatch(repo_classes=(RepoClass.CLIENT,)),
            PrecedenceLevel.CLASS_DEFAULT,
            id="class-default",
        ),
        pytest.param(
            RoutingMatch(roles=(WorkerRole.IMPLEMENTER,)),
            PrecedenceLevel.GLOBAL_ROLE_OR_REQUIREMENT,
            id="global-role",
        ),
        pytest.param(
            RoutingMatch(), PrecedenceLevel.GLOBAL_DEFAULT, id="global-default"
        ),
    ],
)
def test_precedence_is_earned_by_the_shape_of_the_match(
    match: RoutingMatch, expected: PrecedenceLevel
) -> None:
    """Specificity is structural — a policy cannot claim a rung it did not name."""
    assert precedence_level(RoutingPolicy(id="p", match=match)) is expected


def test_a_system_safety_rule_outranks_an_exact_project_route() -> None:
    """The design's one carve-out: only an explicit safety rule beats level 2."""
    policy = RoutingPolicy(
        id="safety", system_safety=True, match=RoutingMatch(repo_ids=("a/b",))
    )

    assert precedence_level(policy) is PrecedenceLevel.SYSTEM_SAFETY


def test_a_more_specific_policy_wins_over_a_broader_one() -> None:
    """An exact-repo rule beats a global default regardless of priority."""
    decision = explain(
        _context(model_requirement=_HIGH_REASONING),
        _snapshot(
            _zai_lock("exact"),
            RoutingPolicy(
                id="global",
                priority=9_000,
                action=RoutingAction(provider_lock=ProviderBinding.ANTHROPIC),
            ),
        ),
    )

    assert decision.policy_id == "exact"


def test_the_outranked_policy_is_explained_as_outranked_not_as_unmatched() -> None:
    """An operator asking "why not mine?" gets ``outranked``, not silence."""
    decision = explain(
        _context(model_requirement=_HIGH_REASONING),
        _snapshot(
            _zai_lock("exact"),
            RoutingPolicy(
                id="global",
                action=RoutingAction(provider_lock=ProviderBinding.ANTHROPIC),
            ),
        ),
    )
    reasons = {item.policy_id: item.reason for item in decision.explanation.considered}

    assert reasons["global"] is MatchReason.OUTRANKED


def test_higher_priority_wins_inside_one_precedence_level() -> None:
    """Within a rung, the numeric priority is the tiebreak."""
    decision = explain(
        _context(model_requirement=_HIGH_REASONING),
        _snapshot(
            _zai_lock("low", priority=10, provider_lock=ProviderBinding.ANTHROPIC),
            _zai_lock(),
        ),
    )

    assert decision.policy_id == "project-x-zai"


# --- Conflicts --------------------------------------------------------------


def test_equal_precedence_policies_that_disagree_are_rejected_at_write_time() -> None:
    """The store refuses the set rather than relying on insertion order."""
    codes = [
        issue.code
        for issue in validate_policies(
            [_zai_lock("a"), _zai_lock("b", provider_lock=ProviderBinding.ANTHROPIC)]
        )
    ]

    assert PolicyValidationCode.EQUAL_PRECEDENCE_CONFLICT in codes


def test_a_conflict_that_reaches_the_resolver_rejects_rather_than_guessing() -> None:
    """Fail closed: there is no defensible answer, so there is no answer."""
    decision = explain(
        _context(model_requirement=_HIGH_REASONING),
        _snapshot(
            _zai_lock("a"), _zai_lock("b", provider_lock=ProviderBinding.ANTHROPIC)
        ),
    )

    assert decision.reason is DecisionReason.POLICY_CONFLICT


def test_a_rejected_conflict_names_every_policy_that_tied() -> None:
    """The explanation has to be actionable, so it names both sides."""
    decision = explain(
        _context(model_requirement=_HIGH_REASONING),
        _snapshot(
            _zai_lock("a"), _zai_lock("b", provider_lock=ProviderBinding.ANTHROPIC)
        ),
    )

    assert decision.explanation.conflicting_policy_ids == ("a", "b")


def test_equal_precedence_policies_that_agree_are_not_a_conflict() -> None:
    """Two identical actions have one answer, so there is nothing to reject."""
    assert validate_policies([_zai_lock("a"), _zai_lock("b")]) == ()


def test_non_overlapping_matches_at_equal_precedence_are_not_a_conflict() -> None:
    """Two rules that can never both apply cannot disagree."""
    left = _zai_lock("a")
    right = RoutingPolicy(
        id="b",
        priority=100,
        match=RoutingMatch(repo_ids=("other/repo",)),
        action=RoutingAction(provider_lock=ProviderBinding.ANTHROPIC),
    )

    assert validate_policies([left, right]) == ()


def test_matches_overlap_treats_an_empty_dimension_as_the_universe() -> None:
    """An omitted dimension means *any*, so it intersects everything."""
    assert matches_overlap(RoutingMatch(), RoutingMatch(repo_ids=("a/b",)))


def test_a_duplicate_policy_id_is_a_validation_error() -> None:
    """Two rules with one name cannot be told apart in an audit trail."""
    codes = [
        issue.code for issue in validate_policies([_zai_lock("a"), _zai_lock("a")])
    ]

    assert PolicyValidationCode.DUPLICATE_POLICY_ID in codes


# --- Model compatibility ----------------------------------------------------


def test_a_literal_opus_request_can_never_be_served_by_a_zai_account() -> None:
    """The epic's named hazard: Opus must not silently become GLM."""
    decision = explain(
        _context(model_requirement=_LITERAL_OPUS), _snapshot(_zai_lock())
    )

    assert decision.reason is DecisionReason.LITERAL_FAMILY_UNSATISFIABLE


def test_a_literal_opus_request_blocked_by_a_zai_lock_yields_no_route() -> None:
    """Refusing is the point; there is no Anthropic escape hatch behind it."""
    decision = explain(
        _context(model_requirement=_LITERAL_OPUS), _snapshot(_zai_lock())
    )

    assert decision.account_id is None


def test_a_zai_account_is_rejected_for_a_literal_family_with_a_reason_code() -> None:
    """The explanation names the account and why it could not serve."""
    decision = explain(
        _context(model_requirement=_LITERAL_OPUS), _snapshot(_zai_lock())
    )
    reasons = {
        item.account_id: item.reason for item in decision.explanation.rejected_accounts
    }

    assert reasons["legacy-zai-harness"] is (
        AccountRejectionReason.LITERAL_FAMILY_INCOMPATIBLE
    )


def test_a_policy_mapping_a_literal_family_to_glm_is_rejected_at_write_time() -> None:
    """The dishonest mapping never reaches a snapshot in the first place."""
    policy = _zai_lock(
        requirement_map=(
            RequirementMapping(requirement=_LITERAL_OPUS, effective_model="glm-5.3"),
        )
    )

    codes = [issue.code for issue in validate_policies([policy])]

    assert PolicyValidationCode.LITERAL_FAMILY_MAPPED_TO_FOREIGN_MODEL in codes


def test_a_capability_request_resolves_only_through_an_explicit_mapping() -> None:
    """``high-reasoning`` means whatever policy says it means — and nothing else."""
    decision = explain(
        _context(model_requirement=_HIGH_REASONING), _snapshot(_zai_lock())
    )

    assert decision.effective_model == "glm-5.3"


def test_a_capability_with_no_mapping_is_held_rather_than_guessed() -> None:
    """Guessing is how "high-reasoning" silently becomes the cheapest lane."""
    decision = explain(
        _context(model_requirement=_HIGH_REASONING),
        _snapshot(_zai_lock(requirement_map=())),
    )

    assert decision.reason is DecisionReason.CAPABILITY_UNMAPPED


def test_a_held_capability_is_held_not_rejected() -> None:
    """Hold and reject are different instructions to the caller."""
    decision = explain(
        _context(model_requirement=_HIGH_REASONING),
        _snapshot(_zai_lock(requirement_map=())),
    )

    assert decision.outcome is DecisionOutcome.HELD


def test_a_concrete_model_outside_the_allowed_patterns_is_rejected() -> None:
    """``allowed_patterns`` is a fence, not a hint."""
    decision = explain(
        _context(
            model_requirement=ModelRequirement(
                kind=ModelRequirementKind.CONCRETE_MODEL, value="kimi-k3"
            )
        ),
        _snapshot(_zai_lock()),
    )

    assert decision.reason is DecisionReason.MODEL_NOT_ALLOWED


def test_a_mapped_model_outside_the_allowed_patterns_is_a_validation_error() -> None:
    """A policy may not fence itself out of its own mapping."""
    policy = _zai_lock(
        requirement_map=(
            RequirementMapping(requirement=_HIGH_REASONING, effective_model="kimi-k3"),
        )
    )

    codes = [issue.code for issue in validate_policies([policy])]

    assert PolicyValidationCode.MAPPED_MODEL_NOT_IN_ALLOWED_PATTERNS in codes


# --- Account eligibility ----------------------------------------------------


def test_eligibility_lives_inside_the_explanation_where_adr_0138_put_it() -> None:
    """Never an account-global field — always a property of one route."""
    decision = explain(
        _context(model_requirement=_HIGH_REASONING), _snapshot(_zai_lock())
    )

    assert decision.explanation.eligible_account_ids == ("legacy-zai-harness",)


@pytest.mark.parametrize(
    ("account", "expected"),
    [
        pytest.param(
            AccountAvailability(
                account_id="legacy-zai-harness",
                provider_binding=ProviderBinding.ZAI_HARNESS,
                configured=False,
            ),
            AccountRejectionReason.NOT_CONFIGURED,
            id="unconfigured",
        ),
        pytest.param(
            AccountAvailability(
                account_id="legacy-zai-harness",
                provider_binding=ProviderBinding.ZAI_HARNESS,
                configured=True,
                administrative_state=AdministrativeState.DRAINING,
            ),
            AccountRejectionReason.ADMINISTRATIVE_DRAINING,
            id="draining",
        ),
        pytest.param(
            AccountAvailability(
                account_id="legacy-zai-harness",
                provider_binding=ProviderBinding.ZAI_HARNESS,
                configured=True,
                administrative_state=AdministrativeState.DISABLED,
            ),
            AccountRejectionReason.ADMINISTRATIVE_DISABLED,
            id="disabled",
        ),
    ],
)
def test_an_ineligible_account_is_rejected_with_its_own_reason_code(
    account: AccountAvailability, expected: AccountRejectionReason
) -> None:
    """Each independent fact produces its own code, never one merged badge."""
    decision = explain(
        _context(model_requirement=_HIGH_REASONING, accounts=(account,)),
        _snapshot(_zai_lock()),
    )
    reasons = {
        item.account_id: item.reason for item in decision.explanation.rejected_accounts
    }

    assert reasons["legacy-zai-harness"] is expected


def test_an_account_outside_the_provider_lock_is_rejected_for_the_lock() -> None:
    """A locked policy names why the other lane did not qualify."""
    decision = explain(
        _context(model_requirement=_HIGH_REASONING), _snapshot(_zai_lock())
    )
    reasons = {
        item.account_id: item.reason for item in decision.explanation.rejected_accounts
    }

    assert reasons["legacy-anthropic"] is AccountRejectionReason.PROVIDER_LOCK_MISMATCH


def test_an_ordered_account_pool_is_honoured_in_its_declared_order() -> None:
    """``selection: ordered`` means the pool's order, not alphabetical order."""
    extra = AccountAvailability(
        account_id="zai-secondary",
        provider_binding=ProviderBinding.ZAI_HARNESS,
        configured=True,
    )
    decision = explain(
        _context(model_requirement=_HIGH_REASONING, accounts=(_ANTHROPIC, _ZAI, extra)),
        _snapshot(_zai_lock(account_pool=("zai-secondary", "legacy-zai-harness"))),
    )

    assert decision.account_id == "zai-secondary"


def test_no_eligible_account_holds_by_default() -> None:
    """``on_unavailable: hold`` is the safe default and it is honoured."""
    unconfigured = AccountAvailability(
        account_id="legacy-zai-harness",
        provider_binding=ProviderBinding.ZAI_HARNESS,
        configured=False,
    )
    decision = explain(
        _context(model_requirement=_HIGH_REASONING, accounts=(unconfigured,)),
        _snapshot(_zai_lock()),
    )

    assert decision.reason is DecisionReason.NO_ELIGIBLE_ACCOUNT


def test_a_policy_asking_to_reject_on_unavailable_rejects_instead_of_holding() -> None:
    """Hold versus reject is the policy author's call, and it is respected."""
    unconfigured = AccountAvailability(
        account_id="legacy-zai-harness",
        provider_binding=ProviderBinding.ZAI_HARNESS,
        configured=False,
    )
    decision = explain(
        _context(model_requirement=_HIGH_REASONING, accounts=(unconfigured,)),
        _snapshot(_zai_lock(on_unavailable=OnUnavailable.REJECT)),
    )

    assert decision.outcome is DecisionOutcome.REJECTED


# --- The "no policy applies" path -------------------------------------------


def test_no_managed_policy_reports_the_legacy_route_as_the_authority() -> None:
    """The truth about an unpoliced spawn, not a pretence that policy chose it."""
    decision = explain(_context(), PolicySnapshot.empty())

    assert decision.policy_source is PolicySource.LEGACY_COMPATIBILITY


def test_no_managed_policy_still_produces_a_selected_decision() -> None:
    """The spawn *is* routed; a held decision here would misdescribe reality."""
    decision = explain(_context(), PolicySnapshot.empty())

    assert decision.outcome is DecisionOutcome.SELECTED


def test_no_managed_policy_reports_the_lowest_precedence_rung() -> None:
    """Legacy compatibility is rung 9 — below every managed rule."""
    decision = explain(_context(), PolicySnapshot.empty())

    assert decision.precedence_level is PrecedenceLevel.LEGACY_COMPATIBILITY


def test_no_policy_and_no_legacy_route_is_held_not_invented() -> None:
    """A dry-run with no legacy input has nothing to report, and says so."""
    decision = explain(_context(legacy_route=None), PolicySnapshot.empty())

    assert decision.reason is DecisionReason.NO_LEGACY_ROUTE


# --- Snapshot trust ---------------------------------------------------------


def test_a_corrupt_snapshot_holds_rather_than_routing_as_if_unpoliced() -> None:
    """ "Unreadable" and "no policy written" are different facts."""
    decision = explain(
        _context(), PolicySnapshot.empty(), snapshot_state=SnapshotState.CORRUPT
    )

    assert decision.reason is DecisionReason.SNAPSHOT_UNAVAILABLE


def test_a_corrupt_snapshot_never_names_a_policy_source() -> None:
    """Nothing was consulted, so nothing may be cited."""
    decision = explain(
        _context(), PolicySnapshot.empty(), snapshot_state=SnapshotState.CORRUPT
    )

    assert decision.policy_source is PolicySource.NONE


def test_an_absent_snapshot_resolves_normally() -> None:
    """A host that never wrote a policy is the ordinary case, not a fault."""
    decision = explain(
        _context(), PolicySnapshot.empty(), snapshot_state=SnapshotState.ABSENT
    )

    assert decision.outcome is DecisionOutcome.SELECTED


# --- The record is self-sufficient ------------------------------------------


def test_the_decision_echoes_its_whole_input_context() -> None:
    """An explanation that cannot be reconstructed from its inputs is not one."""
    context = _context()

    assert explain(context, PolicySnapshot.empty()).explanation.context == context


def test_the_decision_cites_the_exact_revision_it_resolved_against() -> None:
    """A decision without a revision cannot be replayed later."""
    decision = explain(
        _context(model_requirement=_HIGH_REASONING), _snapshot(_zai_lock())
    )

    assert decision.policy_revision == 7


def test_the_decision_cites_the_snapshot_content_hash() -> None:
    """The revision number alone does not prove *which* policies were in force."""
    snapshot = _snapshot(_zai_lock())
    decision = explain(_context(model_requirement=_HIGH_REASONING), snapshot)

    assert decision.snapshot_hash == snapshot.content_hash


def test_the_same_inputs_produce_the_same_decision_id() -> None:
    """The id is content-addressed, so a decision is reproducible from its record."""
    snapshot = _snapshot(_zai_lock())
    first = explain(_context(model_requirement=_HIGH_REASONING), snapshot)
    second = explain(_context(model_requirement=_HIGH_REASONING), snapshot)

    assert first.decision_id == second.decision_id


def test_a_different_outcome_produces_a_different_decision_id() -> None:
    """Two different answers must not share one identity."""
    snapshot = _snapshot(_zai_lock())
    selected = explain(_context(model_requirement=_HIGH_REASONING), snapshot)
    blocked = explain(_context(model_requirement=_LITERAL_OPUS), snapshot)

    assert selected.decision_id != blocked.decision_id


def test_hash_policies_is_independent_of_declaration_order() -> None:
    """Reordering a policy file is not a policy change."""
    left, right = _zai_lock("a"), _zai_lock("b")

    assert hash_policies([left, right]) == hash_policies([right, left])


# --- Batch explain ----------------------------------------------------------


def test_explain_batch_returns_one_decision_per_context() -> None:
    """Exactly one decision per resolve attempt, batched or not."""
    contexts = [_context(), _context(model_requirement=_HIGH_REASONING)]

    assert len(explain_batch(contexts, _snapshot(_zai_lock()))) == 2


def test_explain_batch_resolves_every_row_against_one_revision() -> None:
    """A matrix whose rows saw different revisions is a race, not a matrix."""
    snapshot = _snapshot(_zai_lock())
    decisions = explain_batch(
        [_context(), _context(model_requirement=_HIGH_REASONING)], snapshot
    )

    assert {decision.snapshot_hash for decision in decisions} == {snapshot.content_hash}


def test_explain_batch_over_no_contexts_returns_nothing() -> None:
    """An empty matrix is empty, not an error."""
    assert explain_batch([], PolicySnapshot.empty()) == ()


# --- Match dimensions -------------------------------------------------------


def test_a_disabled_policy_is_considered_and_reported_as_disabled() -> None:
    """Disabling is visible in the trace, not an erasure."""
    decision = explain(_context(), _snapshot(_zai_lock(enabled=False)))

    assert decision.explanation.considered[0].reason is MatchReason.POLICY_DISABLED


def test_a_role_scoped_policy_skips_a_principal_with_no_canonical_role() -> None:
    """ADR-0138 §D6: an unmapped principal is not quietly matched."""
    policy = RoutingPolicy(
        id="role-only",
        match=RoutingMatch(roles=(WorkerRole.REVIEWER,)),
        action=RoutingAction(provider_lock=ProviderBinding.ANTHROPIC),
    )
    decision = explain(
        _context(principal_id="adr_reviewer", worker_role=None), _snapshot(policy)
    )

    assert decision.explanation.considered[0].reason is MatchReason.ROLE_NOT_CANONICAL


def test_a_principal_scoped_policy_matches_the_raw_loop_name() -> None:
    """Loops that are not ADR-0137 roles are still addressable, by principal."""
    policy = RoutingPolicy(
        id="loop-scoped",
        match=RoutingMatch(principal_ids=("adr_reviewer",)),
        action=RoutingAction(provider_lock=ProviderBinding.ANTHROPIC),
    )
    decision = explain(
        _context(
            principal_id="adr_reviewer",
            worker_role=None,
            model_requirement=_HIGH_REASONING,
            legacy_route=None,
        ),
        _snapshot(policy),
    )

    assert decision.policy_id == "loop-scoped"


def test_a_request_face_outside_the_policy_s_set_does_not_match() -> None:
    """A policy written for agentic traffic does not silently claim one-shots."""
    policy = RoutingPolicy(
        id="agentic-only",
        match=RoutingMatch(request_faces=(RequestFace.AGENTIC,)),
        action=RoutingAction(provider_lock=ProviderBinding.ANTHROPIC),
    )
    decision = explain(_context(request_face=RequestFace.ONE_SHOT), _snapshot(policy))

    assert decision.explanation.considered[0].reason is (
        MatchReason.REQUEST_FACE_NOT_IN_SET
    )


def test_a_repo_class_outside_the_policy_s_set_does_not_match() -> None:
    """Class scoping is exact, like every other dimension."""
    policy = RoutingPolicy(
        id="hydraflow-only",
        match=RoutingMatch(repo_classes=(RepoClass.HYDRAFLOW,)),
        action=RoutingAction(provider_lock=ProviderBinding.ANTHROPIC),
    )
    decision = explain(_context(repo_class=RepoClass.CLIENT), _snapshot(policy))

    assert decision.explanation.considered[0].reason is (
        MatchReason.REPO_CLASS_NOT_IN_SET
    )
