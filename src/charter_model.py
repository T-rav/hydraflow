"""The charter data model — pure, so the decision seam can share it.

``charter.yaml`` is one repo's governing declaration (ADR-0143's PAAA layers,
ADR-0121's rails block). This module holds the SHAPE and its parsing; reading
and writing the file, and computing drift against a live repo, stay in
:mod:`charter` because they touch the world.

The split exists because there were two ``Charter`` classes. ``policy.models``
carried a minimal one — "the slice the decision seam needs ... so the protocol
below can carry its real signature before that lands" — because
:mod:`charter` imports ``yaml`` and reads files, and
``tests/architecture/test_policy_engine_is_pure.py`` holds the policy package
pure. The loader has since landed, so the placeholder's reason to exist has
gone; what remained was two tables over one vocabulary (ADR-0053), the same
defect ``actors:`` refuses by rule (ADR-0143 Ruling 6, guard 3).

Nothing here touches the filesystem, the clock, the network or a subprocess,
and it must stay that way: the decision seam imports it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from data_class_vocabulary import is_regulated_class, is_valid_data_class

CHARTER_FILENAME = "charter.yaml"
CHARTER_SCHEMA_VERSION = 1

#: The pre-#11748 manifest filename. Read for one cycle as a rails-only
#: charter (see :func:`load_charter`); never written.
LEGACY_RAILS_FILENAME = "rails.yaml"
RAILS_SCHEMA_VERSION = 1

#: Where the Actors layer is declared. The charter points at this directory;
#: it never restates what is in it (ADR-0143 Ruling 6, guard 3; the house
#: standard of 2026-08-25, #11741).
ACTORS_DIRECTORY = "agents/"

#: ``articles.assurance`` reuses the repo data-governance vocabulary of
#: ``repo_store.RepoRecord.data_class`` — ``public-code`` / ``internal`` /
#: ``regulated-<name>``. No second scale (#11748).
DEFAULT_ASSURANCE = "internal"

#: Where standard ids resolve, relative to a repo root.
STANDARDS_DIR = "docs/standards"

# Layer names this audit version knows how to verify. The charter TOLERATES
# any other name (forward-compat) — see ``RailsBlock.unknown_layers``.
KNOWN_LAYERS: frozenset[str] = frozenset({"universal", "language_pack", "domain_rails"})

# Finding classes. One drift issue is filed per (repo, finding_class), deduped
# like the branch-protection-drift loop.
FINDING_MISSING_LAYER = "missing-layer"
FINDING_COVERAGE_FLOOR = "coverage-floor"
FINDING_MISSING_GATE_SCRIPT = "missing-gate-script"
FINDING_MISSING_STANDARD = "missing-standard"
FINDING_MISSING_ARTIFACT = "missing-artifact"

#: A governed charter states no intent: `purpose.product` is empty, or it
#: names no goals. Fatal, because Purpose is a precondition rather than a
#: decoration — goal referential integrity has nothing to resolve against an
#: empty goal list, so an unstated purpose silently disables the check above
#: it (#11856, ADR-0143 Amendment 2026-09-01).
FINDING_MISSING_PURPOSE = "missing-purpose"
#: The check itself has no teeth — nothing declared to check, or the shipped
#: standards registry could not be enumerated. Fatal by design: a silent
#: drift check reads as coverage.
FINDING_UNCHECKABLE_CHARTER = "uncheckable-charter"

# Non-fatal classes: REPORTED but never fatal — they never make a report
# "dirty" and never file an issue on their own.
FINDING_UNKNOWN_LAYER = "unknown-layer"
FINDING_UNKNOWN_STANDARD = "unknown-standard"
FINDING_LEGACY_RAILS_MANIFEST = "legacy-rails-manifest"
#: A declared loop names an actor with no contract file. FATAL: the loop
#: cannot run, and a kernel worker handed an unreadable actor would either
#: refuse or — worse — fall back to a default prompt (ADR-0145 Ruling 2).
FINDING_LOOP_WITHOUT_ACTOR = "loop-without-actor"
#: An enumerated actor that no loop names. NON-FATAL: a repo mid-migration
#: looks exactly like this, and enlarging the mandate is a human's ENACT
#: (ADR-0143 Ruling 6 guard 4) — so this files for a person rather than
#: failing a load.
FINDING_ACTOR_WITHOUT_LOOP = "actor-without-loop"

NON_FATAL_FINDING_CLASSES: frozenset[str] = frozenset(
    {
        FINDING_UNKNOWN_LAYER,
        FINDING_UNKNOWN_STANDARD,
        FINDING_LEGACY_RAILS_MANIFEST,
        # Deliberately non-fatal, and the asymmetry with its twin is the
        # point: one-way binding is how `standard.yaml` and its README drifted
        # (#11751), but making BOTH sides fatal would make migration
        # impossible — which is how a guard gets deleted rather than met.
        FINDING_ACTOR_WITHOUT_LOOP,
    }
)

#: Non-fatal classes that must still reach a HUMAN as a filed issue.
#:
#: `NON_FATAL_FINDING_CLASSES` was answering two different questions at once:
#: "does this count as drift?" (it governs `clean`) and "do we file it?" (the
#: caretaker only logs the tolerated ones). Every member until now wanted the
#: same answer to both, so the conflation was invisible.
#:
#: `actor-without-loop` is the first that does not. A repo mid-migration is not
#: broken — failing it would make migration impossible — but enlarging the
#: mandate is a human's ENACT (ADR-0143 Ruling 6 guard 4), so the caretaker's
#: whole job is to put the question in front of one. Logging it would leave the
#: decision with nobody.
ADVISORY_FINDING_CLASSES: frozenset[str] = frozenset({FINDING_ACTOR_WITHOUT_LOOP})

#: check_id suffixes for :data:`FINDING_UNCHECKABLE_CHARTER`.
UNCHECKABLE_NOTHING_DECLARED = "nothing-declared"
UNCHECKABLE_REGISTRY_UNAVAILABLE = "standards-registry-unavailable"


class CharterError(ValueError):
    """A charter that must not load at all.

    Raised for the two rejections that are rulings rather than drift: a role
    list under ``actors``, and an ``assurance`` value outside the
    ``data_class`` vocabulary. Both fail closed — the charter does not load
    with a guessed value, because both control *authority*, and the
    forward-compat tolerance of ADR-0121 was written for template layer
    names, not for who may act or what data may leave the repo.
    """


def _as_str_tuple(field: str, value: Any) -> tuple[str, ...]:
    """Coerce a YAML sequence to a tuple of strings, or reject it.

    A scalar and a mapping both iterate in Python — a string yields its
    characters and a dict yields its keys — so both would be *silently*
    accepted in the wrong shape. Reject them by name instead.
    """
    if value is None:
        return ()
    if isinstance(value, str | bytes | dict):
        msg = f"charter `{field}` must be a list, got {type(value).__name__}: {value!r}"
        raise CharterError(msg)
    return tuple(str(v) for v in value)


def _as_mapping(field: str, value: Any) -> dict[str, Any]:
    """Coerce a YAML block to a mapping, or reject it by name.

    Without this, a wrong-shaped block (``purpose: "a string"``) reaches
    ``raw.get(...)`` and dies as a bare ``AttributeError`` naming neither the
    file nor the key. The charter is hand-edited and reviewed in a pull
    request, so the diagnostic has to name what to fix.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        msg = (
            f"charter `{field}` must be a mapping, got "
            f"{type(value).__name__}: {value!r}"
        )
        raise CharterError(msg)
    return value


