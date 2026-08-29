# OPA pilot: measurement record and verdict — **NOT ADOPTED**

**Status:** pilot complete (2026-08-29). **Issue:** #11750 (child of epic #11752, milestone v1.0.1).
**Depends on:** #11749 — `Fact` / `StandardDecision` / `DecisionEngine` / `PythonDecisionEngine` (`src/policy/`).
**Verdict:** do not adopt Open Policy Agent as HydraFlow's standards-decision layer. Keep `PythonDecisionEngine`.
**Disposition of the pilot code:** removed. It is reproducible from this document; the full Rego policy is in the appendix.

---

## The verdict in one paragraph

The pilot was built, run and measured. Rego reached **exact parity** with `PythonDecisionEngine`
over every Accepted ADR and over an exhaustive synthetic fact space, and it did so in **fewer
lines than the Python it replaces** (0.71×, against a kill threshold of 3×). The composition
probe — the only thing the pilot was really testing — was **materially cheaper in Rego** (12
lines against 23, 0.52×). **The kill criterion as written did not fire.** The verdict is
nonetheless *not adopted*, because the criterion's denominator was "the Python it replaces" and
that silently excluded the Python needed to *run* Rego: a **237-line adapter, an 84-line
installer and a 43 MB per-platform binary**, paid before the first standard delivers any benefit.
At 11 lines saved per cross-standard rule, OPA breaks even at roughly **22 such rules**. HydraFlow
declares **eight** standards. The arithmetic does not close, and the operational costs — a second
language, a second test runner, a binary absent from every current CI machine, and Rego's
fail-open default in a repo whose dominant defect class is the guard that stopped observing its
subject — all point the same way.

A reader who holds that the adapter should not count against Rego is reading the same numbers and
may reach "adopt". That disagreement is stated on purpose: the measurements below are the shared
ground, and the adapter's 237 lines are the single number the decision turns on.

---

## What was built

Scoped to the `adr_enforcement` standard, as the issue specified, against the seam #11749 landed.

| Artifact | Role |
|---|---|
| `policy/adr_enforcement.rego` | The decision, in Rego. Reproduces `PythonDecisionEngine._decide_enforcement` including its fail-closed behaviour. |
| `policy/adr_enforcement_test.rego` | 18 Rego-native unit tests (`opa test`), one per arm of the ladder plus the probe. |
| `src/policy/opa_engine.py` | `OpaDecisionEngine`, implementing the `DecisionEngine` protocol by shelling out to a pinned local `opa eval`. |
| `scripts/opa_install.sh` | Pinned OPA **1.4.2**, four vendored per-platform SHA-256 sums, installs to `.opa/opa`. |
| `tests/architecture/test_policy_opa_parity.py` | The parity comparison, plus its own anti-vacuity guards. |
| `tests/test_policy_opa_engine.py` | The optional-dependency contract, tested with **no** OPA installed. |
| `make opa-install` / `make opa-test` | Install and run; `opa-test` prints a loud SKIPPED banner rather than passing when the binary is absent. |

