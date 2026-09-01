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

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from data_class_vocabulary import is_valid_data_class

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


@dataclass(frozen=True)
class Artifacts:
    """The Artifacts layer: paths whose presence the repo commits to."""

    required: tuple[str, ...] = ()

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
        return cls(required=required)

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
            schema_version=_as_int(
                "schema_version", data.get("schema_version"), CHARTER_SCHEMA_VERSION
            ),
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
            or self.rails.layers
            or self.rails.domain_gate_scripts
            or self.rails.coverage_floor > 0
        )