def _as_int(field: str, value: Any, default: int) -> int:
    """Coerce a YAML scalar to an int, or reject it by name."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        msg = f"charter `{field}` must be an integer, got {value!r}"
        raise CharterError(msg) from exc


def _as_float(field: str, value: Any) -> float:
    """Coerce a YAML scalar to a float, or reject it by name."""
    if not value:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        msg = f"charter `{field}` must be a number, got {value!r}"
        raise CharterError(msg) from exc


@dataclass(frozen=True)
class Purpose:
    """The Purpose layer: what the repo is trying to do.

    ADR-0143 Ruling 3 left Purpose unchecked and required a ruling before any
    check was added, because "does this repo serve its purpose" is not
    decidable. The operator ruled on 2026-08-31 (ADR-0143 Amendment
    2026-09-01, #11856) and the condition is now satisfied: two *structural*
    claims about Purpose are checkable without pretending to read intent.

    * **Stated** — a governed charter carries a non-empty ``product`` and at
      least one goal. Checked here, as ``missing-purpose`` in
      :func:`charter.compute_charter_drift`.
    * **Anchored** — each goal id is cited by some Article or standard, so a
      goal cannot be pure decoration. That is a cross-surface judgement over
      facts and belongs to the policy seam, not to drift.

    **Semantic conformance stays refused.** Whether the work serves the goals
    is not deterministically decidable, and a judge-model check would rest a
    conformance claim on an external service (#11687). Do not re-propose it.
    """

    product: str = ""
    goals: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Any) -> Purpose:
        raw = _as_mapping("purpose", data)
        return cls(
            product=str(raw.get("product", "") or ""),
            goals=_as_str_tuple("purpose.goals", raw.get("goals")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"product": self.product, "goals": list(self.goals)}


@dataclass(frozen=True)
class LocalArticle:
    """A repo-specific article: a free-form id and a one-line statement.

    The attribute is ``article_id`` while the YAML key stays ``id``. Binding
    ``id`` at class scope shadows the builtin, and
    ``tests/architecture/test_policy_engine_is_pure.py`` refuses all shadowing
    in the pure seam — deliberately, and without a list of dangerous names to
    keep current, because a shadowed name stops its builtin pin from seeing
    that name used at all. The charter schema is unchanged: ``from_dict`` and
    ``to_dict`` both still speak ``id``.
    """

    article_id: str
    statement: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LocalArticle:
        return cls(
            article_id=str(data.get("id", "") or ""),
            statement=str(data.get("statement", "") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.article_id, "statement": self.statement}


@dataclass(frozen=True)
class Articles:
    """The Articles layer: what must remain true of the repo.

    ``standards`` are ids resolving to ``docs/standards/<id>/``. Building
    standards are *one class* of Articles, not the whole of them (ADR-0143
    Ruling 6, guard 2) — ``local`` carries the rest.
    """

    standards: tuple[str, ...] = ()
    assurance: str = DEFAULT_ASSURANCE
    local: tuple[LocalArticle, ...] = ()

    @classmethod
    def from_dict(cls, data: Any) -> Articles:
        raw = _as_mapping("articles", data)
        assurance = str(raw.get("assurance", DEFAULT_ASSURANCE) or DEFAULT_ASSURANCE)
        if not is_valid_data_class(assurance):
            msg = (
                f"charter `articles.assurance` is {assurance!r}, which is not a "
                "data class. It reuses the repo data-governance vocabulary of "
                "`repo_store.RepoRecord.data_class` — `public-code`, `internal`, "
                "or `regulated-<name>` — and there is no second scale (#11748). "
                "Fails closed: an assurance level nothing can honour must not "
                "load as if it could."
            )
            raise CharterError(msg)
        local_raw = raw.get("local") or []
        if isinstance(local_raw, str | bytes | dict):
            msg = (
                "charter `articles.local` must be a list of {id, statement} "
                f"entries, got {type(local_raw).__name__}"
            )
            raise CharterError(msg)
        local: list[LocalArticle] = []
        for item in local_raw:
            if not isinstance(item, dict):
                msg = (
                    "each charter `articles.local` entry must be a mapping with "
                    f"`id` and `statement`, got {type(item).__name__}: {item!r}"
                )
                raise CharterError(msg)
            local.append(LocalArticle.from_dict(item))
        return cls(
            standards=_as_str_tuple("articles.standards", raw.get("standards")),
            assurance=assurance,
            local=tuple(local),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "standards": list(self.standards),
            "assurance": self.assurance,
            "local": [item.to_dict() for item in self.local],
        }


#: The per-change artifact names a charter may require (ADR-0149).
#:
#: Held here, not imported from ``change_chain``, because that module owns the
#: chain's *behaviour* — digests, renderers, filesystem resolution — and
#: importing it would drag ``pathlib.Path`` across this module's purity pin
#: (``tests/architecture/test_policy_engine_is_pure.py``). Same move
#: ``data_class_vocabulary`` already makes: a pure module gets to ask "is this
#: a valid name?" without dragging I/O in behind the answer.
#:
#: Two writers, one set: ``tests/test_charter.py`` binds this to
#: ``ChainArtifact`` so the copy cannot rot.
CHAIN_ARTIFACT_NAMES: frozenset[str] = frozenset(
    {"intent", "criteria", "plan", "evidence"}
)


@dataclass(frozen=True)
class Artifacts:
    """The Artifacts layer: paths whose presence the repo commits to.

    ``required`` names standing paths — directories and files that must
    exist in the repo at all times. ``chain`` names the PER-CHANGE
    artifacts every change must carry (ADR-0149); its entries are artifact
    names, not paths, because a change's directory moves under quarterly
    compaction and a declaration pinned to a path would go stale the first
    time a quarter folded.
    """

    required: tuple[str, ...] = ()
    chain: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Any) -> Artifacts:
        raw = _as_mapping("artifacts", data)
        required = _as_str_tuple("artifacts.required", raw.get("required"))
        for path in required:
            if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
                msg = (
                    f"charter `artifacts.required` entry {path!r} must be a path "
                    "relative to the repo root, with no `..` segments. A charter "
                    "that satisfies itself with a path outside its own repo "
                    "declares nothing about that repo."
                )
                raise CharterError(msg)
        chain = _as_str_tuple("artifacts.chain", raw.get("chain"))
        for name in chain:
            if name not in CHAIN_ARTIFACT_NAMES:
                msg = (
                    f"charter `artifacts.chain` entry {name!r} names no chain "
                    f"artifact. Known: {sorted(CHAIN_ARTIFACT_NAMES)}. A declaration "
                    "naming a subject that cannot exist is worse than no "
                    "declaration — nothing would ever check it."
                )
                raise CharterError(msg)
        return cls(required=required, chain=chain)

    def to_dict(self) -> dict[str, Any]:
        # `chain` is emitted only when declared. Absent and empty are
        # different claims: rendering `chain: []` into a repo that never
        # opted into ADR-0149 writes a positive "this repo requires no chain
        # artifacts" into a file the drift caretaker then audits. Same rule
        # `Charter.to_dict` applies to its own optional blocks.
        rendered: dict[str, Any] = {"required": list(self.required)}
        if self.chain:
            rendered["chain"] = list(self.chain)
        return rendered


@dataclass(frozen=True)
class RailsBlock:
    """The ADR-0121 rails fields, moved under one key, semantics unchanged.

    Declares which template layers a stamped repo carries — universal kernel /
    language pack / domain rails — at what template version, its coverage
    floor, and its domain gate scripts.
    """

    template_version: str = ""
    layers: tuple[str, ...] = ()
    coverage_floor: float = 0.0
    domain_gate_scripts: tuple[str, ...] = ()
    schema_version: int = RAILS_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, data: Any) -> RailsBlock:
        raw = _as_mapping("rails", data)
        return cls(
            template_version=str(raw.get("template_version", "")),
            layers=_as_str_tuple("rails.layers", raw.get("layers")),
            coverage_floor=_as_float("rails.coverage_floor", raw.get("coverage_floor")),
            domain_gate_scripts=_as_str_tuple(
                "rails.domain_gate_scripts", raw.get("domain_gate_scripts")
            ),
            schema_version=_as_int(
                "rails.schema_version", raw.get("schema_version"), RAILS_SCHEMA_VERSION
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "template_version": self.template_version,
            "layers": list(self.layers),
            "coverage_floor": self.coverage_floor,
            "domain_gate_scripts": list(self.domain_gate_scripts),
        }

    @property
    def unknown_layers(self) -> tuple[str, ...]:
        """Declared layer names this audit version does not recognise."""
        return tuple(layer for layer in self.layers if layer not in KNOWN_LAYERS)


def _parse_actors(raw: Any) -> str:
    """Accept a path pointer; reject anything that re-declares roles."""
    if raw is None:
        return ACTORS_DIRECTORY
    if isinstance(raw, str):
        return raw.strip() or ACTORS_DIRECTORY
    msg = (
        "charter `actors` must be a path pointing at the actors directory "
        f"(e.g. `actors: {ACTORS_DIRECTORY}`), not a "
        f"{type(raw).__name__} of roles. Actors are declared by the "
        f"`{ACTORS_DIRECTORY}` tree — role contracts and chamber charters — "
        "which the house standard of 2026-08-25 (#11741) fixes as *the* "
        "Actors declaration. Restating roles in YAML is a second declaration "
        "that will rot (ADR-0143 Ruling 6, guard 3)."
    )
    raise CharterError(msg)


# ---------------------------------------------------------------------------
# schema_version 2: the `loops:` block (ADR-0145)
# ---------------------------------------------------------------------------

CHARTER_SCHEMA_VERSION_V2 = 2
"""The version that may carry a `loops:` block. v1 charters load unchanged."""

#: Files under `agents/` that are documents, not actors.
_NON_ACTOR_FILES = frozenset({"README.md", "runtime.md"})
#: Directories under `agents/` that hold governance records, not actors.
_GOVERNANCE_DIRS = frozenset({"council", "board", "operator"})

#: The only `output.gate` value at v1.1.0. Names what already happens rather
#: than inventing policy (ADR-0145).
_GATE_PR = "pr"


def enumerate_actors(entries: Sequence[str]) -> tuple[str, ...]:
    """Actor names visible in an `agents/` listing. **Pure** over *entries*.

    The predicate is part of the contract, not an implementation detail
    (ADR-0145 guard 1). It accepts BOTH layouts — top-level ``x.md`` and
    ``x/README.md`` — because a narrower "top-level ``*.md`` minus README"
    silently stops seeing an actor the day it moves into a package, and a
    membership test that matches nothing simply returns False while nothing
    reddens. That is this repo's ten-instance path-membership class (#11669),
    and it is why the module→package move has a mutation test.

    *entries* are repo-relative POSIX paths under the actors directory, e.g.
    ``["finance.md", "records/README.md", "council/decisions/0001.md"]``.
    Taking a listing rather than reading a directory keeps this pure and
    keeps enumeration out of the decision half of the seam (ADR-0143 Ruling 5).
    """
    names: list[str] = []
    for entry in entries:
        parts = PurePosixPath(entry).parts
        if not parts or parts[0] in _GOVERNANCE_DIRS:
            continue
        if len(parts) == 1:
            if parts[0].endswith(".md") and parts[0] not in _NON_ACTOR_FILES:
                names.append(parts[0][: -len(".md")])
        elif len(parts) == 2 and parts[1] == "README.md":
            names.append(parts[0])
    return tuple(sorted(set(names)))


def ambiguous_actors(entries: Sequence[str]) -> tuple[str, ...]:
    """Actors declared BOTH as ``x.md`` and ``x/README.md``.

    Two files for one key is the two-tables defect at file granularity
    (ADR-0145). Reported separately from :func:`enumerate_actors` so the
    enumeration stays total and the caller decides that this is fatal.
    """
    flat: set[str] = set()
    packaged: set[str] = set()
    for entry in entries:
        parts = PurePosixPath(entry).parts
        if not parts or parts[0] in _GOVERNANCE_DIRS:
            continue
        if len(parts) == 1 and parts[0].endswith(".md"):
            if parts[0] not in _NON_ACTOR_FILES:
                flat.add(parts[0][: -len(".md")])
        elif len(parts) == 2 and parts[1] == "README.md":
            packaged.add(parts[0])
    return tuple(sorted(flat & packaged))


@dataclass(frozen=True)
class TriggerClause:
    """One clause of a loop's trigger. A loop fires when ANY clause fires.

    ``on:`` is reserved in the schema and REJECTED by the validator at v1.1.0
    (ADR-0145 Ruling 3): it is aspirational even in the evidence repo, whose
    own `loops.yml` header concedes the Operator is the event detector for all
    of them. Shipping a field that looks automatic but needs a human is
    silence-as-failure one field over.
    """

    cron: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"cron": self.cron}


@dataclass(frozen=True)
class LoopOutput:
    """Where a loop's work lands and what gates it."""

    branch_prefix: str = ""
    gate: str = _GATE_PR

    def to_dict(self) -> dict[str, Any]:
        return {"branch_prefix": self.branch_prefix, "gate": self.gate}


@dataclass(frozen=True)
class LoopSpec:
    """One declared loop: an actor, when it runs, and its envelope."""

    name: str
    actor: str
    goal: str = ""
    enabled: bool = False
    triggers: tuple[TriggerClause, ...] = ()
    budget_usd: float | None = None
    timeout_s: int | None = None
    model: str = ""
    output: LoopOutput = field(default_factory=LoopOutput)

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "enabled": self.enabled,
            "trigger": [clause.to_dict() for clause in self.triggers],
            "goal": self.goal,
            "budget_usd": self.budget_usd,
            "timeout_s": self.timeout_s,
            "model": self.model,
            "output": self.output.to_dict(),
        }


@dataclass(frozen=True)
class LoopsBlock:
    """The declared loops, and whether the block was there at all.

    ``present`` is the whole point (ADR-0145 guard 3). A present-but-empty
    ``loops: {}`` declares that NOTHING runs and is valid; a missing block
    means an unmigrated repo. The caretaker skips the second and must not skip
    the first, and a bare tuple cannot tell them apart.
    """

    present: bool = False
    loops: tuple[LoopSpec, ...] = ()

    def by_name(self) -> dict[str, LoopSpec]:
        return {loop.name: loop for loop in self.loops}

    def actors_named(self) -> tuple[str, ...]:
        return tuple(sorted({loop.actor for loop in self.loops}))


@dataclass(frozen=True)
class PolicyBlock:
    """The act-vs-ask policy the charter carries, and whether it was there.

    Held as an OPAQUE mapping on purpose. `merge_policy.load_merge_policy` is
    the schema authority for this content and validates it strictly; teaching
    the charter model the same schema would put two definitions of one thing in
    two files, which is the duplication #12116 exists to remove — reproduced
    inside the fix.

    What this class owes is narrower and load-bearing: round-trip fidelity.
    `Charter.to_dict` emits a fixed key set, so a section the model does not
    carry is silently dropped the first time anything re-renders the charter —
    and dropping THIS section does not fail loudly, it produces a charter whose
    merge gate has no classes at all.

    `present` follows `LoopsBlock`: absent means an unmigrated repo whose
    policy still lives in `docs/standards/factory_autonomy/policy.yaml`;
    present-but-empty is a repo declaring something, and the loader refuses it
    rather than reading it as "nothing is restricted".
    """

    present: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Any) -> PolicyBlock:
        if raw is None:
            return cls()
        return cls(present=True, data=raw if isinstance(raw, dict) else {})

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)


