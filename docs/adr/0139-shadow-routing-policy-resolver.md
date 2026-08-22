# ADR-0139: Shadow routing policy resolver and hash-linked decision record

**Status:** Accepted
**Date:** 2026-08-22
**Enforcement:** enforced
**Binds:** factory
**Supersedes:** none
**Superseded by:** none
**Related:** [ADR-0085](0085-secrets-never-persist-in-audit-stream.md) (the redaction the decision chain writes through), [ADR-0110](0110-provider-harness-backend-split.md) (the provider/harness binding a route resolves to), [ADR-0119](0119-credit-failover-to-glm.md) (one of the legacy mechanisms this observes and does not touch), [ADR-0134](0134-per-repo-model-harness-selection.md) (the per-repo dial this observes and does not touch), [ADR-0137](0137-fenced-issue-driver-and-director-runtime-boundary.md) (`src/driver_contracts.py:WorkerRole` and `ModelRequirement`, the contracts this reuses rather than re-declaring), [ADR-0138](0138-gateway-account-identity-and-sanitized-route-visibility.md) (the account identities, state vocabulary, and zero-disclosure guards this joins to and extends). Design source: `docs/proposals/gateway-routing-control-plane.md` §"P1 — pure policy core and explanation". Issues: #11536 (this phase), #11531 (the epic), #11534 (the phase this builds on), #11538 / #11539 (the phases this unblocks).

**Enforced by:**
pytest:tests/test_routing_policy.py
pytest:tests/test_routing_store.py
pytest:tests/test_routing_audit.py
pytest:tests/test_route_shadow.py
pytest:tests/test_gateway_secret_absence.py
pytest:tests/regressions/test_issue_11536_shadow_route_is_inert.py
pytest:tests/scenarios/test_gateway_route_shadow_scenario.py

**Precedent:** Shadow mode / dark launching — running a new decision path against live traffic and comparing its output with the incumbent's without letting it act (Google SRE's "shadow testing", GitHub's `scientist` library, Twitter's "diffy"). The comparison, not the new path, is the deliverable.
**Divergence:** the classic shadow harness runs the *same* computation twice and diffs the results, so a disagreement is a bug in the candidate. Here the incumbent is a set of hand-maintained dials that were never a policy at all, so a disagreement is frequently the *candidate* being right and the incumbent being undocumented. The record therefore carries the incumbent's own mechanism as a first-class field (`LegacyRoute.mechanism`) rather than treating "legacy" as one opaque baseline: an operator reading a divergence has to be able to tell "policy disagrees with `adr_review_provider=zai`" from "policy disagrees with a credit failover that engaged four minutes ago", because only one of those is a policy gap (receipt: this repo pins six loops to z.ai through per-role dials that no policy describes — `.hydraflow/config.json`, and `docs/proposals/gateway-routing-control-plane.md` §"Precedence and conflict rules" level 9, "compiled legacy role defaults ... during migration only").

## Context

ADR-0138 made accounts and routes *visible*. It deliberately stopped short of eligibility: "this account can satisfy *this* repo, role, request face, and model requirement at *this* policy revision" is a property of a route explanation, and there was no resolver to compute one. Epic #11531's delivery principle is **observe before enforce**, and this phase is the observation that has to come before any enforcement is credible.

Routing today is not one decision seam. It is four mechanisms layered at four spawn sites:

- a per-role `*_provider` dial (`config.adr_review_provider` and its siblings), which this repo currently pins to `zai` for six loops (`wiki_compilation`, `adr_review`, `transcript_summary`, `triage_honeypot`, `term_proposer`, `pr_unstick`);
- `config.repo_provider`, the repo-wide override (ADR-0134);
- `gateway_fleet_ratchet_enabled`, which promotes untouched Claude spawns onto the tap;
- ADR-0119 credit failover, which reroutes to GLM while Anthropic credits are exhausted.

They are applied at **four** spawn seams: `base_runner._execute`, `BaseSubprocessRunner.run`, `runner_utils.run_lightweight_agent`, and `runner_utils.stream_claude_with_telemetry` — the last of which applies the fleet ratchet and is therefore *gateway* transport whenever the ratchet is on, i.e. precisely the traffic a policy could bind. Nothing records *why* a given spawn ended up where it did, nothing can answer "what would a project-X-uses-z.ai policy have changed?", and the z.ai-pinned loops do not reach the gateway at all — they are direct HTTP calls that no gateway policy could bind even if one existed.

Three constraints shape the design:

- **The observation must be provably inert.** A resolver that can change a spawn is not a shadow; it is an unreviewed enforcement path.
- **The explanation must be reconstructible.** A record that says "policy X selected z.ai" without the inputs that produced it cannot be re-checked after the policy is edited, which is precisely when someone will want to.
- **The vocabulary is already fixed.** ADR-0137 owns `WorkerRole` and `ModelRequirement`; ADR-0138 owns account identity and the account state vocabulary. Re-declaring either would guarantee a disagreement later.

