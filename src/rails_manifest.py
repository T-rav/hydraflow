"""Rails manifest (``rails.yaml``) schema + drift comparison (#10936, ADR-0121).

A **rails manifest** is a small declarative record written into each
stamped/onboarded HydraFlow-format repo. It captures *which* template layers
the repo carries — universal kernel / language pack / domain rails — and at
what template version, its coverage floor, and its domain gate scripts. This
turns template conformance into durable **data** instead of something only
checked ad-hoc when someone remembers to run ``make audit`` (the gap that let
harvestd silently drift to 4-of-6 kernel standards, 2026-07).

Two consumers share this module:

* :class:`~rails_drift_caretaker_loop.RailsDriftCaretakerLoop` reads a repo's
  manifest, observes its live state, and files deduped drift issues.
* the onboarding / format-upgrade path writes the manifest (:func:`write_manifest`,
  :func:`manifest_from_snapshot`) so every managed repo carries one.

Forward-compat (Book-3 operator-agent pack): unknown/future layer names are
**tolerated and reported, never rejected**. The schema does not enumerate a
closed set of legal layer names — an undeclared *extra* rail in the repo is
fine, and a declared layer this audit version doesn't recognise is surfaced as
a non-fatal ``unknown-layer`` finding rather than an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

RAILS_MANIFEST_FILENAME = "rails.yaml"
RAILS_MANIFEST_SCHEMA_VERSION = 1

# Layer names this audit version knows how to verify. The manifest TOLERATES
# any other name (forward-compat) — see ``RailsManifest.unknown_layers``.
KNOWN_LAYERS: frozenset[str] = frozenset({"universal", "language_pack", "domain_rails"})

# Finding classes. One drift issue is filed per (repo, finding_class), deduped
# like the adr-drift / branch-protection-drift loops.
FINDING_MISSING_LAYER = "missing-layer"
FINDING_COVERAGE_FLOOR = "coverage-floor"
FINDING_MISSING_GATE_SCRIPT = "missing-gate-script"
# ``unknown-layer`` is REPORTED but NOT fatal: it never makes a report "dirty"
# and never files an issue on its own (a future/unknown layer name is allowed).
FINDING_UNKNOWN_LAYER = "unknown-layer"


@dataclass(frozen=True)
class RailsManifest:
    """The declared template surface of one managed repo (``rails.yaml``)."""

    template_version: str
    layers: tuple[str, ...] = ()
    coverage_floor: float = 0.0
    domain_gate_scripts: tuple[str, ...] = ()
    schema_version: int = RAILS_MANIFEST_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RailsManifest:
        """Build a manifest from a parsed ``rails.yaml`` mapping.

        Tolerant by construction: missing keys take defaults and unknown
        *layer names* survive round-trip (they are not filtered here — the
        drift computation reports them as non-fatal).
        """
        layers = data.get("layers") or []
        scripts = data.get("domain_gate_scripts") or []
        return cls(
            template_version=str(data.get("template_version", "")),
            layers=tuple(str(v) for v in layers),
            coverage_floor=float(data.get("coverage_floor", 0.0) or 0.0),
            domain_gate_scripts=tuple(str(v) for v in scripts),
            schema_version=int(
                data.get("schema_version", RAILS_MANIFEST_SCHEMA_VERSION)
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


@dataclass(frozen=True)
class ObservedRails:
    """What a repo actually carries right now (gathered live).

    ``coverage`` is ``None`` when it cannot be determined — in that case the
    coverage floor is *not* evaluated (fail-open: we never file drift on a
    measurement we could not take).
    """

    present_layers: frozenset[str] = frozenset()
    coverage: float | None = None
    present_gate_scripts: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RailsFinding:
    """One drift finding. ``check_id`` is the specific failing check (e.g.
    ``missing-layer:language_pack``); ``finding_class`` is the coarse bucket
    the issue is filed and deduped under (e.g. ``missing-layer``)."""

    check_id: str
    finding_class: str
    detail: str


@dataclass(frozen=True)
class RailsDriftReport:
    """Result of auditing one repo's live state against its manifest."""

    repo: str
    findings: tuple[RailsFinding, ...] = ()
    # ``None`` means the repo has no ``rails.yaml`` — it is unmanaged by the
    # rails contract, distinct from "managed and clean" (empty findings).
    has_manifest: bool = True

    @property
    def clean(self) -> bool:
        """True when there is no *fatal* drift. Unknown-layer findings are
        reported but do not count as drift (forward-compat, #10936)."""
        return not any(f.finding_class != FINDING_UNKNOWN_LAYER for f in self.findings)

    @property
    def fatal_findings(self) -> tuple[RailsFinding, ...]:
        return tuple(
            f for f in self.findings if f.finding_class != FINDING_UNKNOWN_LAYER
        )

    @property
    def tolerated_unknown_layers(self) -> tuple[str, ...]:
        return tuple(
            f.check_id.split(":", 1)[1]
            for f in self.findings
            if f.finding_class == FINDING_UNKNOWN_LAYER and ":" in f.check_id
        )


