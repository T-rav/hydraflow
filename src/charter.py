"""The repo charter (``charter.yaml``) — schema + drift comparison (#11748).

A **charter** is the governing declaration a HydraFlow-governed repository
carries at its root. It is the Articles surface of the PAAA model
(ADR-0143): a factory arriving at a repo cold reads it to answer *what is
this trying to do*, *what rules apply*, *who may change what*, and *what
evidence exists* — from the repo, without institutional memory.

It supersedes the ``rails.yaml`` manifest of ADR-0121. The rails fields fold
under a ``rails:`` key with their semantics unchanged; the name changed
because "rails" means *template layers*, and the file now states purpose,
articles, actors and artifacts as well (naming ruled 2026-08-28, recorded in
ADR-0143's Consequences).

::

    schema_version: 1
    purpose:
      product: "..."
      goals: [...]
    articles:
      standards: [testing, ports-and-loops]   # ids -> docs/standards/<id>/
      assurance: internal                     # RepoRecord.data_class vocabulary
      local:
        - id: staging_only_prs
          statement: "..."
    actors: agents/                           # pointer ONLY, never a role list
    artifacts:
      required: [docs/adr, ...]
    rails:                                    # ADR-0121, semantics unchanged
      schema_version: 1
      template_version: "1"
      layers: [universal, language_pack]
      coverage_floor: 85
      domain_gate_scripts: []

Two guards from ADR-0143 shape this module, and they are rulings rather than
preferences:

* **Actors are declared by the ``agents/`` tree, never re-declared here**
  (Ruling 6, guard 3). ``actors`` is a *path pointer*. A role list is
  rejected at load with :class:`CharterError` — two declarations of who may
  act is one too many, and the copy rots.
* **This is HydraFlow's implementation surface, not "the PAAA spec"**
  (Ruling 6, guard 1). PAAA is an ontology; nothing outside HydraFlow is
  asked to conform to these keys.

What is *tolerated* and what is *fatal* follows ADR-0121's tolerance rule,
extended to the new declarations:

===========================  =========  ==================================
finding class                fatal?     meaning
===========================  =========  ==================================
``missing-layer``            yes        declared template layer is gone
``coverage-floor``           yes        observed coverage below the floor
``missing-gate-script``      yes        declared gate script is gone
``missing-standard``         yes        declared standard this factory
                                        ships, absent from the repo
``missing-artifact``         yes        declared required path is absent
``uncheckable-charter``      yes        the check has nothing to check, or
                                        could not be performed
``unknown-layer``            no         future/unrecognised layer name
``unknown-standard``         no         id neither carried nor shipped
``legacy-rails-manifest``    no         loaded from a legacy ``rails.yaml``
===========================  =========  ==================================

``uncheckable-charter`` is the guard against the failure this repo has spent
a week clearing: a drift check whose subject list is empty passes silently
and *reads as coverage*. A charter that declares nothing checkable, or one
that declares standards while the shipped registry cannot be enumerated,
fails loudly instead.

:func:`compute_charter_drift` is **pure over its two inputs** (ADR-0143
Ruling 5 — the decision layer never touches the filesystem). Every path
resolution happens in the observation step; that is why
:func:`~charter_drift_caretaker_loop.observe_repo` takes the charter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from prompt_gate import is_valid_data_class

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
#: The check itself has no teeth — nothing declared to check, or the shipped
#: standards registry could not be enumerated. Fatal by design: a silent
#: drift check reads as coverage.
FINDING_UNCHECKABLE_CHARTER = "uncheckable-charter"

# Non-fatal classes: REPORTED but never fatal — they never make a report
# "dirty" and never file an issue on their own.
FINDING_UNKNOWN_LAYER = "unknown-layer"
FINDING_UNKNOWN_STANDARD = "unknown-standard"
FINDING_LEGACY_RAILS_MANIFEST = "legacy-rails-manifest"

NON_FATAL_FINDING_CLASSES: frozenset[str] = frozenset(
    {
        FINDING_UNKNOWN_LAYER,
        FINDING_UNKNOWN_STANDARD,
        FINDING_LEGACY_RAILS_MANIFEST,
    }
)

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


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str | bytes):
        msg = f"expected a list, got a scalar: {value!r}"
        raise CharterError(msg)
    return tuple(str(v) for v in value)


@dataclass(frozen=True)
class Purpose:
    """The Purpose layer: what the repo is trying to do.

    ADR-0143 Ruling 3 names Purpose the one layer nothing checks. The charter
    carries it so it has a declaration surface at all; **no drift check reads
    it**, and none should be added without a ruling that says what checking
    intent would even mean.
    """

    product: str = ""
    goals: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Purpose:
        raw = data or {}
        return cls(
            product=str(raw.get("product", "") or ""),
            goals=_as_str_tuple(raw.get("goals")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"product": self.product, "goals": list(self.goals)}


@dataclass(frozen=True)
class LocalArticle:
    """A repo-specific article: a free-form id and a one-line statement."""

    id: str
    statement: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LocalArticle:
        return cls(
            id=str(data.get("id", "") or ""),
            statement=str(data.get("statement", "") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "statement": self.statement}


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
    def from_dict(cls, data: dict[str, Any] | None) -> Articles:
        raw = data or {}
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
        return cls(
            standards=_as_str_tuple(raw.get("standards")),
            assurance=assurance,
            local=tuple(LocalArticle.from_dict(dict(item)) for item in local_raw),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "standards": list(self.standards),
            "assurance": self.assurance,
            "local": [item.to_dict() for item in self.local],
        }


@dataclass(frozen=True)
class Artifacts:
    """The Artifacts layer: paths whose presence the repo commits to."""

    required: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Artifacts:
        raw = data or {}
        return cls(required=_as_str_tuple(raw.get("required")))

    def to_dict(self) -> dict[str, Any]:
        return {"required": list(self.required)}


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
    def from_dict(cls, data: dict[str, Any] | None) -> RailsBlock:
        raw = data or {}
        return cls(
            template_version=str(raw.get("template_version", "")),
            layers=_as_str_tuple(raw.get("layers")),
            coverage_floor=float(raw.get("coverage_floor", 0.0) or 0.0),
            domain_gate_scripts=_as_str_tuple(raw.get("domain_gate_scripts")),
            schema_version=int(raw.get("schema_version", RAILS_SCHEMA_VERSION)),
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
            schema_version=int(data.get("schema_version", CHARTER_SCHEMA_VERSION)),
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
        }

    @property
    def declares_nothing_checkable(self) -> bool:
        """True when no declaration in this charter has a check behind it.

        Purpose and ``articles.local`` are deliberately excluded: nothing
        checks intent (ADR-0143 Ruling 3), and a local article is prose. A
        charter of only those is a charter the drift check cannot speak to.
        """
        return not (
            self.articles.standards
            or self.artifacts.required
            or self.rails.layers
            or self.rails.domain_gate_scripts
            or self.rails.coverage_floor > 0
        )


@dataclass(frozen=True)
class ObservedRepo:
    """What a repo actually carries right now (gathered live).

    ``coverage`` is ``None`` when it cannot be determined — the coverage floor
    is then *not* evaluated (fail-open: never file drift on a measurement we
    could not take).

    ``known_standards`` is the set of standard ids this factory can recognise
    — its own shipped ``docs/standards/`` union the target repo's. ``None``
    means the registry could not be enumerated at all, which is a *fault*, not
    an empty set: with an empty registry every declared id would look like a
    tolerated future id and the check would pass in silence. Hence the
    fail-loud default.
    """

    present_layers: frozenset[str] = frozenset()
    coverage: float | None = None
    present_gate_scripts: frozenset[str] = frozenset()
    present_standards: frozenset[str] = frozenset()
    present_artifacts: frozenset[str] = frozenset()
    known_standards: frozenset[str] | None = None


@dataclass(frozen=True)
class CharterDriftReport:
    """Result of auditing one repo's live state against its charter."""

    repo: str
    findings: tuple[CharterFinding, ...] = ()
    # ``False`` means the repo carries no charter — it is ungoverned by the
    # charter contract, distinct from "governed and clean" (empty findings).
    has_charter: bool = True

    @property
    def clean(self) -> bool:
        """True when there is no *fatal* drift.

        Non-fatal findings (unknown layer / unknown standard / legacy
        manifest) are reported but do not count as drift — forward-compat,
        ADR-0121.
        """
        return not self.fatal_findings

    @property
    def fatal_findings(self) -> tuple[CharterFinding, ...]:
        return tuple(
            f for f in self.findings if f.finding_class not in NON_FATAL_FINDING_CLASSES
        )

    @property
    def tolerated_findings(self) -> tuple[CharterFinding, ...]:
        return tuple(
            f for f in self.findings if f.finding_class in NON_FATAL_FINDING_CLASSES
        )