## Decision

### D1: The resolver is a pure, total function, and enforcement is not built

`src/hydraflow_gateway/routing_policy.py:explain` maps `(RouteContext, PolicySnapshot)` to exactly one `RouteDecision`. It performs no I/O, reads no clock, holds no state, and **raises on no input**: a corrupt snapshot, an equal-precedence tie, a literal family a policy would answer with GLM, and a capability with no mapping are all typed `held`/`rejected` outcomes carrying a reason code. (An ambiguous repository identity is *not* one of them: it makes every repo-scoped policy fail to match with `repo-identity-not-canonical`, and the decision then falls through to legacy compatibility — refusing the join, not the route. D2 has the detail.)

Totality is not stylistic. The only caller in this phase is an observer standing beside a live spawn, and an exception thrown from a pure core would become a routing incident. `explain_batch` resolves many contexts against **one** snapshot, because an effective-route matrix whose rows saw different revisions is a race rather than a matrix.

There is no enforcement dial and no `v2` mint. A disabled dial for behaviour that does not exist would validate at config load and never route at runtime — the footgun `config.py` already refuses for the agentic role dials. Enforcement arrives with #11539, gated on its own evidence.

### D2: Canonical repository identity is exactly `owner/repo`, and the lossy slug can never join

`RepoIdentity` carries a `version` of `canonical` or `legacy-lossy`. `canonicalize_repo` accepts exactly one slash between two safe path segments and returns `None` for everything else — including a bare runtime slug, which has no slash at all.

This matters because HydraFlow's path-safe slug (`config.repo_slug`) flattens `/` to `-`: **`a-b/c` and `a/b-c` both become `a-b-c`.** Recovering an owner from that slug is a coin flip, and a policy join would then treat the result as fact. So an identity derived from a slug is marked `legacy-lossy`, and `evaluate_match` refuses it against any `repo_ids` set with the code `repo-identity-not-canonical`. A policy that *declares* a non-canonical repo id is rejected at write time (`non-canonical-repo-id`), so the ambiguity cannot enter from either side.

The gateway's existing `MintKeyRequest.repo_slug` carries the lossy form. That is not changed here; it is simply never treated as a policy identity.

### D3: Precedence is earned structurally, and an equal-precedence disagreement is invalid

`precedence_level` derives the design's ladder rung from the *shape* of a policy's match — a rule cannot claim "exact repository + exact role" without naming both. Ordering is `(level, -priority, id)`; a lower level always wins, and priority is the tiebreak inside one level.

Two enabled policies at the same level and priority whose matches overlap and whose actions differ are a **conflict**:

- `validate_policies` reports `equal-precedence-conflict` and `RoutingPolicyStore.save` refuses the write, so the set never reaches a snapshot;
- if one somehow reaches `explain` anyway, the decision is `rejected` with `policy-conflict` and the explanation names every policy that tied.

Insertion order is never the tiebreak. Overlap is computable exactly because v1 matches only on exact sets — the design explicitly defers globs until the conflict model has real evidence, and this is why.

### D4: A literal Opus/Sonnet requirement can never resolve to GLM

Two independent checks, either of which alone would be enough, deliberately kept both:

- **At the account.** A `literal_family` requirement makes every non-Anthropic account ineligible (`literal-family-incompatible`), mapping or no mapping. So a `provider_lock: zai-harness` policy meeting a `claude-opus` request yields `literal-family-unsatisfiable`, not a quiet substitution and not an escape back to Anthropic past the lock.
- **At the model.** Any explicit `requirement_map` entry for a literal family must satisfy `driver_contracts.ModelRequirement.satisfied_by` — ADR-0137's provenance allow-list. A policy mapping `claude-opus → glm-5.3` is rejected at *write* time (`literal-family-mapped-to-foreign-model`), before any spawn can meet it.

A provider-neutral `capability` resolves **only** through an explicit mapping; without one the decision is `held` with `capability-unmapped`. Guessing is how "high-reasoning" silently becomes whichever lane is cheapest.

**The rule governs what a policy may resolve to, not what legacy already did.** A `legacy-compatibility` decision (D7) reports a route that has already happened, and ADR-0119 credit failover genuinely does put a `claude-opus` request on GLM. Reporting that accurately is the divergence signal this phase exists to produce; a resolver that hid it — by holding, or by rewriting the model it reports — would erase the one observation the burn-in needs. `test_no_managed_policy_ever_routes_a_literal_family_off_anthropic` sweeps the whole input matrix for the invariant, and `test_a_legacy_route_that_defies_the_requirement_is_reported_not_suppressed` pins the distinction so the two cannot be conflated later.

