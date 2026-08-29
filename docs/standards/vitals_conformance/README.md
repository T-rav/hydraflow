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
mechanics in `tests/architecture/conformance_offline_scan.py` — and, since
#11706, an **empirical** third that runs the suite with egress blocked and
watches instead of reading. The static pair is the floor and the fast local
answer; the lane is the one that can settle a question about what a call
resolves to at runtime. Both are described below, the lane under
"[The lane](#the-lane-what-the-static-checks-cannot-reach)".

1. **No conformance file reaches a remote client — transitively.** The remote
   clients are the ones that can *only* mean a remote service (`boto3`,
   `swamp`, `requests`, `aiohttp`, …). The reach follows first-party imports —
   `src/` then the repo root, the two entries the suite puts on `sys.path` — to
   a fixed point, including relative imports and re-exports through
   `__init__.py`, with cycles handled by a visited set.

   A dynamic import counts too, and it is recognised by **resolving the
   argument, not the callee**. Three versions of that check tried to recognise
   the callee — literal spelling, then resolved `ImportFrom` bindings — and each
   was walked past by the next binding form somebody thought of (`import_module
   as im`, then `from importlib import *` and `load = importlib.import_module`).
   The callee's identity is unbounded; the first positional argument is a string
   literal or it is not. So `import_module("boto3")` is caught however it is
   bound, and so are `pytest.importorskip("boto3")` and
   `mock.patch("boto3.client")`, which import as a side effect and which nobody
   had enumerated. Measured across the 1471 files the conformance roots reach:
   zero calls take a remote-client name as their first positional argument.

   Inverting a rule is not free — it moves the error to the other side. Here
   the other side is "names a client without importing it":
   `logging.getLogger("botocore")`, `mock_import.assert_called_once_with(
   "boto3")`. Those are excluded by callee (`assert*` as a prefix, plus a
   two-name list), and *that* enumeration is fine where the first one was not:
   a spelling missed on the detection side is a **silent false negative**, while
   a callee missed on the safe side is a **loud false positive** its author
   fixes in one line. The exclusion is pinned in both directions — removing it
   reddens the false-positive control, widening it to swallow
   `pytest.importorskip` / `mock.patch` (which really do import) reddens the
   detection control.

2. **No conformance file spawns its way out of the checkout.** An argv is a
   reach an import sweep cannot see: `subprocess.run(["curl", …])` imports
   nothing. Every spawn call is read — the stdlib primitives, `os.exec*`/
   `spawn*`, `asyncio.create_subprocess_*`, and HydraFlow's own bounded-spawn
   wrappers, which is the path `test_subprocess_reap_guard.py` *requires*
   production code to use — and its argv literals are checked against
   `NETWORK_CAPABLE_BINARIES` and against the hosts they name.

Each static property carries a vacuity guard, because both passed on the day
they landed and a check that has never observed a violation is a claim about
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

### Waivers, and why there are none left

`SUBPROCESS_WAIVERS` held three entries, and all three said the same thing:
*this call is faked*. One monkeypatched `asyncio.create_subprocess_exec`; two
passed `cmd=["claude", …]` into an inversion-of-control seam with a recording
double in `StreamConfig(runner=)`. A parser reads the call, never what the call
resolves to at runtime, so a hand-written waiver was the only honest way to say
it — and "the only honest way to say it" is exactly the state that should make
you go build a different instrument.

The list is **empty**, and `SUBPROCESS_WAIVER_CEILING` is **0**. A flagged
spawn site is no longer waived, it is **escalated**: the file is run in a child
process with `tests/architecture/egress_guard.py` armed, and the question "does
this argv ever become a process?" is answered by the interpreter's own
`subprocess.Popen`/`os.exec` audit events. A monkeypatched primitive and an
injected runner both spawn nothing, so both are simply not observed. Measured
on those three files: 14 tests, 5 real spawns, every one of them `bash` or
`true`.

The cost is proportional to the exception count, which is the property that
makes it affordable and the pressure gradient the right way round: a rule
nobody trips costs nothing, and a rule tripped fifty times costs fifty test
files. `git status` in a hundred conformance tests is still free, because
nothing flags it.

The waiver *liveness* property — an exemption must still match a live spawn, or
it pre-approves whatever lands in that file next — is not gone, it moved. It
now applies to the one list that is not empty, `EGRESS_LANE_EXCLUSIONS`, and is
enforced by `scripts/check_egress_exclusions.py`.

An argv is read wherever it can be passed — positionally, spread across
varargs, or by keyword. `subprocess.run(args=[...])` is ordinary working Python
(`run(*popenargs, **kwargs)` forwards straight into `Popen(args=…)`), and a
scanner reading only `call.args` sees a real spawn with an empty argv and
reports nothing. An absolute path is reduced to its basename for the same
reason: `/usr/bin/curl` is `curl`. Both sides — the AST scanner and the runtime
guard — call one `argv_tokens`, so the same argv cannot be read two different
ways.

### The lane: what the static checks cannot reach