def _layer_findings(charter: Charter, observed: ObservedRepo) -> list[CharterFinding]:
    findings: list[CharterFinding] = []
    for layer in charter.rails.unknown_layers:
        findings.append(
            CharterFinding(
                check_id=f"{FINDING_UNKNOWN_LAYER}:{layer}",
                finding_class=FINDING_UNKNOWN_LAYER,
                detail=(
                    f"charter declares layer '{layer}', which this audit "
                    "version does not recognise — tolerated (forward-compat)"
                ),
            )
        )
    for layer in charter.rails.layers:
        if layer in KNOWN_LAYERS and layer not in observed.present_layers:
            findings.append(
                CharterFinding(
                    check_id=f"{FINDING_MISSING_LAYER}:{layer}",
                    finding_class=FINDING_MISSING_LAYER,
                    detail=(
                        f"charter declares the '{layer}' layer but the repo "
                        "no longer carries it"
                    ),
                )
            )
    return findings


def _standard_findings(
    charter: Charter, observed: ObservedRepo
) -> list[CharterFinding]:
    """Split declared-but-absent standards into fatal and tolerated.

    A declared id absent from the repo is ``missing-standard`` (fatal) when
    this factory ships a standard by that id — the repo dropped something
    real. When neither the repo nor the factory knows the id it is
    ``unknown-standard`` (tolerated), the same forward-compat rule ADR-0121
    applies to layer names.
    """
    findings: list[CharterFinding] = []
    known = observed.known_standards
    for standard in charter.articles.standards:
        if standard in observed.present_standards:
            continue
        if known is not None and standard in known:
            findings.append(
                CharterFinding(
                    check_id=f"{FINDING_MISSING_STANDARD}:{standard}",
                    finding_class=FINDING_MISSING_STANDARD,
                    detail=(
                        f"charter declares the '{standard}' standard but "
                        f"`{STANDARDS_DIR}/{standard}/` is absent from the repo"
                    ),
                )
            )
            continue
        findings.append(
            CharterFinding(
                check_id=f"{FINDING_UNKNOWN_STANDARD}:{standard}",
                finding_class=FINDING_UNKNOWN_STANDARD,
                detail=(
                    f"charter declares standard id '{standard}', which neither "
                    "the repo nor this factory carries — tolerated "
                    "(forward-compat)"
                ),
            )
        )
    return findings