**No network at decision time.** `opa eval` was handed a local policy file and the input document
on stdin. No server, no bundle, no `http.send` — a committed guard scanned the policy's *code*
(comments stripped, since the policy's own header names the builtins it must not use) for
`http.send`, `net.lookup_ip_addr`, `opa.runtime`, `time.now_ns`, `rand.intn` and `trace(`.

**Absent binary degrades, never crashes.** `OpaDecisionEngine.availability()` returns a named
reason (`binary-not-found` naming `$HYDRAFLOW_OPA_BIN` and `make opa-install`, `policy-not-found`,
`binary-not-runnable`); `decide()` raises `OpaUnavailableError` carrying it. It never returns `[]`,
which a gate would read as "no violations".

---

## Measurement 1 — parity: **PASS**

Corpus, all compared on **full decision equality** (`standard`, `status`, `blocking`, `reason`,
`remediation`), not on status alone:

* **Live:** all **88** Accepted ADRs (85 `REAL`, 3 `WEAK`; frozen snapshot 12, resolved 7,
  exempt 3), collected by `policy.facts.collect_adr_enforcement_facts`, serialized to JSONL and
  parsed back — so both engines were judged on the *written* evidence, per the epic's offline claim.
* **Exhaustive synthetic:** the entire
  `enforcement_class × in_baseline_snapshot × resolved × exempt × binds` space — 3 × 2 × 2 × 2 × 4
  = **96 subjects** — run under **both** assurance classes (`internal`, `regulated-phi`).
  Exhaustive rather than sampled: a sampled parity corpus is the shape that agrees everywhere it
  looks and diverges where it does not.

Zero divergences.

### Proving the comparison is not vacuous

Two engines can agree by both returning nothing, or by a corpus that exercises one arm. Every one
of those failure modes was closed by an assertion that ships with the test, not by inspection:

* the synthetic corpus is pinned to reach **all four** `DecisionStatus` values;
* the live comparison is pinned to span **> 50** subjects;
* a charter that does not place the standard in force is asserted to yield `[]` **on both sides**,
  so "no decisions" can never be a silent pass;
* the two charters are asserted to reach **different** answers — otherwise running every parity
  assertion twice would prove nothing twice;
* **seven deliberate policy mutations** each had to make the comparison diverge, and each
  mutation's search string is asserted to still occur in the policy, so a rewrite cannot silently
  retire the mutation into a no-op.

The mutations: exempt loses to the baseline lane · grandfathering ignores `resolved` · `WEAK` stops
counting as debt · violations stop blocking · remediation never files an issue · the probe stops
reading the charter · the probe forgets `Binds: both`.

**Mutation run, the other direction.** The mutations above break Rego. To prove the comparison is
not merely watching Rego, the *Python* engine was mutated instead — `_BINDS_FACTORY` narrowed from
`{"factory", "both"}` to `{"factory"}` — and the parity suite failed with the ADR ids and both
decisions in the message, including one subject (`ADR-0035`) where **only the `reason` string
diverged and the status did not**. That is the evidence that parity is asserted over the whole
decision and not over a convenient projection of it. Restored; suite green.

---

## Measurement 2 — size: Rego is **smaller**, the system is **larger**

Lines are counted the same way on both sides: non-blank, non-comment, non-docstring.

| | code lines |
|---|---|
| **Rego** — `adr_enforcement.rego`, parity only | **45** |
| **Python** — `_decide_enforcement` (52) + `_indexed` (11) | **63** |
| **ratio** | **0.71×** |

With the composition probe included: Rego 54, Python 84 — **0.64×**.

The kill criterion's threshold was **3×**. Rego came in at roughly a fifth of it. The reason is
not magic: the Python ladder spends ~35 of its 52 lines constructing four `StandardDecision`
objects with their prose reasons, where Rego computes one object with a computed reason.

**The number the criterion did not ask for:**

| | code lines |
|---|---|
| `src/policy/opa_engine.py` (the adapter) | **237** |
| `scripts/opa_install.sh` | 84 (shell) |
| pinned `opa` binary | **43 MB**, per platform, uncommittable |

The adapter is not decision logic. It is binary discovery, an availability probe with named
degradation reasons, an error taxonomy, JSON marshalling of facts into an input document, one
subprocess invocation with a timeout, and result parsing back into `StandardDecision`. **All of
it exists only because the decision moved out of process behind an optional binary.** It is a
one-time cost, not a per-standard one — but it is paid in full before the first standard returns
anything.

Whole-system comparison for the same decision: Rego path 54 + 237 = **291**; Python path **84**.
**3.5×.**

---

## Measurement 3 — latency: **a non-issue**

Whole 88-ADR corpus, one `decide()` call, median of 15 runs, on a shared host running other
suites:

| | median |
|---|---|
| `OpaDecisionEngine.decide` (one `opa eval` spawn) | **16–29 ms** |
| `PythonDecisionEngine.decide` | **0.2–0.5 ms** |
| bare `opa version` (process spawn floor) | 9–14 ms |

52–76× relative, ~20 ms absolute. More than half of it is process spawn, not evaluation. At one
evaluation per `make quality` this is invisible, and latency is **not** an argument against
adoption.

One design note found by measuring: the first implementation re-probed `opa version` inside every
`decide()`, so it spent more wall time asking whether OPA existed than asking it anything. The
probe is now answered once per engine instance.

---

## Measurement 4 — the composition probe: **cheaper in Rego, and not by enough**

The rule, chosen because it cannot be expressed by a per-subject ladder without new plumbing:

> An ADR that binds the **factory** (ADR-0123 `**Binds:** factory | both`) and is only weakly
> enforced is **blocking even when the ratchet grandfathers it**, once the repo's charter declares
> a regulated assurance class (ADR-0143 `articles.assurance`, `regulated-*`).

It is cross-standard because it joins a fact about the **subject** to a fact about the **repo**.

### Cost, engine-specific

| | code lines |
|---|---|
| **Rego** — 9 in the policy + 3 in the adapter's input document | **12** |
| **Python** — 21 in `_decide_enforcement` + 2 threading the charter to the call site | **23** |
| **ratio** | **0.52×** |

### Cost, shared — paid identically whichever engine wins

| | code lines |
|---|---|
| `policy/facts.py` — emit `binds`, add `seam_charter` | +14 |
| `policy/models.py` — `CharterArticles.assurance`, `Charter.is_regulated` | +3 |

### Cost, tests

| | code lines |
|---|---|
| `policy/adr_enforcement_test.rego` — 6 probe tests + fixture churn | +55 |
| `tests/test_policy_python_engine.py` — 7 probe tests + fixture churn | +62 |

Near parity. Rego's `with input as ...` is legal only inside a rule body, so it has no fixture
mechanism and every test rebuilds its own input — which cancels most of the terseness the policy
itself gains.

### What the numbers mean

Rego's advantage is real and it is qualitative as well as quantitative. The Python probe forced a
**signature change**: `_decide_enforcement` had to start receiving the charter, and that rippled
to its call site. In Rego the charter was already in `input`, visible to every rule, so a new
cross-cutting rule needs no plumbing at all. That is exactly the composition argument the epic
makes, and the pilot confirms it: **the marginal cost of the Nth cross-standard rule is lower in
Rego, because nothing has to be threaded.**

It is also not enough. Eleven lines saved per rule against a 237-line adapter is a break-even at
**~22 cross-standard rules**. Stripping the adapter's optional-dependency machinery (making OPA a
hard dependency) would take it to perhaps 130 lines and a break-even near **12**. `charter.yaml`
declares **eight** standards. The realistic near-term count of genuine cross-standard rules is
single digits, and the pilot had to invent the first one.

