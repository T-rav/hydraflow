# README and hydraflow.ai alignment review

**Status:** review (2026-08-20). **Scope:** compare the repository's main
`README.md` with the behavior on `staging` and the public product story at
[hydraflow.ai](https://hydraflow.ai/). This document recommends changes; it does
not change product behavior or onboarding.

## Executive finding

HydraFlow's positioning is coherent across the README and site: intent enters a
quality-gated, label-driven delivery pipeline and exits as reviewed software.
The operational instructions underneath that story have drifted. The README's
primary installation command points to a repository that does not exist, its
Quick Start assigns scaffolding to the wrong command, and several configuration,
provider, coverage, authentication, and background-loop claims no longer match
the implementation. The site has the correct repository URL and current command
name, but its onboarding omits required target-repository preparation and makes
Docker, recovery, and fidelity claims more absolute than the product currently
guarantees.

The next documentation change should treat the README and site as two views of
one product contract. Fix the shared onboarding path first, then derive both
surfaces from a small set of verified facts rather than maintaining parallel
copy.

## What is already aligned

- The product sentence and five-stage narrative accurately describe the core
  pipeline: triage, plan, implement, review, and HITL escalation.
- The README's Node requirement matches `package.json`, and its admin and
  multi-repository endpoints exist.
- The architecture site is live and its four-hour scheduled refresh matches the
  DiagramLoop cadence.
- The repository supports Claude Code and Codex as agent CLIs, and Beads can be
  installed by the setup machinery when decomposition needs it.
- Local links and images referenced by the README resolve.

## P0: repair onboarding before promoting it

### 1. Choose one canonical installation shape

The README currently starts with:

```text
git submodule add https://github.com/T-rav/hydra.git hydraflow
```

`T-rav/hydra` does not exist. The live site instead clones
`T-rav/hydraflow.git`. The two surfaces also disagree on whether HydraFlow is a
standalone control repository or a submodule inside the target repository.

Recommend one canonical, tested path at the top of both surfaces:

1. clone `https://github.com/T-rav/hydraflow.git`;
2. run `make setup` in HydraFlow;
3. run `make setup TARGET_REPO_ROOT=/path/to/repo`, then `make scaffold` and
   `make prep` against that target repository in their real order and with
   their actual responsibilities;
4. start HydraFlow;
5. register and explicitly start the target repository;
6. create a first issue with `/hf.issue`.

If submodule deployment remains supported, move it to an advanced deployment
guide and test it independently. Do not mix both mental models in the primary
Quick Start.

### 2. Make the first-run sequence executable as written

`make prep` syncs labels, audits the repository, and initializes metrics state;
it does not scaffold quality gates. `make scaffold` owns that behavior. The
site's repository-registration call also does not start the registered runtime.
The Quick Start needs both commands and an explicit start step, followed by a
health check that proves the runtime is ready.

The command advertised for issue creation must be `/hf.issue`; `/gh-issue` is a
stale name. The old examples inside `.claude/commands/hf.issue.md` need the same
repair so the installed command does not teach its predecessor.

### 3. State the supported environment exactly

- Python support is `>=3.11,<3.12`, so say **Python 3.11.x**, not 3.11+.
- The dashboard already defaults on; remove the unsupported
  `HYDRAFLOW_DASHBOARD_ENABLED` instruction.
- Prefer `HYDRAFLOW_DATA_ROOT`. Mention `HYDRAFLOW_HOME` only as a compatibility
  alias if it must remain documented.
- Explain that agent PRs normally merge to `staging`, while the release train
  promotes release candidates to `main`. “Merged” and “released” are not the
  same terminal state.

## P1: make configuration and security truthful

### Runtime, route, and provider are different axes

The README currently treats any recognized provider credential environment
variable as a supported routing provider. Replace that list with a matrix:

| Axis | Supported choices | Meaning |
|---|---|---|
| Agent CLI | `claude`, `codex` | The process that executes an agent contract |
| Agentic route | native Claude, z.ai harness, gateway | How Claude-compatible agent traffic reaches an upstream |
| One-shot HTTP backend | Claude/gateway, OpenRouter, z.ai, Kimi | Backend choices for supported lightweight calls |
| Credential passthrough | provider-specific keys | Secrets a child may receive; not proof of a selectable backend |

Document the current combo variables (`HYDRAFLOW_<ROLE>=tool:model` and
`HYDRAFLOW_BACKGROUND=tool:model`) instead of legacy per-role `*_MODEL`
examples. Pipeline labels are config-file values, not general environment
overrides.

### Add the gateway's security model

The gateway is now a first-class part of HydraFlow but is absent from the main
README. Add a short section that links `gateway/README.md` and distinguishes:

- native/local routes, where selected tool authentication can be mounted into a
  worker;
- gateway routes, where a worker receives a short-lived virtual key and the
  real provider credential stays in the gateway;
- metadata-only versus explicitly allowed body capture;
- canary routing versus the Docker-only terminal fleet ratchet.

Avoid saying a setup token is universally mandatory for Docker. Current native
routes can mount supported local Claude/Codex auth, while remote/headless and
alternate routed backends need explicit credentials. The exact behavior should
be described per mode.

### Repair WhatsApp setup

The instructions omit `HYDRAFLOW_WHATSAPP_APP_SECRET`, even though inbound Meta
requests are HMAC-verified with it. Include the secret in the setup sequence and
make the verification boundary explicit.

## P1: remove or reframe stale product claims

| Current claim | Evidence-backed replacement |
|---|---|
| “enforce 50% minimum and drive toward 70%+” | Say quality floors are repository-defined. HydraFlow's own current global floor is 91.3%, with a separate 85% branch floor for the gateway package. Avoid hard-coding these in marketing copy unless generated. |
| `make prep` scaffolds CI/tests/lint | `make scaffold` creates missing quality infrastructure; `make prep` audits and initializes the target. |
| prep creates local issues and run transcript directories | Remove. The current prep path stores coverage-floor state and initializes metrics; the old local prep issue tracker was never integrated. |
| a hand-written list of ten background loops | Use a grouped summary and link the generated loop registry. The current registry has 66 loops and will continue changing. |
| every PR refreshes the architecture site | PR CI checks generated-architecture drift; deployment occurs from the configured main-branch workflow and the scheduled refresh. |
| all agents run in Docker | Docker is supported and required by the terminal gateway ratchet, but the repository default remains host execution. State the mode rather than universalizing it. |
| crash recovery loses no work | Describe checkpoint/resume and salvage behavior without an absolute guarantee. Stop/reap and external-process boundaries still have failure modes. |
| the whole factory is air-gapped/faked at every boundary | Describe the MockWorld and sandbox tiers precisely; do not imply every external surface has full-machine parity unless a generated completeness check proves it. |
| “guarantee accurate, high-quality output” | Say HydraFlow enforces configured gates and escalates when evidence is insufficient. |
| every change was built by HydraFlow | Report verifiable issue/PR volume separately from agent authorship unless provenance data proves the latter. |
| the primary review verdict is universally calibrated | Say selected advisory judges are calibrated against the escape ledger; do not broaden that claim to every `ReviewRunner` decision. |

The site's “65 caretaker loops” and “125 ADRs” were already behind the audited
repository (66 generated loops and 133 ADR files). Counts of loops, ADRs, PRs,
and issues should be generated at build time or phrased without exact values.

## Recommended information architecture

Keep the root README short enough to answer six questions in order:

1. What is HydraFlow, and what does it own?
2. What happens from issue to staging to release?
3. What do I need to run it?
4. What exact commands produce a verified first run?
5. Where do I configure runtimes, routing, credentials, and safety modes?
6. Where are the operator, deployment, architecture, and contribution guides?

Move WhatsApp, EC2, exhaustive provider credentials, background-loop inventory,
and detailed Docker authentication into focused guides. Link them from a compact
“Operations and integrations” section. Put one current dashboard image near the
top so the repository and product site show the same operational surface. The
site's Work Stream or Operator Console image is the best fit. Add compact hero
links for the product tour, verified Quick Start, narrative architecture page,
generated architecture reference, and Apache 2.0 license; distinguish the two
architecture destinations by name.

The public runtime list should remain Claude/Codex until code and documentation
agree on Pi. ADR-0004 and `AGENTS.md` still claim Pi support, while current
configuration literals reject it. That is an internal contract conflict to
resolve, not a reason to advertise an unusable runtime.

## Keep README and site from drifting again

1. Store the canonical Quick Start commands and product-stage names in one
   source file or checked snippet consumed by both surfaces.
2. Add a docs contract test that checks the repository URL, `/hf.issue`, Python
   constraint, Make target sequence, dashboard/API ports, and supported routing
   matrix against code-owned registries.
3. Generate volatile counts from architecture artifacts during the site build,
   or remove the numbers.
4. Add a link/command smoke check that runs the Quick Start in a clean sandbox
   far enough to prove setup, scaffold, prep, registration, runtime start, and
   health.
5. Require documentation updates when the settings registry, provider registry,
   release branches, or gateway mode changes.

## Definition of done for the alignment pass

- A new user can copy one Quick Start from either surface and reach a healthy,
  started runtime without discovering an omitted command.
- Every named CLI, environment variable, provider/backend, and Make target is
  accepted by the current code.
- Host, Docker, native-auth, and gateway-isolated modes are clearly distinct.
- The README and site agree on repository URL, issue command, pipeline terminal
  states, and installation shape.
- Volatile fleet counts are generated or removed.
- The docs contract and first-run smoke fail when those truths drift.
