# ADR-0140: Revision-safe policy workspace and the operator write boundary

**Status:** Accepted
**Date:** 2026-08-22
**Enforcement:** enforced
**Binds:** factory
**Supersedes:** none
**Superseded by:** none
**Related:** [ADR-0085](0085-secrets-never-persist-in-audit-stream.md) (the redaction the mutation chain writes through, and the redaction the *snapshot* deliberately does not have), [ADR-0021](0021-persistence-architecture-and-data-layout.md) (the per-repo data root this writes under), [ADR-0137](0137-fenced-issue-driver-and-director-runtime-boundary.md) (`src/driver_contracts.py:WorkerRole` and `ModelRequirement`, the matrix axes), [ADR-0138](0138-gateway-account-identity-and-sanitized-route-visibility.md) (§D5's write-route precondition, spent here; §D4's zero-disclosure guards, extended here), [ADR-0139](0139-shadow-routing-policy-resolver.md) (the pure resolver, the durable snapshot, and the hash-linked chain this adds concurrency and provenance to). Design source: `docs/proposals/gateway-routing-control-plane.md` §"P2 — policy UI and shadow burn-in". Issues: #11538 (this phase), #11531 (the epic), #11536 (the phase this builds on), #11539 (the enforcement canary this unblocks).

**Enforced by:**
pytest:tests/test_routing_workspace.py
pytest:tests/test_routing_matrix.py
pytest:tests/test_operator_identity.py
pytest:tests/test_dashboard_gateway_policy_routes.py
pytest:tests/test_gateway_secret_absence.py
pytest:tests/scenarios/test_gateway_policy_workspace_scenario.py