---

## The kill criterion, applied literally

> *if the Rego for parity exceeds 3x the Python it replaces AND the composition probe is not
> materially cheaper in Rego, close this issue as "not adopted"*

* Rego for parity: **0.71×**, not > 3×. **First conjunct false.**
* Composition probe: **0.52×**, materially cheaper. **Second conjunct false.**

**The criterion did not fire.** It is a sufficient condition for killing, not a necessary one —
it never said "otherwise adopt". The pilot therefore did not disqualify OPA on the axes the
criterion named, and the verdict below rests on axes it did not name. Recording that plainly is
the point: the criterion was pre-registered so a verdict could not be rationalised, and
overriding it needs its own stated reason.

**The stated reason:** the criterion's denominator, "the Python it replaces", excluded the Python
required to *run* Rego. That is 237 lines against the 84 being replaced. A criterion that measures
the policy and not the system will always favour the policy language.

---

## Why "not adopted"

1. **The adapter is 2.8× the code it replaces.** 237 lines of process plumbing, error taxonomy and
   marshalling, none of it decision logic, all of it load-bearing and all of it new surface.
2. **The break-even is ~22 cross-standard rules; the repo has 8 standards.** The composition win
   is real per rule and does not accumulate fast enough to pay the fixed cost.
3. **Rego's default is fail-open, and the tooling that is supposed to catch it cannot see the
   shape a normalized fact ledger produces.** Verified empirically. A rule referencing
   `obs.governance_tier` — a fact no collector emits — passes `opa check --strict`, evaluates
   without error, and returns the **un-probed** verdict (`grandfathered` where the rule intended
   `violated`). Nothing reddens. The equivalent Python (`by_key["governance_tier"]`) raises
   `KeyError` and crashes loudly.

   OPA has a real mitigation for this — METADATA `schemas:` annotations plus
   `opa check --schema <dir>`, which type-checks `input` references against a JSON schema — and
   the pilot tested it rather than assuming. It works on **statically-known paths**:

   | reference | `opa check --strict --schema` |
   |---|---|
   | `input.nonexistent_toplevel` | **error** — `undefined ref`, lists the valid keys |
   | `input.charter.nonexistent_nested` | **error** — same |
   | `some _, obs in input.subjects; obs.governance_tier` | **silent** |
   | `input.subjects[subject].governance_tier` | **silent** |

   The two silent forms are the only ones a fact ledger can use, because subjects are ADR ids —
   the document is keyed dynamically by construction, and a dynamic key defeats the checker.
   **The exact shape the `Fact` model produces is the shape OPA cannot type-check.** The pilot's
   policy falls back to a hand-written `required_facts` set and a `missing_facts` rule, which
   covers only the facts someone remembered to list; forgetting one is silent. In a repo whose
   dominant defect class is **the guard that stopped observing its subject**, adopting a language
   whose default is "the rule quietly does not fire" — with its type checker blind to the one
   document shape in use — is the wrong direction.