### D5: Snapshots are versioned and hashed; an unreadable one holds rather than routing

`RoutingPolicyStore` writes one revision per save through `file_util.atomic_write`, validated first, with an order-independent `content_hash` over the policy set. `load()` returns a typed `SnapshotLoad` whose `state` is `ok`, `absent`, or `corrupt`, and the distinction is load-bearing:

- **absent** is the normal state of a host that has never written a policy, and resolves normally;
- **corrupt** — unparseable, or a `content_hash` that does not match its own contents — yields an *empty* snapshot and a `held` decision with `snapshot-unavailable`.

Collapsing those two into "no policies" is the failure the design names directly: missing or corrupt policy evidence must never present as a coherent state. The hash is also the only thing standing between a hand-edited policy file and a route nobody authorised.

A write **over** a corrupt snapshot is refused (`CorruptSnapshotError`) rather than performed. A corrupt load reports revision 0, so saving through it would restart the counter at 1 and leave two different policy sets both cited as revision 1 on a durable, hash-linked decision chain — silently destroying the one property that makes a decision replayable. Repair is an explicit operator act.

**Writes are not exposed.** `save` exists so the format, the revision counter, and the hash are durable and tested now; there is no HTTP route to it in this phase, and therefore **ADR-0138 §D5 does not apply** — this phase adds no gateway write route, and no new gateway read route, through the dashboard proxy. The first such route (#11538's policy workspace) inherits §D5's precondition unchanged.

### D6: Every shadowed spawn appends one hash-linked, sanitized record

`src/hydraflow_gateway/routing_audit.py:RoutingAuditLog` writes an append-only chain: each record carries `seq`, the previous record's `record_hash`, and a digest binding the two. `verify()` walks the chain and names the first `seq` whose links do not hold, so an edited or removed row is detectable rather than merely unlikely.

Two implementation details make the chain hold *in this repo* rather than in the abstract:

- **The payload is scrubbed before it is hashed.** `file_util.append_jsonl` redacts credential-shaped substrings on the way to disk (ADR-0085). Digesting the pre-scrub payload would produce a chain that fails verification exactly when the redactor fires — a self-inflicted tamper alarm on the one record that most needed to be trustworthy.
- **`prev_hash` is read from disk, not remembered.** A bounded tail seek recovers the chain head, falling back to a full read when a single record outgrew the window, so a restarted process continues one chain instead of forking a private one.

`src/route_shadow.py:ShadowDecision` is the payload: the decision, the route that actually ran, `agreed`, and a `divergence` code. It inherits ADR-0138's zero-disclosure guards by being added to the parametrize lists in `tests/test_gateway_secret_absence.py` — the schema-level credential-shaped-field guard and the AST `get_secret_value` sweep — rather than by growing a second set of guards.

### D7: The legacy mechanism is named, not laundered

When no managed policy claims a context, the decision is `selected` with `policy_source=legacy-compatibility` at rung 9, reporting the caller's own legacy route. It is not `held`: the spawn *is* routed, and a held decision would misdescribe reality.

The record then names *which* legacy mechanism decided it. `route_shadow.classify_legacy_mechanism` walks the ordered stages a seam applied and returns the last one that actually moved the provider — the answer to "why did this spawn go to GLM?" — falling back to the dial it started on when nothing moved it. So an `adr_reviewer` spawn on z.ai records `mechanism=role-dial`, `mechanism_detail=provider=zai`, and `policy_source=legacy-compatibility`. It does not pretend a policy chose it, which is the specific dishonesty this decision exists to prevent.

`transport` is recorded on the same row, and it is derived from the *request face*, not the provider name: at the agentic seam `zai` is the Claude CLI pointed at GLM's Anthropic-shaped endpoint (`harness-direct`), while at the one-shot seam the same name means a direct OpenAI-compatible call (`direct-http`) that never reaches the gateway. The five z.ai-pinned loops are therefore recorded as ungoverned bypass traffic — the measurement #11544 needs and could not previously take.

### D8: The role join is ADR-0138's, with one definition

`routing_policy.canonical_worker_role` is the single exact, case-insensitive match against `driver_contracts.WorkerRole`, and `gateway_control_reader.canonical_worker_role` now delegates to it. ADR-0138 §D6 warned that a fuzzily-guessed role in the observation layer would disagree with the resolver's own answer and read as a routing bug; two copies of the mapping is the same hazard by a slower route. A loop name (`adr_reviewer`) stays `null` on both sides, and policies address such principals through `RoutingMatch.principal_ids` instead.

## Non-goals — what this phase deliberately does not build

**Observe before enforce.** The phase is defined by these.

- **No enforcement, no route-aware mint, no model rewrite.** `resolve-and-mint v2` is #11539. Nothing here returns a route to a caller: `record_route_shadow` returns a record or `None`.
- **No policy writes over HTTP, and no policy UI.** `save` is reachable only in-process. The revision-safe workspace, conflict UI, before/after matrix, and rollback are #11538.
- **No explain/dry-run HTTP endpoints.** The design's P1 lists them; they are not built here. An explain endpoint needs a legacy route as input — which the gateway process does not have, since a direct-Claude spawn never touches it — and its only consumer would be a UI #11538 builds. Speculative surface on an authenticated control plane is worse than none, and `explain`/`explain_batch` are pure functions the workspace can call the moment it exists.
- **No multi-account pools.** `account_pool` and `selection: ordered` are honoured by the resolver so the wire shape is fixed, but the only accounts in existence are ADR-0138's two legacy bindings (#11540).
- **No `forbid_direct_bypass` enforcement.** The field exists and is recorded; nothing acts on it. The bypass it describes is now *measurable*, which is the prerequisite (#11544).
- **No compiled legacy policy entries.** The legacy dials are reported as an input mechanism (D7), not compiled into rung-9 `RoutingPolicy` rows. Compiling them would require a code-owned map from every telemetry source to its dial field, which is a maintained lie the moment a loop is renamed; #11543's retirement work needs the real mapping and can build it against this phase's evidence.
- **No ledger-backed or cross-process decision history.** One chain per repo, written by the one factory process that owns that repo line.

## Consequences

- **Enforcement now has a measurable prerequisite.** #11538 can burn in disagreement rates per repo, role, and mechanism from a durable, verifiable chain rather than from a claim.
- **The decision chain grows without rotation.** One record per spawn, and an append-only hash chain cannot be trimmed without breaking itself. This matches `AppendOnlyJsonlLedger`'s existing behaviour and is accepted for a shadow phase; a rotation scheme that starts a new chain with a documented anchor is the follow-up when volume warrants it.
- **`decision_id` is content-addressed in this phase.** It is a digest of the context, the snapshot hash and revision, and the outcome — so a decision is reproducible from its own record, and two identical contexts under one revision share an id. #11539's mint stamps a per-lease identity on top; it does not replace this one.
- **Shadow recording defaults on.** Observation that does not run is not observation. `gateway_route_shadow_enabled` is the kill switch, live at every seam, and it is checked with `is not True` so a `MagicMock` config in an unrelated test cannot switch it on by being truthy.
- **A bug in the shadow path still surfaces.** The wiring swallows what a sink can plausibly raise (an unwritable data root, a full disk) after `reraise_on_credit_or_bug`, but a genuine `TypeError` propagates, per the house rule. A silently wrong shadow is worse than a loud one, and the inertness of a *working* resolver is pinned separately.
- **HydraFlow's local account view is conservative and says so.** `route_shadow.local_account_availability` reports what this host can see — the credential the legacy router itself gates on — not the gateway's own upstream configuration. ADR-0138's `GET /control/v2/accounts` remains authoritative, and every decision records the accounts it actually used, so the verdict stays reconstructible.

## Alternatives considered

- **Wire the resolver into the spawn path behind a default-off enforcement flag.** Rejected: a flag is one edit away from being flipped by someone who has not read the divergence data, and the code path would be live-but-untested in exactly the way ADR-0051's review discipline exists to prevent. Enforcement gets its own phase and its own canary.
- **Generate a non-deterministic `decision_id` (ULID) per resolve.** Rejected for a pure core: it would make `explain` impure, and it would make a decision impossible to re-derive from its record — the one property that turns a log into an audit. The lease-scoped identity #11539 needs is a *different* id, minted where the lease is.
- **Compile the legacy dials into rung-9 policies so everything routes "through policy".** Rejected as the dishonesty D7 exists to prevent. The dials key on telemetry sources and config field names, not on ADR-0137 roles, so the compilation would need a hand-maintained source→dial table that silently rots on the next loop rename — and every shadow decision would then cite a policy that does not exist.
- **Record only divergences, plus a sample of agreements.** Cheaper, and tempting. Rejected: "every governed spawn records" is what makes an agreement rate a rate rather than an anecdote, and a sampled denominator cannot answer "did any project-X spawn escape the policy domain today?".
- **Put the policy snapshot in the gateway and have HydraFlow read it over HTTP per spawn.** Rejected for this phase: it makes every spawn depend on a reachable gateway to record an observation that must never affect the spawn, and the gateway container and the factory host do not share a filesystem. One authority is established with the first write route (#11538), where it belongs.
- **Skip the hash chain and write a plain JSONL log.** Rejected: the enforcement phases will be asked *why* a spawn was routed where it was, long after the deciding process exited. A log that cannot distinguish "this is what we decided" from "this is what someone later wrote down" is not evidence.
