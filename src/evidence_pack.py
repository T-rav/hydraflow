"""Release evidence-pack compiler (CH-4, issue #9732).

Every RC promotion already generates the raw compliance material — CH-2
approval records, CH-1 chained audit streams, CH-5 Req-ID trailers, CH-7
reproducibility manifests, principles-audit results, kill-switch state —
but nothing bundles it. In validation-heavy settings (FDA/IEC 62304 CSV,
SOC2 evidence collection) the binder IS the deliverable, so this module
compiles one per promoted RC:

``<repo_data_root>/evidence/rc-YYYY-MM-DD-HHMM/``
    * ``manifest.json`` — RC SHA range, included PRs with their approval
      records and authors, Req-ID trailers, the RC PR's own repro manifest,
      and the ``gaps`` list.
    * ``audit.json`` — latest principles-audit totals plus a CH-1 chain
      verification result for every registered audit stream.
    * ``ops.json`` — kill-switch/config snapshot (CH-7's
      :data:`~repro_manifest.CONFIG_SNAPSHOT_ALLOWLIST`, imported — never a
      second allowlist) and per-loop enabled states when the caller has them.
    * ``index.md`` — a one-page human-readable summary with a NAMED GAPS
      section.

Named gaps, never silence
-------------------------
Any datum the compiler cannot find — a missing approval record for an
included PR, an unverifiable chain, an absent audit report, a PR body
without a manifest — is recorded in ``manifest.json``'s ``gaps`` list AND
rendered in ``index.md``. An empty-input pack is all-gaps, not an error:
the pack is a report-only ratchet (tightening is a later decision), so the
compiler degrades per-datum instead of failing.

Tamper evidence
---------------
One ``record_type="evidence_pack"`` summary record (pack path, RC PR
number, SHA range, gap count, per-file sha256 digests) is appended to the
CH-1 ``evidence_packs`` stream registered in
:func:`audit_chain.audit_streams`, so ``RunsGCLoop``'s existing
verify/retention tick covers it and out-of-band edits to a written pack are
detectable against the chained digests.

The gh boundary reuses ``approval_records.py``'s precedent: raw ``gh`` via
:func:`subprocess_util.run_subprocess` at the 30s gh tier — no new PRPort
methods for one read shape. ``AuthenticationError``/``CreditExhaustedError``
always propagate (dark-factory §2.2); every other per-datum failure becomes
a named gap.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import subprocess_util
import traceability
from approval_records import RECORD_TYPE_APPROVAL
from audit_chain import AuditChain, audit_streams
from repro_manifest import CONFIG_SNAPSHOT_ALLOWLIST, extract_manifest_block

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.evidence_pack")

#: Bump when the pack layout / record shape changes incompatibly.
EVIDENCE_PACK_SCHEMA = "hydraflow.evidence-pack/v1"

#: ``record_type`` discriminator on the chained ``evidence_packs`` stream.
RECORD_TYPE_EVIDENCE_PACK = "evidence_pack"

#: The files every pack contains, in index-rendering order.
PACK_FILE_NAMES = ("manifest.json", "audit.json", "ops.json", "index.md")

# gh timeout tier (see docs/wiki: subprocess timeout tiers — gh=30s).
_GH_TIMEOUT_SECONDS = 30.0

_RC_PR_JSON_FIELDS = (
    "number,title,body,author,baseRefName,headRefName,headRefOid,"
    "mergeCommit,mergedAt,url,commits"
)
_INCLUDED_PR_JSON_FIELDS = "number,title,body,author"

# Squash-merge headline convention: "<type>(<scope>): <title> (#N)". The
# LAST parenthesised ref on the headline is the merged PR's own number.
_PR_REF_RE = re.compile(r"\(#(\d+)\)")

# -- named gap kinds ----------------------------------------------------------
GAP_RC_PR_DETAIL = "rc_pr_detail_unavailable"
GAP_NO_INCLUDED_PRS = "no_included_prs_detected"
GAP_INCLUDED_PR_DETAIL = "included_pr_detail_unavailable"
GAP_APPROVAL_STREAM = "approval_stream_missing"
GAP_APPROVAL_RECORD = "approval_record_missing"
GAP_REPRO_MANIFEST = "repro_manifest_missing"
GAP_AUDIT_REPORT = "audit_report_missing"
GAP_AUDIT_REPORT_UNREADABLE = "audit_report_unreadable"
GAP_AUDIT_CHAIN_BREAK = "audit_chain_break"
GAP_LOOP_STATES = "loop_states_unavailable"

#: Failure shapes converted into named gaps at each datum boundary.
#: ``AuthenticationError``/``CreditExhaustedError`` are RuntimeError
#: subclasses and MUST be re-raised before this tuple is consulted.
_GAP_EXCEPTIONS = (RuntimeError, OSError, TimeoutError, ValueError, KeyError)


@dataclass(frozen=True)
class EvidencePackResult:
    """Outcome of one compiled release evidence pack."""

    pack_dir: Path
    rc_branch: str
    pr_number: int
    gaps: tuple[dict[str, str], ...]
    file_digests: dict[str, str]
    chain_record: dict[str, Any]

    @property
    def gap_count(self) -> int:
        return len(self.gaps)


class _GapList:
    """Accumulates named gaps; the guarantee is gaps, never silence."""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, kind: str, detail: str) -> None:
        self.items.append({"kind": kind, "detail": detail})


async def compile_evidence_pack(
    config: HydraFlowConfig,
    rc_branch: str,
    pr_number: int,
    *,
    disabled_workers: Collection[str] | None = None,
) -> EvidencePackResult:
    """Compile the evidence pack for one promoted RC and chain its summary.

    *disabled_workers* is the per-loop kill-switch state when the caller has
    it cheaply (``StateTracker.get_disabled_workers()``); ``None`` records a
    named gap instead of guessing.

    Per-datum failures degrade to named gaps; only auth/credit signals and
    genuine write failures on the pack itself propagate.
    """
    gaps = _GapList()

    detail = await _fetch_rc_detail(config, pr_number, gaps)
    sha_range = _sha_range(config, rc_branch, detail)
    included_numbers = _included_pr_numbers(detail, pr_number, gaps)
    approvals = _approvals_by_pr_number(config, gaps)
    included_prs = [
        await _build_included_entry(config, number, approvals, gaps)
        for number in included_numbers
    ]
    repro_manifest = _rc_repro_manifest(detail, gaps)
    audit_data = _build_audit(config, gaps)
    ops_data = _build_ops(config, disabled_workers, gaps)

    manifest = {
        "schema": EVIDENCE_PACK_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "repo": config.repo,
        "rc_branch": rc_branch,
        "pr_number": pr_number,
        "rc_pr_url": (detail or {}).get("url") or "",
        "merged_at": (detail or {}).get("mergedAt") or "",
        "sha_range": sha_range,
        "included_prs": included_prs,
        "req_ids": sorted({e["req_id"] for e in included_prs if e.get("req_id")}),
        "repro_manifest": repro_manifest,
        "gaps": gaps.items,
    }

    pack_dir = config.evidence_dir / rc_branch.replace("/", "-")
    pack_dir.mkdir(parents=True, exist_ok=True)
    _write_json(pack_dir / "manifest.json", manifest)
    _write_json(pack_dir / "audit.json", audit_data)
    _write_json(pack_dir / "ops.json", ops_data)
    (pack_dir / "index.md").write_text(
        _render_index(manifest, audit_data, ops_data), encoding="utf-8"
    )

    file_digests = {name: _digest(pack_dir / name) for name in PACK_FILE_NAMES}
    chain_record = AuditChain(config.evidence_packs_path).append(
        {
            "schema": EVIDENCE_PACK_SCHEMA,
            "record_type": RECORD_TYPE_EVIDENCE_PACK,
            "repo": config.repo,
            "rc_branch": rc_branch,
            "pr_number": pr_number,
            "pack_path": str(pack_dir),
            "sha_range": sha_range,
            "gap_count": len(gaps.items),
            "files": file_digests,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
    logger.info(
        "Compiled evidence pack for %s (PR #%d) at %s: %d gap(s)",
        rc_branch,
        pr_number,
        pack_dir,
        len(gaps.items),
    )
    return EvidencePackResult(
        pack_dir=pack_dir,
        rc_branch=rc_branch,
        pr_number=pr_number,
        gaps=tuple(gaps.items),
        file_digests=file_digests,
        chain_record=chain_record,
    )


# -- gh boundary (approval_records.py precedent: raw gh, 30s tier) ------------


async def _gh_pr_view(
    config: HydraFlowConfig, pr_number: int, fields: str
) -> dict[str, Any]:
    raw = await subprocess_util.run_subprocess(
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--repo",
        config.repo,
        "--json",
        fields,
        timeout=_GH_TIMEOUT_SECONDS,
    )
    detail = json.loads(raw)
    if not isinstance(detail, dict):
        raise ValueError(f"gh pr view #{pr_number} returned {detail!r}")
    return detail


async def _fetch_rc_detail(
    config: HydraFlowConfig, pr_number: int, gaps: _GapList
) -> dict[str, Any] | None:
    try:
        return await _gh_pr_view(config, pr_number, _RC_PR_JSON_FIELDS)
    except (subprocess_util.AuthenticationError, subprocess_util.CreditExhaustedError):
        raise
    except _GAP_EXCEPTIONS as exc:
        gaps.add(
            GAP_RC_PR_DETAIL,
            f"could not fetch RC PR #{pr_number} detail from gh: {exc}",
        )
        return None


# -- manifest.json ------------------------------------------------------------


def _sha_range(
    config: HydraFlowConfig, rc_branch: str, detail: dict[str, Any] | None
) -> dict[str, str]:
    """The promoted range: head_sha is the RC tip (the staging snapshot plus
    the synthetic CI-trigger commit); the merge commit's other parent is the
    pre-promotion main tip, so ``base_ref..head_sha`` is fully derivable."""
    detail = detail or {}
    merge_commit = detail.get("mergeCommit")
    return {
        "base_ref": detail.get("baseRefName") or config.main_branch,
        "head_ref": detail.get("headRefName") or rc_branch,
        "head_sha": detail.get("headRefOid") or "",
        "merge_commit_sha": (
            merge_commit.get("oid", "") if isinstance(merge_commit, dict) else ""
        ),
    }


def _included_pr_numbers(
    detail: dict[str, Any] | None, rc_pr_number: int, gaps: _GapList
) -> list[int]:
    """PR numbers merged into this RC, read from squash-commit headlines.

    The RC PR's own number is excluded (the synthetic CI-trigger commit
    references it). No headline refs on a fetched commit list is itself a
    named gap — an RC of PRs the compiler cannot attribute is a hole in the
    traceability story, not a normal shape.
    """
    if detail is None:
        return []
    numbers: set[int] = set()
    commits = detail.get("commits")
    for commit in commits if isinstance(commits, list) else []:
        if not isinstance(commit, dict):
            continue
        refs = _PR_REF_RE.findall(commit.get("messageHeadline") or "")
        if refs:
            numbers.add(int(refs[-1]))
    numbers.discard(rc_pr_number)
    if not numbers:
        gaps.add(
            GAP_NO_INCLUDED_PRS,
            f"no included-PR refs found in RC PR #{rc_pr_number} commit headlines",
        )
    return sorted(numbers)


def _approvals_by_pr_number(
    config: HydraFlowConfig, gaps: _GapList
) -> dict[int, dict[str, Any]]:
    """Latest CH-2 approval record per PR number, read from the local stream."""
    path = config.approval_records_path
    if not path.exists():
        gaps.add(
            GAP_APPROVAL_STREAM,
            f"approval-record stream not found at {path}",
        )
        return {}
    records: dict[int, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            # A corrupt line is a chain break — reported by the chain
            # verification section; approval lookup keeps working from the
            # parseable records.
            continue
        if not isinstance(record, dict):
            continue
        if record.get("record_type", RECORD_TYPE_APPROVAL) != RECORD_TYPE_APPROVAL:
            continue
        number = record.get("pr_number")
        if isinstance(number, int):
            records[number] = record
    return records


async def _build_included_entry(
    config: HydraFlowConfig,
    number: int,
    approvals: dict[int, dict[str, Any]],
    gaps: _GapList,
) -> dict[str, Any]:
    approval_record = approvals.get(number)
    approval = None
    if approval_record is not None:
        approval = {
            "role": approval_record.get("role") or "",
            "role_separated": bool(approval_record.get("role_separated")),
            "approver": approval_record.get("approver_identity") or "",
            "author": approval_record.get("author_identity") or "",
            "merged_at": approval_record.get("merged_at") or "",
            "record_hash": approval_record.get("record_hash") or "",
        }
    else:
        gaps.add(
            GAP_APPROVAL_RECORD,
            f"no CH-2 approval record for included PR #{number}",
        )

    title = ""
    authors: list[str] = []
    req_id: str | None = None
    try:
        detail = await _gh_pr_view(config, number, _INCLUDED_PR_JSON_FIELDS)
    except (subprocess_util.AuthenticationError, subprocess_util.CreditExhaustedError):
        raise
    except _GAP_EXCEPTIONS as exc:
        gaps.add(
            GAP_INCLUDED_PR_DETAIL,
            f"could not fetch included PR #{number} detail from gh: {exc}",
        )
        if approval is not None and approval["author"]:
            authors = [approval["author"]]
    else:
        title = detail.get("title") or ""
        author = detail.get("author")
        login = author.get("login") if isinstance(author, dict) else None
        authors = [login] if isinstance(login, str) and login else []
        req_id = traceability.extract_req_id(labels=[], body=detail.get("body") or "")
    return {
        "number": number,
        "title": title,
        "authors": authors,
        "req_id": req_id,
        "approval": approval,
    }


def _rc_repro_manifest(
    detail: dict[str, Any] | None, gaps: _GapList
) -> dict[str, Any] | None:
    body = (detail or {}).get("body") or ""
    manifest = extract_manifest_block(body)
    if manifest is None:
        gaps.add(
            GAP_REPRO_MANIFEST,
            "RC PR body carries no parseable CH-7 reproducibility manifest",
        )
    return manifest


# -- audit.json ---------------------------------------------------------------


def _build_audit(config: HydraFlowConfig, gaps: _GapList) -> dict[str, Any]:
    report_path = config.repo_root / ".hydraflow" / "audit-report.json"
    principles: dict[str, Any] | None = None
    if not report_path.exists():
        gaps.add(
            GAP_AUDIT_REPORT,
            f"principles-audit report not found at {report_path}",
        )
    else:
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("audit report is not a JSON object")
            principles = {
                "path": str(report_path),
                "version": payload.get("version"),
                "summary": payload.get("summary"),
            }
        except (OSError, ValueError) as exc:
            gaps.add(
                GAP_AUDIT_REPORT_UNREADABLE,
                f"principles-audit report at {report_path} is unreadable: {exc}",
            )

    chain_verification: list[dict[str, Any]] = []
    for spec in audit_streams(config):
        result = AuditChain(spec.path).verify()
        chain_verification.append(
            {
                "stream": spec.name,
                "path": str(spec.path),
                "ok": result.ok,
                "total_records": result.total_records,
                "chained_records": result.chained_records,
                "breaks": [f"record {b.record_no}: {b.reason}" for b in result.breaks],
            }
        )
        if not result.ok:
            gaps.add(
                GAP_AUDIT_CHAIN_BREAK,
                f"audit stream {spec.name!r} failed chain verification "
                f"({len(result.breaks)} break(s))",
            )
    return {
        "schema": EVIDENCE_PACK_SCHEMA,
        "principles_audit": principles,
        "chain_verification": chain_verification,
    }


# -- ops.json -----------------------------------------------------------------


def _build_ops(
    config: HydraFlowConfig,
    disabled_workers: Collection[str] | None,
    gaps: _GapList,
) -> dict[str, Any]:
    loop_states: dict[str, Any] | None = None
    if disabled_workers is None:
        gaps.add(
            GAP_LOOP_STATES,
            "per-loop enabled states unavailable to the compiler "
            "(no StateTracker at the call site)",
        )
    else:
        loop_states = {"disabled_workers": sorted(disabled_workers)}
    return {
        "schema": EVIDENCE_PACK_SCHEMA,
        # CH-7's allowlist, imported — never fork a second one.
        "config_snapshot": {
            name: getattr(config, name) for name in CONFIG_SNAPSHOT_ALLOWLIST
        },
        "loop_states": loop_states,
    }


# -- index.md -----------------------------------------------------------------


def _render_index(
    manifest: dict[str, Any],
    audit_data: dict[str, Any],
    ops_data: dict[str, Any],
) -> str:
    sha = manifest["sha_range"]
    lines = [
        f"# Evidence Pack — {manifest['rc_branch']} (PR #{manifest['pr_number']})",
        "",
        f"Generated: {manifest['generated_at']} · Repo: {manifest['repo']} · "
        f"Schema: {manifest['schema']}",
        "",
        "## RC",
        "",
        f"- Range: `{sha['base_ref']}` ← `{sha['head_ref']}` "
        f"@ `{sha['head_sha'] or '?'}`",
        f"- Merge commit: `{sha['merge_commit_sha'] or '?'}` · "
        f"Merged at: {manifest['merged_at'] or '?'}",
        f"- Reproducibility manifest: "
        f"{'present' if manifest['repro_manifest'] else 'MISSING (see gaps)'}",
        "",
        f"## Included PRs ({len(manifest['included_prs'])})",
        "",
        "| PR | Title | Authors | Role | Role-separated | Approver | Req-ID |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in manifest["included_prs"]:
        approval = entry["approval"] or {}
        lines.append(
            f"| #{entry['number']} "
            f"| {entry['title'] or '?'} "
            f"| {', '.join(entry['authors']) or '?'} "
            f"| {approval.get('role') or 'NO RECORD'} "
            f"| {approval.get('role_separated', '—')} "
            f"| {approval.get('approver') or '—'} "
            f"| {entry['req_id'] or '—'} |"
        )
    principles = audit_data["principles_audit"]
    summary = (principles or {}).get("summary") or {}
    lines += [
        "",
        "## Audit",
        "",
        (
            "- Principles audit: "
            + ", ".join(f"{k.upper()} {v}" for k, v in summary.items())
            if principles
            else "- Principles audit: MISSING (see gaps)"
        ),
        "- Chain verification: "
        + ", ".join(
            f"{entry['stream']}={'ok' if entry['ok'] else 'BREAK'}"
            for entry in audit_data["chain_verification"]
        ),
        "",
        "## Ops",
        "",
        "- Config snapshot: "
        + ", ".join(
            f"{name}={value}"
            for name, value in sorted(ops_data["config_snapshot"].items())
        ),
        (
            "- Disabled loops: "
            + (", ".join(ops_data["loop_states"]["disabled_workers"]) or "none")
            if ops_data["loop_states"] is not None
            else "- Disabled loops: UNKNOWN (see gaps)"
        ),
        "",
        "## Named Gaps",
        "",
    ]
    if manifest["gaps"]:
        lines += [f"- **{g['kind']}** — {g['detail']}" for g in manifest["gaps"]]
    else:
        lines.append("None — all evidence located.")
    lines.append("")
    return "\n".join(lines)


# -- file helpers -------------------------------------------------------------


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