4. **The argument for OPA assumes an alternative HydraFlow does not have.** The issue's case was
   that "once standards compose, a homegrown YAML DSL becomes an accidental programming language."
   #11749 already settled that: the decision layer is a typed Python protocol, not a YAML DSL. The
   duplication OPA was proposed to fix was fixed by **normalizing the decision**, not by changing
   the language. Rego would be replacing a general-purpose language that already has a type
   checker, a debugger, and 2300 files of house convention with one that has none of that here.
5. **The gate would run nowhere.** The binary is 43 MB, per-platform, uncommittable, and absent
   from every current CI machine. Until CI installs it, the OPA parity gate is green because it
   never ran — the exact vacuous-gate shape the repo is fighting. Wiring it into `make quality`
   behind a presence check would have satisfied the acceptance criterion by installing a
   decoration, which is why the pilot left it as a standalone `make opa-test`.
6. **The seam's strongest existing guarantee does not extend to it.**
   `tests/architecture/test_policy_engine_is_pure.py` pins `models.py` and `python_engine.py` to a
   literal import set in **both** directions, so any new import — hazardous or not — reddens and
   forces the question out loud. An engine that shells out to a binary can never be inside that
   pin. Adopting OPA means the decision layer's purity guarantee covers the reference engine and
   not the one actually deciding.

---

## What would change this verdict

Stated so the ruling is falsifiable rather than final:

* **The cross-standard rule count reaches ~12–20.** If several standards genuinely compose
  (`factory_autonomy` × `branch_protection` × `testing`), the per-rule saving starts to pay the
  fixed cost. Re-measure then, with the adapter counted.
* **Policy has to be authored or reviewed by someone who does not read Python** — an auditor, a
  downstream repo owner, a compliance reader. Rego's value there is not line count.
* **Decisions must be portable outside HydraFlow's runtime** — evaluated by a different service,
  in a different language, over the same facts. That is what OPA is actually for, and none of it
  is true today.
* **OPA's schema type-checking learns to descend through dynamically-keyed objects** (an
  `additionalProperties` schema applied to values reached by iteration). That alone would remove
  finding 3, the strongest safety objection — the feature already exists and already works on
  static paths; it simply cannot see the shape a fact ledger has. Re-test with the table in
  finding 3 before assuming otherwise.
* **The fact document is restructured so every reference is static** — e.g. one `opa eval` per
  subject with the subject's facts at the document root. That trades the silence for ~88 process
  spawns per run (≈ 1.5 s at the measured ~17 ms floor), which is a different bad trade, but it is
  a real option and it was not measured here.

None of these hold today.

---

## Findings the criterion did not ask about