def _uncheckable_findings(
    charter: Charter, observed: ObservedRepo
) -> list[CharterFinding]:
    """Fail loudly when the drift check has nothing, or no way, to check.

    Both branches exist because a silent drift check is worse than none: it
    reads as coverage. An empty declaration and an un-enumerable standards
    registry both produce zero findings on every other path.
    """
    findings: list[CharterFinding] = []
    if charter.declares_nothing_checkable:
        findings.append(
            CharterFinding(
                check_id=(
                    f"{FINDING_UNCHECKABLE_CHARTER}:{UNCHECKABLE_NOTHING_DECLARED}"
                ),
                finding_class=FINDING_UNCHECKABLE_CHARTER,
                detail=(
                    f"`{CHARTER_FILENAME}` declares no standards, no required "
                    "artifacts, no template layers, no gate scripts and no "
                    "coverage floor — the drift check has nothing to check, so "
                    "a clean report would mean nothing"
                ),
            )
        )
    if charter.articles.standards and observed.known_standards is None:
        findings.append(
            CharterFinding(
                check_id=(
                    f"{FINDING_UNCHECKABLE_CHARTER}:{UNCHECKABLE_REGISTRY_UNAVAILABLE}"
                ),
                finding_class=FINDING_UNCHECKABLE_CHARTER,
                detail=(
                    "the standards registry could not be enumerated, so every "
                    "declared standard id would be tolerated as unknown and no "
                    "`missing-standard` could ever fire"
                ),
            )
        )
    return findings


def compute_charter_drift(
    charter: Charter, observed: ObservedRepo, *, repo: str
) -> CharterDriftReport:
    """Compare a repo's declared charter against its observed live state.

    Pure over ``(charter, observed)`` — it reads no files, runs no commands
    and touches no git (ADR-0143 Ruling 5). Every path resolution happened in
    the observation step.

    Rules:

    * a **missing declared layer / standard / required artifact / gate
      script** is drift, and so is observed coverage below the declared floor
      (evaluated only when coverage is known);
    * an **undeclared extra** of any kind is fine and never reported;
    * an **unknown layer name or standard id** is tolerated and reported;
    * a charter with **nothing checkable**, or one whose standard ids cannot
      be resolved against any registry, is fatal — see
      :func:`_uncheckable_findings`.
    """
    findings: list[CharterFinding] = list(charter.load_findings)
    findings.extend(_uncheckable_findings(charter, observed))
    findings.extend(_layer_findings(charter, observed))
    findings.extend(_standard_findings(charter, observed))

    for path in charter.artifacts.required:
        if path not in observed.present_artifacts:
            findings.append(
                CharterFinding(
                    check_id=f"{FINDING_MISSING_ARTIFACT}:{path}",
                    finding_class=FINDING_MISSING_ARTIFACT,
                    detail=(
                        f"charter declares required artifact '{path}' but it is "
                        "absent from the repo"
                    ),
                )
            )

    floor = charter.rails.coverage_floor
    if floor > 0 and observed.coverage is not None and observed.coverage < floor:
        findings.append(
            CharterFinding(
                check_id=f"{FINDING_COVERAGE_FLOOR}:{floor:g}",
                finding_class=FINDING_COVERAGE_FLOOR,
                detail=(
                    f"coverage {observed.coverage:g}% is below the declared "
                    f"floor of {floor:g}%"
                ),
            )
        )

    for script in charter.rails.domain_gate_scripts:
        if script not in observed.present_gate_scripts:
            findings.append(
                CharterFinding(
                    check_id=f"{FINDING_MISSING_GATE_SCRIPT}:{script}",
                    finding_class=FINDING_MISSING_GATE_SCRIPT,
                    detail=(
                        f"charter declares domain gate script '{script}' but "
                        "it is absent from the repo"
                    ),
                )
            )

    return CharterDriftReport(repo=repo, findings=tuple(findings))


