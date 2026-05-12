# Coverage Matrix Baseline

**Snapshot date:** 2026-05-12
**Audit commit SHA:** `de42e482cfce04eb8a584a2e4ebeb02cb96aa35d`
**Spec:** `docs/superpowers/specs/2026-05-12-coverage-matrix-design.md`
**Automation follow-up bead:** `<paste bead ID after Task 14>`

## Column criteria

(Copy verbatim from the spec, §4. Reproduced here so the matrix is self-contained.)

### Loops table

- **ADR.** `grep -l "LoopName" docs/adr/*.md` returns ≥1 file where the loop is referenced in body prose. Cell shows ADR number + status (Proposed / Accepted / Superseded).
- **Wiki.** `grep -l "LoopName" docs/wiki/*.md` returns ≥1 substantive match (not bare cross-link).
- **Generated.** Loop appears in `docs/arch/generated/loops.md` with non-`—` Tick AND Kill Switch columns.
- **Standard.** Loop bound by a rule in `docs/standards/**/README.md` (roll-up rules count).
- **Unit tests.** `tests/test_<snake_case_loop>*.py` exists with ≥1 test exercising the class directly.
- **MockWorld scenario.** Loop in `tests/scenarios/catalog/loop_registrations.py` AND scenario file invokes it.
- **Sandbox e2e.** Loop exercised in `tests/sandbox_scenarios/scenarios/`.

### Ports table

- **ADR / Wiki / Generated / Standard.** Same predicates with PortName.
- **Fake adapter.** `Fake<PortName>` class under `tests/scenarios/fakes/` implementing every Protocol method (ADR-0047).
- **Cassette tests.** `tests/trust/contracts/cassettes/<port>/` exists with recordings.
- **Contract test.** Test asserts fake satisfies same contract as real adapter (ADR-0047).

### Phases table

- **ADR / Wiki / Standard.** Phase named in substantive prose.
- **Loops driving it.** Hand-mapped against `factory_operation/README.md` and `docs/arch/generated/labels.md`.
- **Escalation path.** One sentence: what event or label transition fires on failure / stall.
- **HITL trigger.** One sentence: condition that escalates to human. Cells reading "human always reviews" are explicit signal for a slice #4 drift bead.

## Cell vocabulary

- ✅ followed by ref (ADR number, wiki path, test path).
- ⚠️ followed by what's missing + `[bd:N]`.
- ❌ followed by `[bd:N]`.
- N/A when column doesn't apply (must be justified inline).

## Aliases

(Populated during extraction. Maps row name to extra grep-matching strings.)

## Excluded refs

(Populated during extraction. Per-row list of files whose mention does not count.)

---

## Section 1: Loops (41 × 7)

| Loop | ADR | Wiki | Generated | Standard | Unit | Scenario | Sandbox |
|---|---|---|---|---|---|---|---|
<!-- rows populated in Task 9 -->

## Section 2: Ports (9 × 7)

| Port | ADR | Wiki | Generated | Standard | Fake | Cassette | Contract |
|---|---|---|---|---|---|---|---|
<!-- rows populated in Task 10 -->

## Section 3: Factory phases (8 × 6)

| Phase | ADR | Wiki | Standard | Loops driving it | Escalation path | HITL trigger |
|---|---|---|---|---|---|---|
<!-- rows populated in Task 11 -->

## Sampling check

(Populated in Task 13.)

## Counts reconciliation

(Populated in Task 13.)