**The issue's "five ratchet rules" are not five decisions.** The issue framed the Rego as encoding
"exactly the five ratchet rules". Only two of them are per-subject decisions the `DecisionEngine`
protocol can express at all:

| Ratchet rule | Expressible as a `StandardDecision`? |
|---|---|
| new / ungrandfathered debt blocks | **yes** — `VIOLATED`, `blocking` |
| resolved must be genuinely REAL | **yes** — falls out of the ladder |
| debt count non-increasing | **no** — a population claim, not a subject's |
| grandfathered-now-REAL must be marked resolved | **no** — a hygiene claim about the *baseline file*, not about the ADR; both engines correctly call such an ADR `COMPLIANT` |
| exemptions reference existing Accepted ADRs | **no** — a bogus exemption names no Accepted ADR, so it produces no subject and no facts |

This is symmetric — it constrains `PythonDecisionEngine` identically — so it does not tilt the
comparison. But it means the seam does **not** take over the ratchet; it takes over the per-subject
slice, and the ratchet's population and referential-integrity rules stay where they are. Worth
knowing before a future issue assumes otherwise.

**Two `Charter` classes, and the bridge between them is a translation, not a copy — this is a
live trap.** `charter.Charter` (`src/charter.py`) is the full ADR-0143 loader and reads the
filesystem; `policy.models.Charter` is the pure slice the engine may hold. The probe needed
`articles.assurance`, which existed only on the loader, and the engine cannot import the loader
without breaking its import pin — so `assurance` was added to the seam's `CharterArticles` and
`policy.facts.seam_charter()` became the one bridge, in the collector, because crossing it is a
repo read. The default was pinned to `charter.DEFAULT_ASSURANCE` by a test in the one place
allowed to see both, so that copy cannot rot.

**The `standards` field, however, does not survive the crossing, and the pilot's bridge got it
wrong.** The two lists are different vocabularies that overlap on exactly one id:

| | vocabulary | members today |
|---|---|---|
| `charter.Articles.standards` | directories under `docs/standards/<id>/` | `adr_enforcement`, `branch_protection`, `factory_autonomy`, `factory_operation`, `parametrised_guards`, `ports-and-loops`, `testing`, `vitals_conformance` |
| `policy.models.CharterArticles.standards` | standards a `DecisionEngine` can decide | `adr_enforcement`, `adr_conformance` |

`adr_conformance` is a seam standard with no `docs/standards/` directory; the other seven charter
ids are standards no engine decides. So `seam_charter()` — which copied the loader's list straight
across — would have produced a charter under which `Charter.governs("adr_conformance")` is
**False**, and `PythonDecisionEngine.decide` would have silently dropped every `adr_conformance`
fact, turning `AdrConformanceLoop`'s remediation decisions into an empty list. Fail-closed by
design, silent in effect: no decisions reads exactly like no problems.

Nothing caught it because nothing consumed `seam_charter()` — the probe's tests built their
charters by hand. It is reverted with the rest of the pilot, and it is recorded here because the
next person to bridge these two types will reach for the same one-line copy. **The bridge must
translate the id vocabulary (or carry only `assurance` and leave `standards` to the seam's own
default), and it needs a test asserting that a charter built from `charter.yaml` still governs
`adr_conformance`.** A second, cheaper reading: the seam's `standards` field and the charter's are
different enough that they should not share a field name at all — which is ADR-0053's own rule,
applied to the layer whose job is vocabulary.

**One acceptance criterion is unsatisfiable as written.** "MockWorld scenario: the engine selection
(OPA present vs absent) is observable in the loop's evidence record" — no loop decides
`adr_enforcement`. It is a test-time ratchet. The only live consumer of the decision seam is
`AdrConformanceLoop`, which decides `adr_conformance`, the standard this pilot was explicitly
scoped **out** of. Engine selection is instead observable as
`OpaDecisionEngine.availability().reason`, covered by unit tests that run with no OPA installed.

**`PythonDecisionEngine` is not uniformly a re-derivation.** Its `adr_enforcement` lane genuinely
re-derives the ratchet's set arithmetic by an ordered per-subject ladder, which is what makes the
existing parity test meaningful and what made this pilot's comparison fair. Its `adr_conformance`
lane *wraps* `classify_remediation_over`. Every number in this document is from the enforcement
lane; none of it is a comparison against a thin wrapper.

