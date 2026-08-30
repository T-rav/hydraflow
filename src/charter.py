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

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Re-exported so every existing `from charter import X` keeps working; the
# model itself lives in a pure module the decision seam can also import.
from charter_model import (
    ACTORS_DIRECTORY,
    CHARTER_FILENAME,
    CHARTER_SCHEMA_VERSION,
    DEFAULT_ASSURANCE,
    FINDING_COVERAGE_FLOOR,
    FINDING_LEGACY_RAILS_MANIFEST,
    FINDING_MISSING_ARTIFACT,
    FINDING_MISSING_GATE_SCRIPT,
    FINDING_MISSING_LAYER,
    FINDING_MISSING_STANDARD,
    FINDING_UNCHECKABLE_CHARTER,
    FINDING_UNKNOWN_LAYER,
    FINDING_UNKNOWN_STANDARD,
    KNOWN_LAYERS,
    LEGACY_RAILS_FILENAME,
    NON_FATAL_FINDING_CLASSES,
    RAILS_SCHEMA_VERSION,
    STANDARDS_DIR,
    UNCHECKABLE_NOTHING_DECLARED,
    UNCHECKABLE_REGISTRY_UNAVAILABLE,
    Articles,
    Artifacts,
    Charter,
    CharterError,
    CharterFinding,
    LocalArticle,
    Purpose,
    RailsBlock,
    _as_float,
    _as_int,
    _as_mapping,
    _as_str_tuple,
    _parse_actors,
)

#: Re-exported from :mod:`charter_model`. Declared rather than suppressed:
#: a `noqa` would be a new entry in the suppressions ratchet, which only
#: shrinks, and `__all__` states the same intent as an export contract.
__all__ = [
    "ACTORS_DIRECTORY",
    "Articles",
    "Artifacts",
    "CHARTER_FILENAME",
    "CHARTER_SCHEMA_VERSION",
    "Charter",
    "CharterError",
    "CharterFinding",
    "DEFAULT_ASSURANCE",
    "FINDING_COVERAGE_FLOOR",
    "FINDING_LEGACY_RAILS_MANIFEST",
    "FINDING_MISSING_ARTIFACT",
    "FINDING_MISSING_GATE_SCRIPT",
    "FINDING_MISSING_LAYER",
    "FINDING_MISSING_STANDARD",
    "FINDING_UNCHECKABLE_CHARTER",
    "FINDING_UNKNOWN_LAYER",
    "FINDING_UNKNOWN_STANDARD",
    "KNOWN_LAYERS",
    "LEGACY_RAILS_FILENAME",
    "LocalArticle",
    "NON_FATAL_FINDING_CLASSES",
    "Purpose",
    "RAILS_SCHEMA_VERSION",
    "RailsBlock",
    "STANDARDS_DIR",
    "UNCHECKABLE_NOTHING_DECLARED",
    "UNCHECKABLE_REGISTRY_UNAVAILABLE",
    "_as_float",
    "_as_int",
    "_as_mapping",
    "_as_str_tuple",
    "_parse_actors",
]


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
    """Parse *path* as a YAML mapping; ``None`` only when the file is absent.

    A present-but-unparseable declaration raises rather than returning
    ``None``. Returning ``None`` would make a broken charter indistinguishable
    from *no* charter, and the caretaker skips repos with no charter — so a
    corrupt governing declaration would read as "ungoverned", silently.
    """
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        msg = f"{path.name} is not valid YAML: {exc}"
        raise CharterError(msg) from exc
    if not isinstance(raw, dict):
        msg = (
            f"{path.name} must be a YAML mapping, got {type(raw).__name__}. A "
            "declaration that cannot be read must not be mistaken for the "
            "absence of one."
        )
        raise CharterError(msg)
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
    scripts = _as_str_tuple(
        "rails.domain_gate_scripts", snapshot.get("domain_gate_scripts")
    )
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
