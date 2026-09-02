# ADR-0146: SRE v1 — the exception sensor

- **Status:** Accepted
- **Date:** 2026-09-01
- **Supersedes:** [ADR-0118](0118-observability-belongs-to-the-sre-agent-not-the-loops.md) (observability belongs to the SRE agent — its backend direction only; see "What ADR-0118 said that still stands")
- **Superseded by:** none
- **Related:** [ADR-0055](0055-otel-honeycomb-instrumentation.md) (the OTel layer ADR-0118 removed), [ADR-0044](0044-hydraflow-principles.md) (P7.7, the observability boundary), [ADR-0085](0085-secrets-never-persist-in-audit-stream.md) (why an error payload is not a free-for-all), [ADR-0002](0002-labels-as-state-machine.md) (the label state machine the sensor's issues enter). Issues: #11879 (the SRE agent epic this is the first rung of).
- **Enforcement:** enforced
- **Binds:** factory
- **Standard:** [`exception_sensor`](../standards/exception_sensor/README.md)

**Enforced by:**
pytest:tests/test_sentry_observability_adapter.py::TestTheDsnIsTheSwitch::test_no_dsn_gets_the_no_op
pytest:tests/test_sentry_observability_adapter.py::TestErrorsOnly::test_tracing_is_initialised_off
pytest:tests/test_triage_phase.py::TestTheExceptionSensorRoute::test_the_sensor_label_routes_a_failed_triage_to_auto_close

## Context

ADR-0118 removed the OpenTelemetry/Honeycomb layer, removed Sentry with it, and
named New Relic as the intended backend — to be wired "when the SRE agent
lands." That agent is still an epic (#11879, human-required), so for a month the
`ObservabilityPort` has had exactly one adapter: a no-op that discards every
event. `capture_exception` has been a function that does nothing, called from
code that believes it reports.

The removal left a second thing behind, and this is the part that matters more
than the missing backend. `triage_phase._flow_route` still carried a branch for
Sentry-originated issues: one that fails triage is treated as a transient and
auto-closed rather than parked for clarification. ADR-0118 deleted the loop that
filed those issues and left the branch. A repo-wide search for the marker it
keys on — `<!-- [sentry:` — returns three hits: the constant itself, and two
test fixtures that hand-build the string. **No production code has written it
since the removal.** The route's tests construct their own input, so they stayed
green for a month while the route was unreachable in production.

That is the failure mode this ADR is really about. A factory that runs
unattended cannot tell the difference between "no errors" and "nothing is
reporting errors," and neither can a test that supplies its own producer.

## Decision

**HydraFlow-format repos carry an exception sensor. It is the SRE v1 agent: it
does not diagnose and it does not fix, it closes the loop from *the software
failed* to *the board knows*.**

The sensor has two halves, and only one is code in this repo.

### Outbound: the adapter

`SentryObservabilityAdapter` implements `ObservabilityPort` over the Sentry SDK.
Errors only — `traces_sample_rate=0.0`, no PII, `set_measurement` a no-op. Spans
stay OTel's, which is ADR-0118 §1 unchanged.

The client is the Sentry SDK, so the **target is any endpoint speaking the Sentry
ingest protocol**. The house default is **Bugsink**: self-hosted, so error
payloads from a repo full of unreleased work stay on infrastructure the operator
owns. Pointing a repo at sentry.io instead is a DSN change, not a code change.
The adapter is named after the library it uses rather than the backend it reaches
because the backend is configuration.

The DSN is the switch. Absent, the composition root returns the no-op, so tests,
CI and the air-gapped sandbox never report. A DSN that fails to initialise also
degrades to the no-op: a broken reporter must not stop the factory booting.

`HYDRAFLOW_SENTRY_DISABLED` overrides a present DSN, always toward off. This ADR
first argued against a second switch — one setting cannot contradict the other —
and two facts overrode that. A live checkout keeps its DSN in `.env`, so
unsetting it is a credentials edit rather than an off-switch. And the flag was
already half-alive: `tests/conftest.py` sets it at import time and three
regressions (#10876, #11580, #11589) pin it surviving fixture clobbering, all
citing an `_init_sentry` that ADR-0118 deleted. A flag the suite defends and no
production code reads is this ADR's own dead-consumer shape, pointing the other
way.

### Inbound: a receiver, not a loop

**Correction (2026-09-02).** This ADR was accepted saying "Bugsink files GitHub
issues itself, deduplicated per error group." **That is wrong.** Bugsink has no
GitHub, GitLab or Jira integration. Its alert backends are email, Slack,
Mattermost, Discord, Microsoft Teams, Telegram and a **custom webhook** — the
last of which POSTs a JSON representation of the issue to a URL you control
(upstream `alerts/service_backends/custom.py`), firing on a new issue, a
regression, or an unmute.

The claim was assumed rather than checked, and it was load-bearing: it was the
entire argument for why the inbound half needed no code. It did.

**What stands:** still no polling loop. Bugsink pushes, so there is no interval,
no cursor and no backoff to keep correct — the receiver is a route
(`dashboard_routes/_issue_intake_routes.py`), and the original objection to a loop
(a second implementation of somebody else's state machine) never applied to a
webhook endpoint.

**Authentication is ADR-0140's, not a new one.** The receiver is a *generic*
issue-intake boundary (`/api/issues/intake`) shared by the UI and the sensor,
guarded by `operator_identity.authenticate_operator` and a gate with
`write_gate`'s shape: loopback bind first, then the credential.

A first draft invented a bespoke URL token for this. It was worse than the
mechanism already in the repo on two counts — it imposed no loopback
requirement, and it was invisible to the ADR-0085 secret scrubber, which only
redacts the `hfop_` grammar. Bugsink's webhook config is a bare URL and cannot
present a bearer token, so **the concession lives at the edge**: a proxy
(`docker/bugsink-proxy/Caddyfile`) turns its URL token into an `Authorization`
header. The application keeps exactly one way in.

**Dedup is ours now, not the backend's.** Bugsink fires the *same* issue id on
new/regression/unmute, so the receiver keys the issue title on that id and
looks for an existing open issue before filing. Keying on the message would file
one issue per rendered value within a single error group.

Those issues enter the pipeline the same way every other piece of work does:
they carry a `find_label` and triage picks them up. They additionally carry a
**provenance label** (`bugsink` by default, `exception_sensor_label`), which is
what makes an error a *routable piece of work* rather than a notification.

### The route, reconnected

`_is_sentry_issue` becomes `_is_exception_sensor_issue` and keys on the label.
The label is structured configuration set by the backend's integration; a body
marker depends on an issue template rendering one exact string, which is how the
old route came to have no producer. The marker survives as a fallback because it
costs one `in`.

The persisted outcome string stays `sentry_noise_closed`. It is written into
issue classification records and read back to score historical verdicts;
renaming a persisted value is a migration, and an unmigrated rename would score
every pre-existing record `unknown` instead of `ADVANCE`.

## What ADR-0118 said that still stands

This supersedes ADR-0118's **backend direction only**:

| ADR-0118 said | Status |
|---|---|
| §1 No OTel SDK under `src/` | **Stands.** Nothing here adds spans. |
| §2 Local `trace_collector` for in-process traces | **Stands.** Untouched. |
| §3 Observability belongs to the SRE agent, not the loops | **Stands** — and this is that agent's first rung. |
| §4 New Relic is the intended backend | **Superseded.** Bugsink by default, any Sentry-protocol endpoint. |

## Consequences

**Good.** Unattended failures become board items instead of nothing. The
`ObservabilityPort` gets its first real adapter, so its call sites stop being
decorative. The dead triage route gets a producer, and a test that fails when it
loses one. #11879 gets a shipped first rung instead of a blocked epic.

**Costs.** A `sentry-sdk` dependency. An operator must run a Bugsink instance
(`make bugsink-up`), which now includes a webhook proxy, and point its custom
webhook at that proxy. The webhook's delivery is deployment, not code, so CI
cannot prove the round trip; the standard's rules cover both halves we own. Error
payloads leave the process, which is why PII is off by default (ADR-0085).

**Risk accepted.** A noisy error group could file issues faster than triage
closes them. Bugsink deduplicates per group, and triage auto-closes sensor
issues that fail evaluation, but the rate is not bounded by anything in this
repo. If that bites, the bound belongs in Bugsink's alert rules, not in a
HydraFlow loop.