**Precedent:** Optimistic concurrency control with a write-ahead intent log — the pairing of a compare-and-set on a version with a durable record of what was about to happen, so recovery is a decision rather than a guess (Kung & Robinson, "On Optimistic Methods for Concurrency Control", 1981; ARIES-style WAL, Mohan et al., 1992; HTTP's `If-Match`/412 as the same idea over a network).
**Divergence:** classical OCC validates at *commit* time and retries the loser automatically, because the loser is a machine with the same intent. Here the loser is a person whose intent may have been invalidated by what the winner did — an auto-retried policy save could silently re-apply an edit written against a route matrix that no longer exists. So the conflict is returned to the operator with the revision that won and is never retried on their behalf (receipt: `docs/proposals/gateway-routing-control-plane.md` §"Failure and security behavior" — "Concurrent policy edit → 409 on stale revision, no lost update" beside "Policy changes with active keys → existing immutable decisions continue", and ADR-0138 §D5's precondition on this route). The write-ahead journal likewise resolves *one* slot rather than replaying a log: at most one policy transaction is ever open, because a second concurrent operator write is refused by the same advisory lock that serialises the first.

## Context

ADR-0139 built the policy core and said plainly what it left out: `RoutingPolicyStore.save` was reachable only in-process, so the snapshot format, the revision counter, and the content hash were durable and tested *ahead of* the workspace that would expose them. Two things were therefore still missing before an operator could define "project X always uses z.ai":

1. **A write path with concurrency and provenance.** The format did not need inventing; a second tab and an authenticated actor did.
2. **A boundary that makes a write safe to expose.** ADR-0138 §D5 recorded that HydraFlow's dashboard has no in-process authentication and that its operator boundary *is* the loopback socket bind — acceptable while every routing route was read-only and every payload non-secret, and explicitly a **precondition on the first write route**. This is that route.

There is also a fact about the code that the issue's prose predates. #11538 was written expecting gateway policy mutation endpoints proxied from the dashboard. ADR-0139 put the snapshot on the **HydraFlow side, under the repository's own data root** (`route_shadow.policy_snapshot_path`), because that is where the shadow resolver reads it at spawn time and because the gateway container and the factory host share no filesystem — and it recorded that "one authority is established with the first write route (#11538), where it belongs." This ADR establishes it, and it follows the code rather than the prose: the write plane lands where the read plane already is.

Three constraints shape everything below:

- **"Revision-safe" is a claim about failures, not successes.** A policy edit must never leave a concurrent reader looking at half a revision, and a *rejected* edit must leave the previous revision exactly as it was.
- **A mutation and its audit record are one fact.** A revision with no record is unexplainable; a record with no revision is a lie.
- **The chain is the history.** Rollback has no other source of truth to restore from, which makes chain verification a write-time precondition rather than a diagnostic.

## Decision

### D1: The policy authority is per-repository and HydraFlow-side; the write plane is not a proxy

`src/dashboard_routes/_gateway_policy_routes.py` serves five endpoints under `/api/gateway/policies` — four reads and exactly one write — against `hydraflow_gateway.routing_workspace.PolicyWorkspace`, which owns the same `routing/` directory the shadow resolver already reads (`route_shadow.routing_dir`). No gateway HTTP route is added, and none is called: `git diff` over `src/hydraflow_gateway/app.py` is empty for this phase.

This is one authority rather than two. A gateway-side policy store would have to be per-repository on a host-global deployable, would put a network round trip inside the path a shadow observation must never disturb, and would need a second revision counter kept in step with the one the decision chain already cites. The scenario pins the property that makes it worth having: `test_the_write_lands_where_the_shadow_resolver_reads` writes through the HTTP plane and the next **real** spawn resolves against that revision, with no restart and no reload.

When #11539 arms enforcement inside the gateway, the snapshot moves with a documented migration; nothing about the *format* changes, because ADR-0139 already fixed it.

### D2: The write plane is gated on a loopback bind AND an authenticated operator, in that order

`src/operator_identity.py:write_gate` returns `enabled`, or one of three named refusals. The order the refusals are reported in is the decision:

| Gate | Means | Status |
|---|---|---|
| `workspace-disabled` | `gateway_policy_workspace_enabled` is off — the blunt switch an operator set deliberately. | 403 |
| `dashboard-not-loopback` | `config.dashboard_host` is reachable from another machine. **No credential overrides this.** | 403 |
| `no-operator-identity` | `HYDRAFLOW_OPERATOR_TOKEN` is unset on this host, so writes are off by default. | 403 |
| (open, credential wrong or absent) | The bearer token did not match. | 401 |

The two conditions are independent, and `test_a_valid_operator_token_cannot_write_past_a_non_loopback_bind` is the test that keeps them that way: the credential says *who is asking*, the bind says *who can ask*, and only the second is a property of the socket. Reporting the bind first is not cosmetic either — it is the thing an operator has to fix before the credential means anything.

**The bind is host business; the kill switch is not.** `dashboard_host` describes one socket for the whole dashboard, so it is read from the host config — a per-repository runtime's copy of it would be a second answer to a question the operating system already answered once. `gateway_policy_workspace_enabled`, however, is a per-repository editable setting, and an operator who turns it off for one repository has to be obeyed *for that repository*: the route evaluates the host gate first and then the resolved repository's, so the check can only ever close the gate further, never open a shut one. The read plane reports that same per-repository disposition, because an editor rendering the host's gate would offer a save button that always 403s.

Three details make the boundary honest rather than decorative:

- **The credential is env-only**, never a config field and never persisted — the same shape as `HYDRAFLOW_GATEWAY_CONTROL_TOKEN`, and for the same reason: a settings screen that could show it is a settings screen that could leak it. It is deliberately excluded from `config.declared_env_keys()`, like every other credential (#10885).
- **The actor comes from the boundary.** `OperatorIdentity.actor` is read from `HYDRAFLOW_OPERATOR_ID` (a non-secret label, defaulting to `operator`) and stamped onto the audit record. `PolicyMutation` declares no actor field and forbids extras, so a caller that tries to assert its own provenance gets a 422.
- **The identity carries no credential material.** There is no digest, no truncation, and no "first eight characters" — a stable credential fingerprint is exactly as forbidden as the credential (ADR-0138 §D1), and deriving an actor label from the token would have been one.

The token is presented by the browser as a bearer header the operator types into the editor and which is never written to `localStorage`, to a view model, or to a URL. That is a real authenticated operator identity rather than a shared ambient one, and because it is a header rather than a cookie, a cross-site request cannot forge it.

### D3: Every check happens before the first byte is written, so a refused edit is a no-op

`PolicyWorkspace.apply` runs, in order: recover any open transaction, refuse a corrupt snapshot, refuse an unverifiable chain, compare `expected_revision`, build the candidate set (scope, existence, credential-shape), and validate the whole set. Only then does anything touch disk.

There is consequently no partial write to undo, because there is never a partial write. `test_a_refused_mutation_leaves_the_previous_revision_byte_identical` asserts that over four different refusals, and `test_a_refused_mutation_appends_nothing_to_the_audit_chain` closes the other half: an audit that recorded refusals would let a reader infer a revision that never existed.

Concurrency is two layers, both borrowed rather than invented. `file_util.file_lock` (bounded, FIFO-fair, cross-process) serialises the read-modify-write, and `expected_revision` catches the case the lock cannot see — a second operator whose browser loaded revision 4 an edit ago. A stale save returns **409 with `actual_revision`**, so the client can say which revision won rather than making the operator guess, and it is never retried on their behalf (see Divergence).

The reader side needs no lock at all: `file_util.atomic_write` replaces the snapshot through `os.replace`, so a concurrent reader holds either the previous coherent revision or the next one. `test_a_concurrent_reader_never_observes_a_half_written_revision` runs a reader thread against 24 real writes and asserts every observation both parsed *and* matched its own content hash — and that observations actually happened, so the assertion cannot go vacuous.

### D4: A single-slot write-ahead journal makes the mutation and its audit record one transaction

The one window that ordering alone cannot close is a crash *between* the snapshot replace and the audit append. Either order is wrong on its own: audit-first invents a revision that may never land, snapshot-first leaves a revision nobody can explain.

So `apply` writes a `MutationIntent` to `routing/policy-journal.json` **before** the snapshot it describes, and clears it only after the append. Recovery reads the journal and compares the landed snapshot against the intent:

- **the snapshot matches** (revision *and* content hash) — the replace committed, so recovery finishes the append the crash cut off and clears the journal (`completed`). It is idempotent: an append whose `mutation_id` already sits at the chain head is not repeated;
- **it does not match** — the replace never happened, the prior revision is authoritative and always was, and recovery records the intent as `aborted` rather than pretending it did not exist (`rolled-back`).

The idempotency check sits **above both branches**, not just the committed one. `mutation_id` identifies the transaction rather than its outcome, and a crash between the *aborted* append and the journal unlink is exactly as possible as one after a committed append — guarding only the happy path would let a single interrupted intent leave two `aborted` records on a chain whose whole value is that it can be counted.

An append that itself fails leaves the journal in place, so the transaction stays open and the next recovery retries it — `test_an_unwritable_audit_leaves_the_transaction_open` pins that, and `test_a_snapshot_replace_that_fails_leaves_a_recoverable_intent` pins the write-ahead ordering by breaking the save and finding the intent. An **unreadable** journal refuses every mutation (`journal-unreadable`) rather than being cleared: a wedge an operator must repair beats a silent guess about what a dead process meant.

`mutation_id` is content-addressed over what the transaction *is* (repo, actor, prior revision, next content hash, timestamp), so recovery can recognise its own append without a random id it would have had to persist first.

### D5: The mutation chain is the durable revision history, and rollback creates a new revision

Each committed record carries the **entire resulting policy set**. That is the whole storage design for history: `_policies_at(revision)` reads a target revision back out of the chain, so there is no second store of old snapshots to keep in step, and the history inherits the chain's tamper-evidence for free. Revision 0 — the state before any policy was written — is a real target with no record, handled explicitly.

Rollback is therefore never a restore: it computes the target set and **saves it as the next revision**, so `policy_revision` on the decision chain stays strictly increasing and a decision recorded under an old revision remains replayable.

Two consequences follow directly:

- **An unverifiable chain refuses every mutation** (`audit-chain-broken`). Rollback has no other source, so a chain that does not verify cannot be built on. This is a write-time precondition, not a diagnostic.
- **Rollback is scoped like every other edit.** It replaces *this repository's* policies with the target revision's and carries every inherited policy forward untouched. Restoring a whole prior snapshot would let a repo-scoped operator silently revert a class or global rule they are not permitted to write — the same escape D6 closes at the front door, arriving through the back.

### D6: A repository editor edits exactly its own repository, and aggregate is read-only

`is_editable_by(policy, repo)` is true only when the match names **exactly one** repository id — this one — and names no repo class and no system-safety flag. Everything else is *inherited*: rendered in the list with its badge, and refused at the write plane with `out-of-scope`.

`repo=__all__` serves a per-repository summary (which repos carry policy, at which revision, in which state) and every other policy route refuses it with a 400. There is no aggregate write, so an aggregate write cannot be mistaken for a host-admin one — the design document names that confusion directly, and the host-admin scope that would own class/global rules and account state is not built here.

### D7: A policy may not carry a credential-shaped value

The snapshot is written by `file_util.atomic_write`, which — unlike the audit chain's `append_jsonl` — does **not** redact on the way to disk, and it is served back over an unauthenticated read route. So a credential pasted into a model id or an account id would land durably and be echoed to every reader of the dashboard.

`_refusing_credential_shaped` scans every **newly introduced** policy with ADR-0085's canonical `scan_for_secrets` and refuses the write (`credential-shaped-value`). Only new policies are scanned, because a pre-existing bad row must not wedge every later edit — repairing it is itself an edit. The refusal names the policy and the pattern *label*, never the matched text: an error message that quoted the credential back would be the leak.

`secret_scrub` gains the `hfop_` operator-token patterns alongside #11637's `hfgw_`/`hfgwctl_` ones, for the same reason those were added: a credential only one test file's `not in payload` assertion can catch is a credential the canonical detector is blind to everywhere else — the audit chain and the transcript stream included.

### D8: The effective-route matrix is one batch against one revision, and it guesses nothing

`src/routing_matrix.py:build_effective_matrix` resolves `WorkerRole × RequestFace × ModelRequirement` through `explain_batch`, so every cell shares one snapshot: a matrix whose rows saw different revisions is a race rather than a matrix (ADR-0139 D1). Each cell carries the explanation the batch produced, so selecting one never re-resolves against a newer revision than the grid was drawn from.

Two deliberate absences:

- **No role→model table.** The default requirement is the provider-neutral `balanced` capability — what `route_shadow.requirement_for_model` already records for a spawn that named no model. Compiling the config's per-role dials into a matrix axis would be the same maintained lie ADR-0139 refused when it declined to compile legacy dials into rung-9 policies. A caller that cares about a literal family passes it in, bounded at `MAX_MATRIX_REQUIREMENTS`.
- **No borrowed legacy route.** A cell asks what *policy* would do; the legacy route is a per-spawn fact this question does not have. A cell no policy claims is `unmanaged` — "legacy routing decides this one" — drawn in a neutral tone, because shadow mode is still authoritative and a red badge would train an operator to write policy to silence it.

The matrix earns its place at the moment it makes ADR-0139 D4's guard visible *before* a save: a bare `provider_lock` with no requirement mapping shows as `held`, with `capability-unmapped` or `literal-family-unsatisfiable` naming which guard held it. That is the conversation the builder exists to have.

### D9: The console round-trips its selection and drops out-of-order responses

`routingView` gains the three keys ADR-0138 reserved (`effective`, `policies`, `audit`) with no URL break, and one new bounded parameter, `routingSelection`, carries the within-view selection: a policy id in Policies, a matrix cell key in Effective. Changing view clears it, because a policy id highlights nothing in a route grid but would still sit in a shared URL.

`usePolicyWorkspace` adds a **monotonic sequence guard** to the `useGatewayRouting` polling shape. An `AbortController` cancels a cycle on unmount but does nothing about two *live* cycles finishing out of order, and a slow poll landing after a save's refresh would put the pre-save revision back on screen — inviting a save against it, which is the lost update D3 exists to prevent. Every load takes a ticket; a response older than the newest already applied is dropped. The poll and the preview keep **separate** ticket pairs, because they write disjoint state: one shared counter would let a routine thirty-second poll silently discard an in-flight preview and leave the Preview button looking inert with no error anywhere.

Three more properties the console needs for D3 to mean anything from a browser:

- **The editor pins the revision it opened on.** `expected_revision` comes from that pin, never re-read from the live poll at click time — reading it at click time would make it the *winner's* revision, and the 409 that stops a lost update could never fire from the surface it was built for. When a newer revision lands under an open form, Save is disabled, the form says which revision it was opened against, and the operator re-bases explicitly.
- **The feed says whether it has been read.** A cycle that threw, or any response that was not 2xx, sets an `unavailable` source state, and every empty-state string is gated on a payload having actually landed. Otherwise a dead endpoint renders as "no policy has been written for this repository" — and, worse, as a **`chain verified`** badge on a chain nobody read, which is a positive tamper-evidence claim about bytes that never arrived.
- **The feed is scoped and idle-exempt in the other direction.** It follows the console's canonical repository selection (an editor pointed at a repository the operator did not pick would write the wrong repository's policy), reads only the read-only aggregate summary when no repository is selected, and does not poll at all while Routing is closed — the audit read walks and hash-verifies a chain this ADR deliberately never prunes.

## Non-goals — what this phase deliberately does not build

**Observe before enforce**, still.

- **No enforcement.** Editing a policy changes what the resolver *would* decide and what the shadow chain records. Legacy routing decides every live spawn, and the scenario proves it at the external boundary: the upstream sees byte-identical traffic before and after a `project-x → zai-harness` policy is written through the HTTP write plane.
- **No host-admin scope.** Class rules, global rules, system-safety rules, account state, and lease revocation are all read-only here. The design's separate read / mint / policy-admin credential split arrives with the scope that needs it.
- **No gateway control-plane policy endpoints.** No `POST /control/v2/policies`, no `/control/v2/decisions/{id}`, no explain endpoints. D1 says why: the authority is here.
- **No multi-repository write.** One mutation edits one repository. `repo=__all__` reads.
- **No glob or prefix matching in a policy.** ADR-0139 deferred globs until the conflict model has real evidence, and a workspace that let an operator write one would have supplied the evidence in the worst possible way.
- **No chain rotation, and no pruning of the mutation history.** The history is the rollback source; trimming it would silently delete rollback targets.
- **No sandbox e2e.** See Consequences.

## Consequences

- **#11539 inherits a write plane, not a format.** An enforcement canary can turn one repository's policy on and off through an audited, revision-safe route, and roll it back without an operator editing JSON on a host.
- **Rollback targets are bounded by the chain, not by disk.** Every committed revision is restorable for as long as the chain exists, and the chain cannot be trimmed without breaking itself (ADR-0139's accepted consequence, now load-bearing for a second reason).
- **Reads are off the event loop, and the history read takes the writer's lock.** Every route hands its file I/O to a worker thread. `history()` additionally acquires the mutation lock on a short timeout, because `append_jsonl` writes through a buffered writer: a record larger than that buffer reaches disk in several writes, and a reader catching the gap would see a torn tail line and report a **broken chain** on the one panel whose entire job is trustworthiness. The lock falls back to an unlocked read rather than ever hanging a poll.
- **The mutation chain grows with the policy set, not just with edits.** Each record carries the resulting policy set, so a large policy set makes each record larger. Acceptable at v1's scale — policy sets are tens of rows and mutations are deliberate operator acts — and revisited with rotation when volume warrants it.
- **A host with no `HYDRAFLOW_OPERATOR_TOKEN` gets a read-only workspace and says so.** That is the default, and it is deliberate: the new surface changes nothing for an existing operator until they opt in.
- **The dashboard now has one authenticated route.** It is the only one. Every other dashboard route retains ADR-0138's boundary-of-record — the loopback bind — and this ADR does not extend operator authentication to them.
- **Sandbox e2e is deliberately not added.** The docker tier exercises behaviour that crosses a process boundary at runtime. This phase adds no loop, no container wiring, and no docker-observable behaviour: it is a set of pure functions, one router, and three React views, all of which the MockWorld scenario already drives in-process against the real routes, the real store, and a real gateway turn. The right moment is #11539's canary, when a routing *decision* starts crossing the container boundary — which is exactly the argument ADR-0139 made for the same omission, and it has not changed.

## Alternatives considered

- **Put the write plane on the gateway and proxy it, as the issue's prose expected.** Rejected in D1: two authorities, two revision counters, a network hop inside an observation path, and a per-repository store on a host-global deployable. Recorded here rather than silently ignored, because the prose is what a reader will find first.
- **Skip the journal; just write the audit record first.** Cheaper, and wrong in a specific way: a crash after the append and before the replace leaves a durable record of a revision that does not exist, which is worse than no record at all — it is a record that cannot be distinguished from a real one.
- **Keep an old-snapshot directory for rollback instead of carrying policy sets on the chain.** Rejected: a second durable store to keep in step with the counter, with its own corruption modes, to answer a question the tamper-evident chain already answers.
- **Auto-retry a 409 against the current revision.** Rejected in the Divergence above: the losing operator's intent may have been invalidated by what the winner did, and re-applying it silently is precisely the lost update the version check exists to catch, one layer up.
- **Let the browser hold the operator token in `localStorage` so it survives a reload.** Rejected. A stored credential is in every later page view's blast radius, including one an operator did not open. Re-typing it per session is the cost of not storing it.
- **Gate the read routes on the operator identity too.** Rejected: ADR-0138 §D5 scopes its restriction to writes, everything published is non-secret by D7 and ADR-0138 §D4, and a builder that could not validate an edit until it was authorised would push operators to save first and look afterwards.
- **Derive the audit actor from a digest of the operator token.** Rejected outright: that is a stable credential fingerprint, which ADR-0138 §D1 forbids as firmly as the credential. A separate non-secret label costs one environment variable.
- **Build the matrix from observed shadow decisions instead of the role catalog.** Tempting, because every cell would then be a route that really happens. Rejected for the same reason the design rejects it: a matrix drawn only from observed traffic cannot answer "what would this policy do to a role that has not run today?", which is the question an operator asks *before* enabling one.
