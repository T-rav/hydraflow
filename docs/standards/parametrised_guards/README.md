# Parametrise over the set the guard iterates

**The rule, in one sentence:**

> **Parametrise over the set the guard actually iterates — the literal
> sequence, by reference.** Not a representative of it. Not a predicate that
> selects from it.

And the diagnostic that goes with it, which is how you tell before you write
the test whether you have found your subject:

> *A rationale that cannot name its enumeration in code has not yet found its
> subject.*

## What the rule replaces

The rule this repo had was **"derive the subject from code, not prose."** It
is not wrong, and it is not enough. A docstring scan *is* code. It satisfies
the older rule while selecting a subset merely **correlated with** the guard's
subject, and the guard then covers part of itself while looking total.

Two instances survived eleven review passes on #11543 — both introduced by
commits **written to close this very class** (#11723):

| | the set the guard iterates | what the fix parametrised over | coverage |
|---|---|---|---|
| **F1** | `legality`, `src/driver_contracts.py` | *"the sharpest of the ordered-table adjacencies"* — one representative | **1 of 10** |
| **F2** | `DECISION_PATH_MODULES`, `tests/architecture/test_director_no_authority.py` | `"no spawn" in doc.lower()` — a docstring predicate | **4 of 10** |

### F1 — a representative of an ordered table

`legality` is an eleven-row first-match rule table. Its test pinned one
adjacency, chosen because it was the sharpest. Nine of the other ten adjacent
swaps survived the full suite, and one of them reproduced the exact harm the
fix was written for: hoisting `writer_conflict` above `writer_foreign` turned a
held-foreign-lease theft event into `writer_lease_held`, downgrading it out of
ADR-0137 B5's counter.

The fixture also did not model what its docstring claimed. `WriterLease(...)`
without `holder_request_id` leaves `is_held` False, so `writer_conflict` could
never be true — the "ordinary theft shape trips BOTH predicates" docstring was
describing a lease nobody held.

### F2 — a predicate that selects a subset

`DECISION_PATH_MODULES` had ten members. The inverse guard written to give it a
drops direction derived its subject from `"no spawn" in doc.lower()`, which
matched four of them. Deleting `src/plan_broker.py` or `src/review_authority.py`
from the list reddened nothing; deleting `src/review_evidence.py` reddened,
because that module happens to use the phrase. The finding the fix was written
against named `review_authority` **by name**, and the fix's subject did not
match it.

Worse, the direction was one-way: nothing checked that a *listed* module still
made the claim, so two individually-green edits — reword the docstring, then
drop the list entry — removed a module from every guard in the file.

## The gate

> For every parametrised architecture guard, assert that deleting any member of
> its subject sequence reddens something.

For this needle, **detection and fix are the same artifact**: the gate *is* the
class check. The registry lives at
`tests/architecture/guard_enumeration_registry.py` and the properties at
`tests/architecture/test_guard_enumeration_gate.py`.

### Subject or corpus — classify first

Not every sequence a `@pytest.mark.parametrize` iterates is a *subject*.

- A **subject** is the thing being guarded: the modules held to a rule, the
  names a module may not call, the rows of an ordered rule table. Dropping a
  member silently narrows what the guard covers. Subjects must be
  drop-detected.
- A **corpus** is the guard's *evidence*: synthetic sources fed to a detector
  to prove the detector sees each shape. Dropping a member drops a test case,
  which is a coverage question, not a "the gate stopped seeing its subject"
  question.

Every module-level sequence fed to `parametrize` under `tests/architecture/`
must be classified. A corpus classification carries a written reason and the
count of them is ratcheted shrink-only, exactly as
`path_membership_registry`'s `package_blind_reason` is.

### Three mechanisms for drop-detection

Which one applies is decided by the subject, not by taste.

**Derived** — for membership lists (`DECISION_PATH_MODULES`, `ACTUATORS`,
`_PROPOSAL_KEYS`, the canary family, the `PHASE_NOT_*` refusal rows). Pin the
literal against a derivation that independently reproduces it, in **both**
directions: `derived == literal`. Dropping a member breaks `derived ⊆ literal`;
adding an unlisted one breaks `literal ⊇ derived`.

The derivation must be **total for the literal**. A derivation that reproduces
four of ten members is F2 again, so where no total derivation existed one was
*created*: each decision-path module now carries the sentence `Decision path,
no authority.` in its own docstring, and the guard derives the list from that.
The module declares itself, and the declaration and the enumeration have to
travel together — the two individually-green edits that used to remove a module
from every guard in the file now redden one each.

**Witnessed** — for ordered rule tables (`legality`, `fencing`). Every row gets
an input for which `admit_dispatch` must answer with exactly that row's reason.
No other row in the same table carries the same reason, so deleting a row makes
its witness unanswerable, and a witness that also satisfies rows below it pins
the precedence an adjacent swap would break.

**Floored** — for deny-lists of call names (`FORBIDDEN_MUTATIONS`,
`CONVERGENCE_WRITES`, `WRITE_PRIMITIVES`, `_SPAWN_MACHINERY`).

These have no derivation, and the reason is worth stating because it is the
trap: a deny-list names calls that must *not* appear, and most of these name
nothing in this repo at all. `ConvergenceLedger` really has
`increment_route_backs` and `recompute_converged`; the other six
`CONVERGENCE_WRITES` members are forward-looking needles, and `src/ports.py`
defines none of the fifteen `FORBIDDEN_MUTATIONS`. **Any derivation would
reproduce a strict subset — which is F2 again, inside the gate written to catch
it.** An earlier draft of this gate witnessed each member by injecting a call
into a real module and asking whether the extractor saw it; that answers *yes*
for any name at all, never consults the deny-list, and passed while `merge_pr`
was deleted.

So the protection is a **shrink-only floor**: an independently written
high-water mark, asserted as `floor ⊆ live`. The deny-list may grow freely and
a new member needs no ceremony; a member that has ever been denied cannot
quietly stop being. It is not a second copy of a vocabulary — it records where
the guard has been, not what the guard is, which is the same shape as the
repo's `GRANDFATHERED_*` baselines inverted.

The floor is kept honest by the witness it replaced, applied to *live* members
rather than used as the detector: every member of every deny-list is injected
into a real subject module and must trip the guard's own extractor. That stops
a floor entry rotting into a name nothing could ever match (the #11669 class
applied to call names), and it catches a shape mismatch on the way in —
`called_names` records `run`, not `subprocess.run`, so a dotted member would
sit in a deny-list forever catching nothing.

Known limit, stated rather than hidden: a floor catches a plain drop, not a
swap that removes one member and adds another in the same edit. A derivation
would; there isn't one.

### Four ways a gate like this goes vacuous, and the property that stops each

1. **The sweep has no subject.** An empty registry, or one whose rows resolve
   to nothing, passes every parametrised assertion because there is nothing to
   assert. `test_the_registry_is_not_empty` and
   `test_every_subject_resolves_to_a_non_empty_sequence` are the answer, and
   the second must *resolve*, not check presence.
2. **The gate asserts presence instead of resolution.** A sibling PR shipped
   `test_the_owner_still_owns_it`, which asserted a literal was present in a
   file and was vacuously satisfiable. Every property here calls the live
   predicate and reads its answer.
3. **The derivation degenerates.** A derivation that starts returning nothing
   makes `derived ⊆ literal` trivially true. `test_a_degenerate_detector_is_a_failure`
   feeds each subject a detector that has degenerated to matching nothing and
   asserts the comparison **fails**. It doubles as the proof that
   `detects_drop` is *consulted* rather than assumed: swapping the callable
   changes the outcome, so the callable is what the gate reads.
4. **The detector reads its own subject.** Two sets derived from one source
   agree by construction, so their equality is not a question. This one is not
   hypothetical: `registered_canaries()` first returned `discovered_canaries()`,
   and `_PHASE_ROWS`'s detector first re-derived the same enum `_PHASE_ROWS` is
   derived from — both caught in self-review, both inside the gate written to
   catch them. The registry rule that follows is: **`members` and
   `detects_drop` must resolve different objects.** A detector that has gone
   further and regressed to `return True` is caught mechanically by
   `test_a_detector_rejects_a_member_that_was_never_there`; a detector reading
   the same source as its members is caught only by looking, which is why it is
   written down here.

### Registering a new enumeration

Add a row to `registered_enumerations()` in
`tests/architecture/guard_enumeration_registry.py`:

- `name` — `<module>.<ATTRIBUTE>`, unique.
- `members` — resolved **by reference** from the live literal
  (`director_guard.DECISION_PATH_MODULES`), never re-typed.
- `detects_drop` — a callable over one member that exercises the **live**
  machinery and answers "would removing this member be caught?". Not a
  re-implementation of the guard; the guard itself.
- `why` — what silently stops being guarded when a member goes uncovered.

Registration is manual and explicit for the same reason
`path_membership_registry`'s is: discovery-by-convention would be the failure
mode one level up. What is *not* manual is noticing an unregistered
enumeration — `test_every_parametrised_arch_sequence_is_classified` scans
`tests/architecture/` and reddens on one nobody classified.

## Two builds, one rule

This rule has more than one implementation because more than one mechanism
produces the defect:

- **#11723** — literal sequences in source. Implemented by the registry above.
- **#11715** — a hand-maintained enumeration standing in for a set produced at
  *runtime* by a repo scan, with drift detection in only one direction.
  Implemented separately (PR #11722) because neither fix covers the other:
  this gate cannot see a set that does not exist until a scan runs, and an
  aggregator job cannot see a tuple in a test file.

Both are the same rule. Write a third implementation before you write a third
rule.

## Related

- [`docs/standards/testing/README.md`](../testing/README.md) — the three-layer
  test pyramid this sits inside.
- [`docs/standards/vitals_conformance/README.md`](../vitals_conformance/README.md)
  — *"a conformance check that stops running must fail, not pass"*, which is
  this rule's parent.
- [ADR-0051](../../adr/0051-iterative-production-readiness-review.md) —
  iterative production-readiness review. #11723's own argument for why this is
  a gate and not a twelfth reviewer pass: across passes 6–11 the rate of
  finding this shape and the rate of fixing it were equal, which is a fixed
  point rather than a convergence.