---

## Reproducing this

```bash
make opa-install                 # pinned OPA 1.4.2, vendored per-platform sha256
make opa-test                    # opa fmt --fail --list, opa check --strict, opa test, pytest -m opa
```

The pilot code was removed on the verdict. To rebuild it: the policy is in the appendix below; the
adapter is a `DecisionEngine` implementation that serializes facts to
`{"charter": {"standards": [...], "assurance": "..."}, "subjects": {"<id>": {<key>: <value>}}}` and
runs `opa eval --format=json --data=<policy> --stdin-input '[data.hydraflow.adr_enforcement.decisions, data.hydraflow.adr_enforcement.missing_facts]'`.

---

## Appendix — the policy, in full

Fifty-four code lines. This is the whole of what OPA was asked to decide, probe included.

```rego
package hydraflow.adr_enforcement

# WEAK + MISSING are the unenforced-decision debt (adr_conformance.EnforcementClass).
debt_classes := {"WEAK", "MISSING"}

# Fail closed on thin evidence. Rego's native behaviour is the opposite — an
# absent key makes a rule body simply not fire — so the check is written out.
required_facts := {"enforcement_class", "in_baseline_snapshot", "resolved", "exempt", "binds"}

missing_facts contains msg if {
	some subject, obs in input.subjects
	absent := required_facts - object.keys(obs)
	count(absent) > 0
	msg := sprintf("%s: missing required fact(s) %v", [subject, sort(absent)])
}

# An empty `standards` list governs everything (Charter.governs fails OPEN there
# and only there: no charter written yet is not "nothing is enforced").
governed if count(object.get(input, ["charter", "standards"], [])) == 0

governed if "adr_enforcement" in input.charter.standards

in_debt(obs) if obs.enforcement_class in debt_classes

# The ladder. Order is the whole rule.
status(obs) := "compliant" if not in_debt(obs)

else := "exempt" if obs.exempt

else := "violated" if probe_blocks(obs)

else := "grandfathered" if {
	obs.in_baseline_snapshot
	not obs.resolved
}

else := "violated"

reason(obs) := sprintf("enforcement classifies %s — bound to a real asserting check", [obs.enforcement_class]) if {
	status(obs) == "compliant"
}

else := sprintf("%s but allow-listed as process-only in docs/standards/adr_enforcement/exemptions.md", [obs.enforcement_class]) if {
	status(obs) == "exempt"
}

else := sprintf("%s but carried by the frozen enforcement-debt baseline; shrink-only — pay it down by giving the ADR a real check", [obs.enforcement_class]) if {
	status(obs) == "grandfathered"
}

else := probe_reason(obs) if probe_blocks(obs)

else := sprintf("%s enforcement debt that is neither grandfathered nor exempt", [obs.enforcement_class])

decisions[subject] := d if {
	governed
	count(missing_facts) == 0
	some subject, obs in input.subjects
	verdict := status(obs)
	d := {
		"standard": "adr_enforcement",
		"subject": subject,
		"status": verdict,
		"blocking": verdict == "violated",
		"reason": reason(obs),
		"remediation": remediation(verdict),
	}
}

remediation(verdict) := "file_issue" if verdict == "violated"

else := "none"

# --- the composition probe -------------------------------------------------
# Cross-standard: joins a fact about the SUBJECT (`binds`, ADR-0123) to a fact
# about the REPO (`articles.assurance`, ADR-0143). Prefix-matched because the
# assurance vocabulary is `internal` | `regulated-<name>`, open on the right.

regulated if startswith(object.get(input, ["charter", "assurance"], "internal"), "regulated-")

probe_blocks(obs) if {
	regulated
	obs.binds in {"factory", "both"}
	obs.enforcement_class == "WEAK"
}

probe_reason(obs) := sprintf("WEAK enforcement on a Binds:%s decision under a regulated charter — the ratchet does not carry factory-binding debt in a regulated repo", [obs.binds])
```