# --------------------------------------------------------------------------- #
# Load / render / write                                                        #
# --------------------------------------------------------------------------- #


def standard_ids_under(root: Path) -> frozenset[str]:
    """Standard ids carried by the tree at *root* (``docs/standards/<id>/``).

    A standard is a *directory* — ``docs/standards/testing/`` — so a repo
    carrying only a loose ``docs/standards/testing.md`` declares no ids. The
    per-standard id file of #11751 lives inside that directory.
    """
    standards = root / STANDARDS_DIR
    if not standards.is_dir():
        return frozenset()
    return frozenset(p.name for p in standards.iterdir() if p.is_dir())


def _read_mapping(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return None
    return raw


def load_charter(repo_root: Path) -> Charter | None:
    """Load ``<repo_root>/charter.yaml``, or ``None`` if the repo has none.

    Falls back for one cycle to a legacy ``rails.yaml``, loaded as a
    rails-only charter carrying a non-fatal ``legacy-rails-manifest``
    finding. ``None`` means the repo is ungoverned by the charter contract —
    distinct from a present-but-empty file, which yields a default charter
    and a fatal ``uncheckable-charter`` finding at drift time.
    """
    raw = _read_mapping(repo_root / CHARTER_FILENAME)
    if raw is not None:
        return Charter.from_dict(raw)
    legacy = _read_mapping(repo_root / LEGACY_RAILS_FILENAME)
    if legacy is not None:
        return Charter.from_legacy_rails(legacy)
    return None


_CHARTER_HEADER = (
    "# HydraFlow charter (charter.yaml) — the repo's governing declaration.\n"
    "#\n"
    "# Purpose / Articles / Actors / Artifacts per ADR-0143; the `rails:` block\n"
    "# is ADR-0121 with its semantics unchanged. `charter_drift_caretaker` files\n"
    "# a drift issue when live state diverges from what is declared here, so\n"
    "# edit deliberately. Unknown layer names and standard ids are tolerated.\n"
    "#\n"
    "# `actors` is a POINTER, never a role list: the agents/ tree is the Actors\n"
    "# declaration (house standard 2026-08-25, #11741).\n"
)


def render_charter(charter: Charter) -> str:
    """Render a charter to YAML text (with an explanatory header comment)."""
    body = yaml.safe_dump(charter.to_dict(), sort_keys=False, default_flow_style=False)
    return _CHARTER_HEADER + body


def write_charter(repo_root: Path, charter: Charter) -> Path:
    """Write ``<repo_root>/charter.yaml`` and return its path."""
    path = repo_root / CHARTER_FILENAME
    path.write_text(render_charter(charter), encoding="utf-8")
    return path


def charter_from_snapshot(
    snapshot: dict[str, Any], *, standards: tuple[str, ...] = ()
) -> Charter:
    """Build a charter from an onboarding standards snapshot.

    The onboarding standards snapshot (``.hydraflow/standards-snapshot.json``)
    already carries ``coverage_floor`` and ``tech_stack``; this maps it onto
    the charter so stamping / onboarding writes both from one source (ADR-0121
    Ruling 2). Every stamped repo carries the universal kernel and a language
    pack; a domain-rails layer is declared when the snapshot names one.

    ``standards`` are the standard ids the stamp actually copied in, so a
    stamped charter never declares a standard the stamp did not deliver.
    """
    layers: list[str] = ["universal", "language_pack"]
    if snapshot.get("domain_rails") or snapshot.get("domain"):
        layers.append("domain_rails")
    scripts = _as_str_tuple(snapshot.get("domain_gate_scripts"))
    description = str(snapshot.get("description", "") or "")
    return Charter(
        purpose=Purpose(product=description),
        articles=Articles(standards=tuple(standards)),
        artifacts=Artifacts(required=("docs/adr",)),
        rails=RailsBlock(
            template_version=str(snapshot.get("template_version", "1")),
            layers=tuple(layers),
            coverage_floor=float(snapshot.get("coverage_floor", 0.0) or 0.0),
            domain_gate_scripts=scripts,
        ),
    )