**The static checks are proxies, not proofs.** They are a floor. The proof is a
CI-lane property — run the conformance suite with egress blocked — and it is
built (#11706). Two mechanisms, because they see different things:

- **`tests/architecture/egress_guard.py`** arms a `sys.addaudithook` hook in a
  child process and watches `socket.connect`, `socket.sendto` and every spawn
  primitive. It can NAME the test that reached and read the argv a process was
  actually handed, which is what settles a faked call and what sees an argv
  assembled from non-literals. It cannot see inside a child process.
- **`scripts/offline_egress_lane.sh`** verifies the surrounding process tree
  has no route off the host, and runs the suite inside it. That is the half
  that catches what the hook cannot: a `gh` that opens its own socket, a
  `mkdocs` plugin fetching Google Fonts, a `git fetch` whose remote is
  configured elsewhere.

Both `arch` and `regression` in `ci.yml` run through the lane. It is not a
second copy of those jobs — it is those jobs with the network taken away, which
is the only version of it nobody switches off to save runner minutes.

#### Why not `pytest-socket --disable-socket`

It was the obvious candidate and it is the wrong altitude twice over. It blocks
at the socket **constructor**, and the asyncio event loop's self-pipe is a
`socket.socketpair()` — so a naive `--disable-socket` breaks the harness rather
than the egress. And it is in-process only: `subprocess.run(["curl", …])`
satisfies it completely, which is the entire second dimension.

Blocking at `connect` instead costs none of that. Measured: `socket.socketpair()`
raises no `connect` audit event at all, and the ~1500 `git` spawns the
conformance roots make against `tmp_path` repos name no host, so neither rule
touches them. `test_the_guard_leaves_local_machinery_alone` is the pin —
socketpair, a loopback round trip, a synchronous `git` and an asyncio
subprocess, all in one guarded run, all clean.

#### Guarding the guard

A lane that stopped isolating would go on passing, which is the failure this
whole standard is about. So `offline_egress_lane.sh` **verifies before it
runs**, every time, with three canaries: an outbound TCP connect to a public
address by IP (must fail), a DNS lookup (must fail), and a loopback round trip
(must **work** — `unshare --net` hands over a namespace whose `lo` is down, and
running the suite there would redden it for a reason unrelated to egress). Any
of the three answering wrong is exit 3, not a warning.

#### What the lane does not cover

- **Three conformance files reach the network today**, and the lane does not run
  them. They are registered in `EGRESS_LANE_EXCLUSIONS` with the reach that was
  *observed*, the count is shrink-only, and they run outside the namespace so
  their own verdict is unchanged. Every one was found BY the lane and is
  invisible to the scanner, because in each case a first-party helper does the
  spawning — the residual named below. The sharpest is
  `test_wired_start_orchestrator_is_airgapped_and_stays_responsive`, which is
  not air-gapped: it spawns `gh run list`, `gh issue list` and opens a TLS
  connection to `raw.githubusercontent.com`, and it **exits 0**, because the
  reaches happen in loops it starts and does not assert about. A gate reading
  the source finds nothing there; a gate watching the process finds three.
- `scripts/check_egress_exclusions.py` reddens when one of those files stops
  reaching, because an exclusion that outlives its reason pre-approves whatever
  lands in that file next. It runs **inside** the namespace, where the reach is
  observed (the audit event fires) and never completes (the syscall fails), and
  it refuses to run outside one.
- The hook observes Python-level audit events, so a C extension calling
  `connect(2)` directly is invisible to it. Only the namespace catches that, and
  the namespace half is Linux-only: a macOS developer box gets the hook and not
  the kernel.
- A callee rebound in a way no argument reveals — the same limit `_SpawnNames`
  has for `spawn = subprocess.run`. Static only; the lane does not care how the
  call was spelled.

#### Residuals the static checks name, and where they now land

- an orchestrator whose *configuration* reaches out — **caught by the
  namespace, and it fired on the first run**. This document used to say
  `mkdocs build --strict` was offline "today", on the theory that `search`,
  `mermaid2` and `git-revision-date-localized` all stay local, and that the
  risk was some *future* plugin. That was wrong about the present:
  `mermaid2` resolves its `javascript` property through `url_exists()`, which
  is a live `requests.get` of the CDN bundle on **every** build. With no route
  out it warns and `--strict` aborts. The prose asserting the opposite had been
  read by several people and reviewed five times; the namespace disagreed with
  it in four minutes. Registered as an exclusion, because vendoring the mermaid
  bundle changes what the published site loads and that is a docs decision, not
  this one;
- `git fetch`/`push` against a remote configured elsewhere, where the argv names
  no host — **caught by the namespace**;
- an argv assembled entirely from non-literal values (`subprocess.run(cmd)`) —
  **caught by the hook**, which reads the argv the process received;
- a conformance check that calls a first-party helper which does the spawning —
  **caught by the hook**, and this is the residual that produced all three live
  findings above;
- a dynamically imported FIRST-PARTY module, deliberately not followed as a
  graph edge: 195 first-positional literals in the corpus resolve to a local
  module and essentially all are `monkeypatch.setattr("state.x", …)` targets
  rather than imports, so turning them into edges would put whole subtrees
  behind a coincidence — and the import rule has no waiver mechanism to undo a
  false positive. Static imports of those modules are followed as normal. **Not
  covered by either half**: it is an import-graph question, not a runtime one,
  and it stays a declared boundary.

## Enforced by

The gates that hold this document to its artifact. This list is the same
set as `enforced_by` in [`standard.yaml`](standard.yaml); editing either
side alone reddens `tests/architecture/test_standards_registry.py`, which
also checks that every cited path is still **collected by pytest** — a
gate that exists but never runs is a citation to nothing.

<!-- standard:enforced-by -->
- `tests/architecture/test_vitals_conformance_seam.py`
- `tests/architecture/test_conformance_egress_lane.py`
<!-- /standard:enforced-by -->