def compute_rails_drift(
    manifest: RailsManifest, observed: ObservedRails, *, repo: str
) -> RailsDriftReport:
    """Compare a repo's declared manifest against its observed live state.

    Rules (per #10936):

    * a **missing declared layer** (declared in the manifest but absent from
      the repo) is drift — but only for layers this version can verify;
    * an **undeclared extra rail** (present in the repo, not in the manifest)
      is fine and never reported;
    * an **unknown/future layer name** in the manifest is tolerated and
      reported as a non-fatal ``unknown-layer`` finding;
    * the **coverage floor** is drift when observed coverage is below it (only
      evaluated when coverage is known);
    * a **declared domain gate script** absent from the repo is drift.
    """
    findings: list[RailsFinding] = []

    # Unknown/future layer names: report, never fail.
    for layer in manifest.unknown_layers:
        findings.append(
            RailsFinding(
                check_id=f"{FINDING_UNKNOWN_LAYER}:{layer}",
                finding_class=FINDING_UNKNOWN_LAYER,
                detail=(
                    f"manifest declares layer '{layer}', which this audit "
                    "version does not recognise — tolerated (forward-compat)"
                ),
            )
        )

    # Missing declared layers (only the known, verifiable ones).
    for layer in manifest.layers:
        if layer in KNOWN_LAYERS and layer not in observed.present_layers:
            findings.append(
                RailsFinding(
                    check_id=f"{FINDING_MISSING_LAYER}:{layer}",
                    finding_class=FINDING_MISSING_LAYER,
                    detail=(
                        f"manifest declares the '{layer}' layer but the repo "
                        "no longer carries it"
                    ),
                )
            )

    # Coverage floor (only when observed coverage is known).
    if (
        manifest.coverage_floor > 0
        and observed.coverage is not None
        and observed.coverage < manifest.coverage_floor
    ):
        findings.append(
            RailsFinding(
                check_id=f"{FINDING_COVERAGE_FLOOR}:{manifest.coverage_floor:g}",
                finding_class=FINDING_COVERAGE_FLOOR,
                detail=(
                    f"coverage {observed.coverage:g}% is below the declared "
                    f"floor of {manifest.coverage_floor:g}%"
                ),
            )
        )

    # Missing domain gate scripts.
    for script in manifest.domain_gate_scripts:
        if script not in observed.present_gate_scripts:
            findings.append(
                RailsFinding(
                    check_id=f"{FINDING_MISSING_GATE_SCRIPT}:{script}",
                    finding_class=FINDING_MISSING_GATE_SCRIPT,
                    detail=(
                        f"manifest declares domain gate script '{script}' but "
                        "it is absent from the repo"
                    ),
                )
            )

    return RailsDriftReport(repo=repo, findings=tuple(findings))


# --------------------------------------------------------------------------- #
# Load / render / write                                                        #
# --------------------------------------------------------------------------- #


def load_manifest(path: Path) -> RailsManifest | None:
    """Load a ``rails.yaml`` manifest, or ``None`` if the file is absent.

    Returns ``None`` on a missing file (the repo is unmanaged by the rails
    contract). A present-but-empty file yields a default manifest.
    """
    if not path.exists():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return None
    return RailsManifest.from_dict(raw)


_MANIFEST_HEADER = (
    "# HydraFlow rails manifest (rails.yaml) — generated per ADR-0121 (#10936).\n"
    "# Declares which template layers this repo carries so the rails-drift\n"
    "# caretaker loop can audit conformance as data. Edit deliberately: the\n"
    "# loop files a drift issue when live state diverges from what is declared\n"
    "# here. Unknown/future layer names are tolerated (forward-compat).\n"
)


def render_manifest(manifest: RailsManifest) -> str:
    """Render a manifest to YAML text (with an explanatory header comment)."""
    body = yaml.safe_dump(manifest.to_dict(), sort_keys=False, default_flow_style=False)
    return _MANIFEST_HEADER + body


def write_manifest(repo_root: Path, manifest: RailsManifest) -> Path:
    """Write ``<repo_root>/rails.yaml`` and return its path."""
    path = repo_root / RAILS_MANIFEST_FILENAME
    path.write_text(render_manifest(manifest), encoding="utf-8")
    return path


def manifest_from_snapshot(snapshot: dict[str, Any]) -> RailsManifest:
    """Build a manifest from an onboarding standards snapshot.

    The onboarding standards snapshot (``.hydraflow/standards-snapshot.json``)
    already carries ``coverage_floor`` and ``tech_stack``; this maps it onto
    the rails manifest so stamping/onboarding writes both from one source.
    Every stamped repo carries the universal kernel and a language pack; a
    domain-rails layer is declared when the snapshot names one (via
    ``domain`` / ``domain_rails``).
    """
    layers: list[str] = ["universal", "language_pack"]
    if snapshot.get("domain_rails") or snapshot.get("domain"):
        layers.append("domain_rails")
    scripts = snapshot.get("domain_gate_scripts") or []
    return RailsManifest(
        template_version=str(snapshot.get("template_version", "1")),
        layers=tuple(layers),
        coverage_floor=float(snapshot.get("coverage_floor", 0.0) or 0.0),
        domain_gate_scripts=tuple(str(s) for s in scripts),
    )