_CRON_FIELDS = 5


def _parse_trigger(loop_name: str, raw: Any) -> tuple[TriggerClause, ...]:
    """Parse a loop's `trigger:` clause list. Cron-only at v1.1.0."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        msg = (
            f"charter `loops.{loop_name}.trigger` must be a LIST of clauses "
            f'(each `- cron: "..."`), not a {type(raw).__name__}. A loop '
            "fires when ANY clause fires, and prose triggers like "
            "'weekly · and on each candidate' are unschedulable as a scalar "
            "(ADR-0145)."
        )
        raise CharterError(msg)
    clauses: list[TriggerClause] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            msg = (
                f"charter `loops.{loop_name}.trigger[{index}]` must be a "
                f"mapping, not a {type(entry).__name__}"
            )
            raise CharterError(msg)
        if "on" in entry:
            msg = (
                f"charter `loops.{loop_name}.trigger[{index}]` uses `on:`, "
                "which is RESERVED but not supported at schema_version 2. "
                "ADR-0145 Ruling 3 defers event triggers to a release that "
                "ships a detector: `on:` is aspirational even in the evidence "
                "repo, whose loops.yml header concedes the Operator is the "
                "event detector for all of them. A field that looks automatic "
                "but requires a human is silence-as-failure. Use a `cron:` "
                "clause and record the event trigger as a documented manual "
                "one until a detector exists."
            )
            raise CharterError(msg)
        cron = entry.get("cron")
        if not isinstance(cron, str) or not cron.strip():
            msg = (
                f"charter `loops.{loop_name}.trigger[{index}]` has no `cron:` "
                "expression; every clause at schema_version 2 must carry one"
            )
            raise CharterError(msg)
        fields = cron.split()
        if len(fields) != _CRON_FIELDS:
            msg = (
                f"charter `loops.{loop_name}.trigger[{index}].cron` is "
                f"{len(fields)}-field ({cron!r}); a 5-field cron expression is "
                "required. An unparseable schedule is a loop that silently "
                "never fires."
            )
            raise CharterError(msg)
        clauses.append(TriggerClause(cron=cron.strip()))
    return tuple(clauses)


def _parse_output(loop_name: str, raw: Any) -> LoopOutput:
    if raw is None:
        return LoopOutput()
    if not isinstance(raw, dict):
        msg = (
            f"charter `loops.{loop_name}.output` must be a mapping, not a "
            f"{type(raw).__name__}"
        )
        raise CharterError(msg)
    gate = str(raw.get("gate", _GATE_PR)).strip() or _GATE_PR
    if gate != _GATE_PR:
        msg = (
            f"charter `loops.{loop_name}.output.gate` is {gate!r}; `pr` is the "
            "only value at v1.1.0 (ADR-0145). It names what already happens "
            "rather than inventing policy."
        )
        raise CharterError(msg)
    return LoopOutput(branch_prefix=str(raw.get("branch_prefix", "") or ""), gate=gate)


def _parse_loop(name: str, raw: Any) -> LoopSpec:
    if not isinstance(raw, dict):
        msg = f"charter `loops.{name}` must be a mapping, not a {type(raw).__name__}"
        raise CharterError(msg)
    # `actor` defaults to the KEY. Many-to-one is legal: two loops may name one
    # actor, which is how the evidence repo runs `records` and
    # `records-quarterly` over one contract (ADR-0145).
    actor = str(raw.get("actor") or name).strip()
    if not actor:
        msg = f"charter `loops.{name}.actor` is empty"
        raise CharterError(msg)
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        msg = (
            f"charter `loops.{name}.enabled` must be true or false, not "
            f"{type(enabled).__name__}. Dormancy is a VALUE here, not a "
            "second list (ADR-0145)."
        )
        raise CharterError(msg)
    budget = raw.get("budget_usd")
    timeout = raw.get("timeout_s")
    return LoopSpec(
        name=name,
        actor=actor,
        goal=str(raw.get("goal", "") or "").strip(),
        enabled=enabled,
        triggers=_parse_trigger(name, raw.get("trigger")),
        budget_usd=float(budget) if isinstance(budget, int | float) else None,
        timeout_s=int(timeout) if isinstance(timeout, int) else None,
        model=str(raw.get("model", "") or "").strip(),
        output=_parse_output(name, raw.get("output")),
    )


def parse_loops(raw: Any, *, present: bool) -> LoopsBlock:
    """Parse the `loops:` block. Raises :class:`CharterError` on a mis-parse.

    A mis-parse fails LOUD (ADR-0145 guard 2). `src/charter.py` already draws
    this line one level up — ``load_charter`` returns None only for a repo with
    NO charter — and the same rule holds here: an unparseable block is an
    error, never an absence, because an absence is indistinguishable from a
    repo that declared nothing runs.
    """
    if not present:
        return LoopsBlock(present=False)
    if raw is None:
        # `loops:` with nothing under it is an empty declaration, not a
        # mis-parse: the author wrote the key.
        return LoopsBlock(present=True)
    if not isinstance(raw, dict):
        msg = (
            f"charter `loops` must be a mapping keyed by LOOP name, not a "
            f"{type(raw).__name__}. Keying by loop (with `actor:` defaulting "
            "to the key) is what lets two loops share one actor (ADR-0145)."
        )
        raise CharterError(msg)
    return LoopsBlock(
        present=True,
        loops=tuple(_parse_loop(name, body) for name, body in sorted(raw.items())),
    )


def unresolved_actors(block: LoopsBlock, actors: Sequence[str]) -> tuple[str, ...]:
    """Loop actors that resolve to no enumerated actor file. FATAL side."""
    known = set(actors)
    return tuple(
        sorted({loop.actor for loop in block.loops if loop.actor not in known})
    )


def actors_without_a_loop(block: LoopsBlock, actors: Sequence[str]) -> tuple[str, ...]:
    """Enumerated actors that no loop names. NON-FATAL side.

    Bidirectional binding is guard 1, and the two sides are deliberately not
    symmetric in severity: a loop naming a missing actor cannot run, while an
    actor no loop names is a repo mid-migration. One-way binding is how
    `standard.yaml` and its README drifted until #11751; making the second
    side fatal would make migration impossible.
    """
    named = {loop.actor for loop in block.loops}
    return tuple(sorted(name for name in set(actors) if name not in named))


@dataclass(frozen=True)
class CharterFinding:
    """One drift finding.

    ``check_id`` is the specific failing check (e.g.
    ``missing-standard:testing``); ``finding_class`` is the coarse bucket the
    issue is filed and deduped under (e.g. ``missing-standard``).
    """

    check_id: str
    finding_class: str
    detail: str


@dataclass(frozen=True)
class Charter:
    """One repo's governing declaration (``charter.yaml``)."""

    purpose: Purpose = field(default_factory=Purpose)
    articles: Articles = field(default_factory=Articles)
    actors: str = ACTORS_DIRECTORY
    artifacts: Artifacts = field(default_factory=Artifacts)
    rails: RailsBlock = field(default_factory=RailsBlock)
    schema_version: int = CHARTER_SCHEMA_VERSION
    #: Non-fatal findings raised while loading (today: the legacy-manifest
    #: fallback). Carried on the charter so the drift report surfaces them
    #: without the loader needing a second return value.
    load_findings: tuple[CharterFinding, ...] = ()
    #: The `loops:` block (schema_version 2, ADR-0145). `present=False` means
    #: an unmigrated repo; `present=True` with no loops means the repo declares
    #: that nothing runs. The caretaker skips the first and must not skip the
    #: second, which is why this is not a bare tuple.
    loops: LoopsBlock = field(default_factory=LoopsBlock)
    #: The `policy:` block (#12116). Opaque here; `merge_policy` validates it.
    policy: PolicyBlock = field(default_factory=PolicyBlock)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Charter:
        """Build a charter from a parsed ``charter.yaml`` mapping.

        Tolerant where ADR-0121 says to be — missing keys take defaults,
        unrecognised standard ids and layer names survive round-trip and are
        reported as non-fatal drift. Strict where authority is at stake:
        :func:`_parse_actors` and ``articles.assurance`` raise
        :class:`CharterError`.
        """
        return cls(
            purpose=Purpose.from_dict(data.get("purpose")),
            articles=Articles.from_dict(data.get("articles")),
            actors=_parse_actors(data.get("actors")),
            artifacts=Artifacts.from_dict(data.get("artifacts")),
            rails=RailsBlock.from_dict(data.get("rails")),
            schema_version=_as_int(
                "schema_version", data.get("schema_version"), CHARTER_SCHEMA_VERSION
            ),
            policy=PolicyBlock.from_dict(data.get("policy")),
            # `"loops" in data` is the absent-vs-empty distinction (guard 3):
            # a v1 charter has no key at all, while `loops:` with nothing under
            # it is a repo declaring that nothing runs.
            loops=parse_loops(data.get("loops"), present="loops" in data),
        )

    @classmethod
    def from_legacy_rails(cls, data: dict[str, Any]) -> Charter:
        """Build a rails-only charter from a legacy ``rails.yaml`` mapping.

        The pre-#11748 file had no purpose / articles / actors / artifacts,
        so those stay at their defaults and only ``rails`` is populated. The
        charter carries a non-fatal ``legacy-rails-manifest`` finding so the
        caretaker reports the fallback without filing on it. No repo had a
        ``rails.yaml`` when this landed — this is cheap insurance for one
        cycle, not a migration.
        """
        return cls(
            rails=RailsBlock.from_dict(data),
            load_findings=(
                CharterFinding(
                    check_id=f"{FINDING_LEGACY_RAILS_MANIFEST}:{LEGACY_RAILS_FILENAME}",
                    finding_class=FINDING_LEGACY_RAILS_MANIFEST,
                    detail=(
                        f"loaded from a legacy `{LEGACY_RAILS_FILENAME}`; rename it "
                        f"to `{CHARTER_FILENAME}` with the rails fields under a "
                        "`rails:` key (ADR-0121 as amended by #11748) — tolerated, "
                        "not fatal"
                    ),
                ),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "purpose": self.purpose.to_dict(),
            "articles": self.articles.to_dict(),
            "actors": self.actors,
            "artifacts": self.artifacts.to_dict(),
            "rails": self.rails.to_dict(),
            # Emitted only when the block is PRESENT, so a round-trip of a v1
            # charter does not silently migrate it (guard 3: absent and empty
            # are different claims, and rendering `loops: {}` for an unmigrated
            # repo would make the second one for it).
            **(
                {"loops": {loop.name: loop.to_dict() for loop in self.loops.loops}}
                if self.loops.present
                else {}
            ),
            # Same present-gating, and for a sharper reason than `loops`: a
            # charter that never declared a policy must not be re-rendered with
            # an empty one, because an empty `policy:` is refused at load and
            # would fail the repo's merges closed on a file nobody edited.
            **({"policy": self.policy.to_dict()} if self.policy.present else {}),
        }

    @classmethod
    def for_standards(cls, *standards: str) -> Charter:
        """A charter placing exactly *standards* in force."""
        return cls(articles=Articles(standards=tuple(standards)))

    def governs(self, standard: str) -> bool:
        """Is *standard* in force? An empty ``standards`` list governs all.

        Fail-OPEN is correct here and only here: an empty article list is "no
        charter has been written yet", not "nothing is enforced". Silently
        deciding nothing would turn the day #11748's loader mis-parses
        ``charter.yaml`` into a green run over zero standards.

        This is NOT in tension with
        :attr:`declares_nothing_checkable`, which the drift check uses: that
        asks whether the charter declares anything checkable AT ALL (a
        conjunction over standards, artifacts, layers, gate scripts and the
        coverage floor) and raises a finding when it does not. Both refuse to
        let an empty declaration read as silent success; they differ only in
        which question they answer.
        """
        return not self.articles.standards or standard in self.articles.standards

    @property
    def declares_nothing_checkable(self) -> bool:
        """True when no declaration in this charter has a check behind it.

        Purpose and ``articles.local`` are deliberately excluded, and Purpose
        stays excluded now that ``missing-purpose`` reads it (#11856). The
        reason changed: it is no longer "nothing checks intent" but that
        *stating* intent is not evidence the repo does anything. A charter
        carrying only a purpose block satisfies ``missing-purpose`` and would
        then report clean while no live subject was ever compared — the exact
        silent pass this property exists to refuse. A local article is prose,
        for the same reason.
        """
        return not (
            self.articles.standards
            or self.artifacts.required
            or self.artifacts.chain
            or self.rails.layers
            or self.rails.domain_gate_scripts
            or self.rails.coverage_floor > 0
        )

    @property
    def is_regulated(self) -> bool:
        """True when ``articles.assurance`` is a ``regulated-*`` class.

        ADR-0143's assurance scale, reused (never a second scale, #11748); a
        decision rule reads this to ask whether the repo's charter puts it
        under a regulated assurance discipline (ADR-0123's factory-binding
        composition probe, #11869).
        """
        return is_regulated_class(self.articles.assurance)
