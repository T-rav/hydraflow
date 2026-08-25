# Vitals and conformance are different claims

**The rule, in one sentence:**

> If the claim is *what the number is*, it is **vitals** and may live in an
> external data plane. If the claim is *that a rule holds*, it is
> **conformance** and must be answerable offline from a clean checkout.

Apply it to a new artifact by asking what breaks if the external plane is down.
A vitals reading becomes unavailable — annoying. A conformance claim becomes
**unanswerable**, and an assurance seat you can only audit through somebody
else's uptime is not an assurance seat.

## Why the distinction is load-bearing

On 2026-08-23 this repo found, in one day:

- a `reraise_on_credit_or_bug` guard that #6855 claimed to add and **never
  added**, whose regression had passed for months against a rotted source-line
  window;
- **every** line-window-anchored assertion in the repo already vacuous, two of
  them pointing past end-of-file;
- three issues (#6752, #6766, #6809) **closed as fixed** on those tests;
- ten path-membership collections that had stopped seeing their subject while
  staying green, two naming files that have never existed here;
- the T29 self-modification veto **inert for 104 days**.

Every one is a case where **the measurement was lying and the dashboard was
green**. A vitals plane pointed at this repo that morning reports a healthy
factory, because every counter was fine and every gate passed.

Vitals answer *what are the numbers*. Conformance answers *is the number still
attached to anything*. The second cannot be sampled — you cannot infer "this
gate has no subject" from a time series of the gate passing. It requires
knowing what the gate was supposed to observe, which is repo knowledge.

## What follows from it

**Vitals may be externalised.** Counts, sizes, durations, rates, costs,
throughput. `scripts/emit_vitals.py` ships them as one self-identifying document
per factory; aggregating those across hosts is the whole point of having a data
plane (#11687, #11690).

**Conformance may not.** A conformance check must run offline, from a clean
checkout, with no network. Concretely it must not import a network client, open
a socket, or read from a service. If a rule can only be verified by asking a
server, the rule is not enforced here — it is *reported* here, which is vitals.

**Silence is not health.** A vitals stream that stops must be detectable as
absent. A conformance check that stops running must fail, not pass.

## Enforcement
Registration is manual and explicit, in
`tests/architecture/vitals_conformance_registry.py`, for the same reason
`path_membership_registry` is: discovery-by-convention is the failure mode one
level up, a rule that quietly stops seeing its subject.

Adding a check that enforces a rule? Register it as conformance. Adding a
counter? Register it as vitals, and it may go to the data plane.

### What is actually enforced

Two static properties, both in
`tests/architecture/test_vitals_conformance_seam.py`, both reading the
mechanics in `tests/architecture/conformance_offline_scan.py`:

1. **No conformance file reaches a remote client — transitively.** The remote
   clients are the ones that can *only* mean a remote service (`boto3`,
   `swamp`, `requests`, `aiohttp`, …). The reach follows first-party imports —
   `src/` then the repo root, the two entries the suite puts on `sys.path` — to
   a fixed point, including relative imports and re-exports through
   `__init__.py`, with cycles handled by a visited set.

2. **No conformance file spawns its way out of the checkout.** An argv is a
   reach an import sweep cannot see: `subprocess.run(["curl", …])` imports
   nothing. Every spawn call is read — the stdlib primitives, `os.exec*`/
   `spawn*`, `asyncio.create_subprocess_*`, and HydraFlow's own bounded-spawn
   wrappers, which is the path `test_subprocess_reap_guard.py` *requires*
   production code to use — and its argv literals are checked against
   `NETWORK_CAPABLE_BINARIES` and against the hosts they name.

Each property carries a vacuity guard, because both passed on the day they
landed and a check that has never observed a violation is a claim about
nothing: the sweep must have a subject, the closure must actually leave the
file it starts from, and the spawn scanner must still recognise the ~165 spawn
sites the conformance roots really contain.

### What was tried and rejected, and why it still matters

- *"imports an HTTP library"* — flagged three regression tests that build an
  in-process `httpx.MockTransport` against RFC-2606 `.test` hostnames. Entirely
  offline. Importing HTTP is not depending on a network.
- *"names a URL"* — flagged fixture data containing `https://github.com/...`,
  which no test contacts.

Both would have needed an allow-list to stay green, and an allow-list that
grows until it *is* the rule is the fail-open shape this standard exists to
prevent.

Going transitive made the first judgement **more** load-bearing, not less: 396
of the 673 swept files reach `httpx` through `hydraflow_gateway` /
`gateway_mint_client` without importing it themselves. Transitivity widens what
the sweep can *see*; it must not widen what counts as a reach. If closing the
non-transitivity hole turns those files red, the closure is wrong — the
carriers are not.

The URL proxy does come back, in the one place it has no false positives:
inside a spawn's argv. `https://github.com/x` in fixture data is data; the same
string in `["git", "clone", …]` is a fetch. Scope, not the pattern, was what
made the repo-wide version wrong — and it is what lets `git` stay off the
binary list. 129 of the ~165 spawn sites are `git` driving a throwaway repo
under `tmp_path`; listing it would need a ~130-entry allow-list, while the host
rule catches `git clone https://…` and `git@host:repo` for free.

### The binary list, and its exclusions

`NETWORK_CAPABLE_BINARIES` (in the registry) is drawn at *the binary's own
purpose*, not at "could conceivably reach a network": transfer tools and raw
sockets, forge and cloud control planes, package managers, registries and model
CLIs. Adding one tightens the rule and needs no ceremony. Removing one is the
loosening move and deserves the scrutiny a new waiver gets.

Deliberately excluded: `git` (above); `make` / `pytest` / `mkdocs`, which are
orchestrators that reach a network only through what they are configured to
invoke — a property of `Makefile` / `mkdocs.yml`, not of the argv, and
therefore invisible to any parser; and `python` / `sys.executable`, since
`python -m pip` is caught by `pip` appearing as an argv token.

### Waivers

`SUBPROCESS_WAIVERS` is the one allow-list here, and it exists because an
import is a fact about the file while an argv can be a fact about a call the
test never makes — monkeypatching is invisible to a parser. It is registered
alongside the claims, keyed by `(path, binary)` rather than by a line number
that would rot, carries a written reason, must still match a live spawn (a dead
waiver pre-approves whatever lands in that file next), and is capped by
`SUBPROCESS_WAIVER_CEILING`, **which may only ever be lowered**. It holds one
entry.

### The floor, and what is still above it

**These are static proxies, not proofs.** They are a floor. The proof that
conformance runs offline is a CI-lane property: run the conformance suite with
egress blocked and require it to pass, with a negative control proving the lane
fires. That remains unbuilt (#11706), and it is what covers the residuals the
static checks name but cannot reach:

- an orchestrator whose *configuration* reaches out (`mkdocs build --strict` is
  offline today only because `mkdocs.yml` enables `search`, `mermaid2` and
  `git-revision-date-localized`; adding the social-card plugin fetches Google
  Fonts at build time and nothing static would redden);
- `git fetch`/`push` against a remote configured elsewhere, where the argv
  names no host;
- an argv assembled entirely from non-literal values (`subprocess.run(cmd)`),
  where there is no string for a parser to read;
- a conformance check that calls a first-party helper which does the spawning —
  the subprocess rule reads the conformance file's own call sites, because
  following spawns transitively would flag every test that imports a module
  capable of shelling `gh`, which is most of them.
