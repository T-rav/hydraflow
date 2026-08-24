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

### What the static check does and does not prove

The enforced check is: **no conformance file imports a client that can only
mean a remote service** (`boto3`, `swamp`, `requests`, `aiohttp`, …). That has
zero false positives here.

Two broader proxies were tried and rejected, and the reasons matter more than
the outcome:

- *"imports an HTTP library"* — flagged three regression tests that build an
  in-process `httpx.MockTransport` against RFC-2606 `.test` hostnames. Entirely
  offline. Importing HTTP is not depending on a network.
- *"names a URL"* — flagged fixture data containing `https://github.com/...`,
  which no test contacts.

Both would have needed an allow-list to stay green, and an allow-list that
grows until it *is* the rule is the fail-open shape this standard exists to
prevent.

**So the static check is a floor, not a proof.** The proof that conformance runs
offline is a CI-lane property: run the conformance suite with egress blocked and
require it to pass. That is a lane configuration rather than a unit test, and it
is the thing to build when there is a data plane worth being tempted by.

`tests/architecture/vitals_conformance_registry.py`. Registration is manual and
explicit for the same reason `path_membership_registry` is: discovery-by-
convention is the failure mode one level up, a rule that quietly stops seeing
its subject.

Adding a check that enforces a rule? Register it as conformance. Adding a
counter? Register it as vitals, and it may go to the data plane.
