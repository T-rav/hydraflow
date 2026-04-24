"""CorpusLearningLoop — grow the adversarial corpus from escape signals (§4.1 v2).

Phase 2 Tasks 11–14 are wired in:

- **Task 11** (reader): the loop queries
  ``PRManager.list_issues_by_label`` for open issues tagged with the
  configured escape label (default :data:`DEFAULT_ESCAPE_LABEL`),
  filters to the last :data:`DEFAULT_LOOKBACK_DAYS` days, and
  materializes each row into an :class:`EscapeSignal` dataclass.
- **Task 12** (synthesis): :meth:`CorpusLearningLoop._synthesize_case`
  turns an :class:`EscapeSignal` into a :class:`SynthesizedCase` by
  parsing a structured escape-issue body convention (see module
  docstring on :class:`SynthesizedCase` for the expected template).
  Malformed or minimal signals surface as ``None`` so the loop skips
  them instead of crashing.
- **Task 13** (self-validation): :meth:`CorpusLearningLoop._validate_case`
  runs three gates against a :class:`SynthesizedCase`:

    a. *harness accepts it* — the before/after pair produces a non-empty
       synthetic diff (matches the precondition in
       :func:`tests.trust.adversarial.test_adversarial_corpus.test_case`).
    b. *expected catcher trips* — feeding the deterministic fixture
       transcript for the named catcher into that skill's
       ``result_parser`` returns ``passed=False`` *and* the keyword
       appears in the summary (same contract the harness asserts via
       ``_read_keyword``).
    c. *unambiguous* — no *other* registered skill's ``result_parser``
       returns ``passed=False`` against the same transcript. A case
       that trips more than one catcher is ambiguous and must be
       rejected before it rots the corpus.

- **Task 14** (wiring): :meth:`CorpusLearningLoop._do_work` ticks through
  the escape signals, synthesizes + validates each, and returns a
  status dict with ``escape_issues_seen``, ``cases_synthesized``, and
  ``cases_validated``. Filing the actual PR is Task 15's scope.

Kill-switch: :meth:`LoopDeps.enabled_cb` with ``worker_name="corpus_learning"``
— **no ``corpus_learning_enabled`` config field** (spec §12.2).
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import WorkCycleResult  # noqa: TCH001
from skill_registry import BUILTIN_SKILLS, AgentSkill

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.corpus_learning_loop")

#: Default GitHub label that marks an issue as a production escape
#: signal. Task 15 will surface this as a
#: ``corpus_learning_signal_label`` config field; until then callers and
#: tests can override via the ``label`` parameter on
#: :meth:`CorpusLearningLoop._list_escape_signals`.
DEFAULT_ESCAPE_LABEL = "skill-escape"

#: Default recency window (days) for escape signals. Issues whose
#: ``updated_at`` is older than this are dropped from the reader so the
#: synthesizer focuses on live regressions, not archived noise.
DEFAULT_LOOKBACK_DAYS = 30

#: Catchers the synthesizer is allowed to target. Mirrors the
#: post-implementation skills the harness fixture builder knows how to
#: emit a deterministic RETRY marker for. ``arch-compliance`` is
#: intentionally excluded until we add a marker mapping for it.
_SYNTHESIZABLE_CATCHERS: frozenset[str] = frozenset(
    {"diff-sanity", "scope-check", "test-adequacy", "plan-compliance"}
)

#: Marker token each skill emits in its ``<SKILL>_RESULT: RETRY``
#: line. Used by :meth:`CorpusLearningLoop._fixture_transcript_for` to
#: build the deterministic gate-(b) fixture without a live LLM call.
_CATCHER_MARKERS: dict[str, str] = {
    "diff-sanity": "DIFF_SANITY_RESULT",
    "scope-check": "SCOPE_CHECK_RESULT",
    "test-adequacy": "TEST_ADEQUACY_RESULT",
    "plan-compliance": "PLAN_COMPLIANCE_RESULT",
}

#: Upper bound on the derived case-directory slug. Anything longer is
#: ugly on disk, harder to grep, and runs into filesystem name limits
#: when combined with the cases-root prefix.
_SLUG_MAX_LEN = 64


@dataclass(frozen=True, slots=True)
class EscapeSignal:
    """A parsed escape-signal row from a ``skill-escape``-labeled issue.

    Intentionally narrow: carries just the fields Task 12's synthesizer
    needs (``issue_number``, ``title``, ``body``) plus the provenance
    bits (``updated_at``, ``label``) the loop uses for filtering and
    telemetry. Reading new GitHub fields means extending this shape —
    never stashing raw ``dict`` rows downstream.
    """

    issue_number: int
    title: str
    body: str
    updated_at: str
    label: str


@dataclass(frozen=True, slots=True)
class SynthesizedCase:
    """An in-memory spec for a would-be ``cases/<slug>/`` directory.

    Produced by :meth:`CorpusLearningLoop._synthesize_case` from a
    parseable :class:`EscapeSignal`. The expected escape-issue body
    convention is::

        <free-form reproduction prose — becomes README.md body>

        Expected-Catcher: diff-sanity
        Keyword: <substring-that-must-appear-in-retry-summary>

        ```before:src/path/to/file.py
        <pre-diff contents>
        ```

        ```after:src/path/to/file.py
        <post-diff contents>
        ```

        (optional)
        ```plan
        <plan text — scope-check/plan-compliance only>
        ```

    Task 15 materializes the spec onto disk (under
    ``tests/trust/adversarial/cases/<slug>/``); Task 14 only validates
    it in memory.
    """

    issue_number: int
    slug: str
    expected_catcher: str
    keyword: str
    before_files: dict[str, str]
    after_files: dict[str, str]
    readme: str
    plan_text: str = ""


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Outcome of :meth:`CorpusLearningLoop._validate_case`.

    ``ok=True`` means all three gates passed. On failure, ``failing_gate``
    identifies *which* gate rejected the case so telemetry (and Task 15's
    HITL escalation) can attribute the rejection precisely:

    - ``"harness_accepts"`` — gate (a) failed (e.g. empty diff).
    - ``"expected_catcher_trips"`` — gate (b) failed (named catcher did
      not report RETRY, or keyword absent from summary).
    - ``"unambiguous"`` — gate (c) failed (another catcher also tripped).
    """

    ok: bool
    reason: str = ""
    failing_gate: str = ""


class CorpusLearningLoop(BaseBackgroundLoop):
    """Grows ``tests/trust/adversarial/cases/`` from production escape signals.

    Current state (Tasks 11–14): reads escape signals, synthesizes
    in-memory case specs, and self-validates them with three gates.
    Filing the case as a PR (Task 15), five-checkpoint status wiring
    (Task 15), and the release-gating scenario (Task 18) are all
    downstream.

    On three self-validation failures for the same issue the loop will
    (Task 15) label it ``hitl-escalation`` + ``corpus-learning-stuck``
    and move on.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        prs: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="corpus_learning",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._prs = prs
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.corpus_learning_interval

    async def _list_escape_signals(
        self,
        *,
        label: str = DEFAULT_ESCAPE_LABEL,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> list[EscapeSignal]:
        """Return escape-signal issues labeled ``label`` from the last ``lookback_days``.

        Delegates to :meth:`PRManager.list_issues_by_label` (the
        canonical ``gh issue list`` wrapper) so CI-mocked and
        scenario-mocked runs stay on a single seam. Rows without a
        usable ``number`` or with an unparseable ``updated_at`` are
        dropped — better to skip a malformed row than poison Task 12's
        synthesizer with ``issue_number=0`` or a ``None`` timestamp.
        """
        raw_issues = await self._prs.list_issues_by_label(label)
        if not raw_issues:
            return []

        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        signals: list[EscapeSignal] = []
        for row in raw_issues:
            issue_number = row.get("number", 0)
            if not issue_number:
                continue
            updated_at_raw = row.get("updated_at", "") or ""
            parsed = _parse_iso_timestamp(updated_at_raw)
            if parsed is None:
                logger.debug(
                    "corpus-learning: dropping issue #%d with unparseable updated_at=%r",
                    issue_number,
                    updated_at_raw,
                )
                continue
            if parsed < cutoff:
                continue
            signals.append(
                EscapeSignal(
                    issue_number=issue_number,
                    title=row.get("title", "") or "",
                    body=row.get("body", "") or "",
                    updated_at=updated_at_raw,
                    label=label,
                )
            )
        return signals

    # ------------------------------------------------------------------
    # Task 12 — in-process synthesis
    # ------------------------------------------------------------------

    def _synthesize_case(self, signal: EscapeSignal) -> SynthesizedCase | None:
        """Parse an escape signal's body into a :class:`SynthesizedCase`.

        Returns ``None`` when the body lacks any required element
        (expected-catcher, keyword, before-block, after-block) or when
        the catcher names a skill the synthesizer does not support. The
        tick loop treats ``None`` as a "skip this signal" — never a
        crash.
        """
        body = signal.body or ""
        if not body.strip():
            return None

        catcher = _extract_header(body, "Expected-Catcher")
        if not catcher or catcher not in _SYNTHESIZABLE_CATCHERS:
            logger.debug(
                "corpus-learning: #%d — missing/unknown Expected-Catcher=%r",
                signal.issue_number,
                catcher,
            )
            return None

        keyword = _extract_header(body, "Keyword")
        if not keyword:
            logger.debug(
                "corpus-learning: #%d — missing Keyword header", signal.issue_number
            )
            return None

        before_files = _extract_fenced_files(body, "before")
        after_files = _extract_fenced_files(body, "after")
        if not before_files or not after_files:
            logger.debug(
                "corpus-learning: #%d — missing before/after fenced block(s)",
                signal.issue_number,
            )
            return None

        plan_blocks = _extract_fenced_blocks(body, "plan")
        plan_text = plan_blocks[0] if plan_blocks else ""

        # README prose = the body text *before* the first header or
        # fenced block. Keeps the human-written repro description
        # without the machine-parseable bits.
        readme = _extract_prose_preamble(body)

        slug = _slugify(signal.title)
        if not slug:
            # Fall back to a number-based slug so the case still has a
            # stable, filesystem-safe identifier even for titles that
            # slugify to empty (all punctuation, non-latin, etc.).
            slug = f"escape-{signal.issue_number}"

        return SynthesizedCase(
            issue_number=signal.issue_number,
            slug=slug,
            expected_catcher=catcher,
            keyword=keyword,
            before_files=before_files,
            after_files=after_files,
            readme=readme,
            plan_text=plan_text,
        )

    # ------------------------------------------------------------------
    # Task 13 — three-gate self-validation
    # ------------------------------------------------------------------

    def _validate_case(self, case: SynthesizedCase) -> ValidationResult:
        """Run the three self-validation gates against a :class:`SynthesizedCase`.

        Gates match the harness's preconditions + pass contract so that
        Task 15's disk materialization + harness run will agree with
        what this check already said in-memory.
        """
        # Gate (a): harness accepts it — same check as
        # test_adversarial_corpus.test_case's "before/after produced
        # empty diff" assertion.
        diff = _synthesize_diff(case.before_files, case.after_files)
        if not diff.strip():
            return ValidationResult(
                ok=False,
                reason="before/after produced empty diff",
                failing_gate="harness_accepts",
            )

        # Gate (b): expected catcher trips + keyword present in summary.
        expected_skill = _skill_by_name(case.expected_catcher)
        if expected_skill is None:
            # Should be unreachable — synthesis guards against unknown
            # catchers — but we keep the check so a registry rename
            # fails loud instead of silently auto-passing.
            return ValidationResult(
                ok=False,
                reason=f"unknown catcher {case.expected_catcher!r}",
                failing_gate="expected_catcher_trips",
            )

        transcript = self._fixture_transcript_for(case, case.expected_catcher)
        passed, summary, findings = expected_skill.result_parser(transcript)
        if passed:
            return ValidationResult(
                ok=False,
                reason=(
                    f"expected_catcher {case.expected_catcher!r} returned OK "
                    f"(summary={summary!r})"
                ),
                failing_gate="expected_catcher_trips",
            )
        haystack = (summary + "\n" + "\n".join(findings)).lower()
        if case.keyword.lower() not in haystack:
            return ValidationResult(
                ok=False,
                reason=(
                    f"expected_catcher {case.expected_catcher!r} returned RETRY "
                    f"but keyword {case.keyword!r} missing from summary/findings"
                ),
                failing_gate="expected_catcher_trips",
            )

        # Gate (c): no *other* catcher trips on the same transcript.
        also_tripped: list[str] = []
        for skill in BUILTIN_SKILLS:
            if skill.name == case.expected_catcher:
                continue
            other_passed, _other_summary, _other_findings = skill.result_parser(
                transcript
            )
            if not other_passed:
                also_tripped.append(skill.name)
        if also_tripped:
            return ValidationResult(
                ok=False,
                reason=(f"ambiguous — these catchers also tripped: {also_tripped!r}"),
                failing_gate="unambiguous",
            )

        return ValidationResult(ok=True)

    def _fixture_transcript_for(self, case: SynthesizedCase, skill_name: str) -> str:
        """Build the deterministic RETRY transcript for ``skill_name``.

        Mirrors the convention the corpus uses for
        ``expected_transcript.txt`` fixtures (see e.g.
        ``cases/renamed-symbol-callsite/expected_transcript.txt``). The
        keyword must appear in ``SUMMARY`` so the harness's keyword
        check is satisfied alongside the result parser.

        Exposed as a method (not a module function) so tests can
        monkey-patch it to simulate LLM-shaped misbehavior (missing
        keyword, cross-catcher marker collisions, etc.).
        """
        marker = _CATCHER_MARKERS[skill_name]
        return (
            f"{marker}: RETRY\n"
            f"SUMMARY: {case.keyword} — synthesized fixture\n"
            f"FINDINGS:\n- {case.slug} — synthesized from escape #{case.issue_number}\n"
        )

    # ------------------------------------------------------------------
    # Task 14 — tick
    # ------------------------------------------------------------------

    async def _do_work(self) -> WorkCycleResult:
        """Tick the loop.

        When the kill-switch is off, short-circuits with
        ``{"status": "disabled"}``. Otherwise fetches escape signals,
        synthesizes + validates each, and reports
        ``{escape_issues_seen, cases_synthesized, cases_validated}``.
        PR filing + dedup persistence land in Task 15.
        """
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        signals = await self._list_escape_signals()
        if signals:
            logger.info(
                "corpus-learning: %d escape signal(s) within %d-day window",
                len(signals),
                DEFAULT_LOOKBACK_DAYS,
            )

        cases_synthesized = 0
        cases_validated = 0
        validated_cases: list[SynthesizedCase] = []
        for signal in signals:
            case = self._synthesize_case(signal)
            if case is None:
                continue
            cases_synthesized += 1
            result = self._validate_case(case)
            if result.ok:
                cases_validated += 1
                validated_cases.append(case)
            else:
                logger.info(
                    "corpus-learning: #%d validation rejected at gate %s: %s",
                    signal.issue_number,
                    result.failing_gate,
                    result.reason,
                )

        # ``validated_cases`` is kept as a local for now; Task 15 will
        # feed it into the PR-opening path.
        _ = validated_cases

        return {
            "status": "noop",
            "escape_issues_seen": len(signals),
            "cases_synthesized": cases_synthesized,
            "cases_validated": cases_validated,
        }


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _parse_iso_timestamp(value: str) -> datetime | None:
    """Parse a GitHub-style ISO-8601 timestamp, returning ``None`` on failure.

    GitHub returns ``updated_at`` as e.g. ``"2026-04-22T14:05:00Z"``.
    :meth:`datetime.fromisoformat` accepts ``+00:00`` natively but only
    accepts the trailing ``Z`` since Python 3.11 — we normalize it
    explicitly so the intent is obvious and the parser never surprises
    a reader hunting a ``ValueError``.
    """
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


_HEADER_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _extract_header(body: str, header: str) -> str:
    """Return the value of a ``Header: value`` line, or ``""`` if absent.

    Matches case-insensitively at the start of a line. Leading/trailing
    whitespace is stripped. An empty value (``"Header:"``) counts as
    absent.
    """
    pattern = _HEADER_RE_CACHE.get(header)
    if pattern is None:
        pattern = re.compile(
            rf"^\s*{re.escape(header)}\s*:\s*(.*?)\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        _HEADER_RE_CACHE[header] = pattern
    match = pattern.search(body)
    if not match:
        return ""
    return match.group(1).strip()


# Fenced block: ```<tag>[:<suffix>]\n<body>\n```
# We use a non-greedy body match and anchor the closing fence at the
# start of a line so nested backticks inside the body don't confuse us.
_FENCED_RE = re.compile(
    r"```(?P<tag>[A-Za-z0-9_-]+)(?::(?P<suffix>[^\n`]+))?\n"
    r"(?P<body>.*?)\n```",
    re.DOTALL,
)


def _extract_fenced_files(body: str, tag: str) -> dict[str, str]:
    """Return ``{path: content}`` for every ``\\`\\`\\`<tag>:<path>`` block."""
    out: dict[str, str] = {}
    for match in _FENCED_RE.finditer(body):
        if match.group("tag").lower() != tag.lower():
            continue
        suffix = (match.group("suffix") or "").strip()
        if not suffix:
            continue
        # Ensure file content ends with a trailing newline so synthetic
        # diffs line up with how authored case files are written.
        content = match.group("body")
        if not content.endswith("\n"):
            content += "\n"
        out[suffix] = content
    return out


def _extract_fenced_blocks(body: str, tag: str) -> list[str]:
    """Return the bodies of every ``\\`\\`\\`<tag>`` block (no suffix required)."""
    out: list[str] = []
    for match in _FENCED_RE.finditer(body):
        if match.group("tag").lower() != tag.lower():
            continue
        out.append(match.group("body"))
    return out


def _extract_prose_preamble(body: str) -> str:
    """Return the body text before the first structured element.

    Structured elements are either a ``Header: ...`` line or a fenced
    code block. Empty preamble returns ``""``.
    """
    lines = body.splitlines()
    preamble: list[str] = []
    header_re = re.compile(r"^\s*[A-Za-z][A-Za-z0-9_-]*\s*:\s*\S")
    for line in lines:
        if line.lstrip().startswith("```"):
            break
        if header_re.match(line):
            break
        preamble.append(line)
    return "\n".join(preamble).strip()


_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    """Return a filesystem-safe kebab slug capped at :data:`_SLUG_MAX_LEN`."""
    lower = text.lower()
    collapsed = _SLUG_STRIP_RE.sub("-", lower).strip("-")
    if len(collapsed) > _SLUG_MAX_LEN:
        collapsed = collapsed[:_SLUG_MAX_LEN].rstrip("-")
    return collapsed


def _synthesize_diff(before: dict[str, str], after: dict[str, str]) -> str:
    """Build a unified diff from before/after file maps.

    Mirrors :func:`tests.trust.adversarial.test_adversarial_corpus._synthesize_diff`
    so validation's gate (a) is byte-equivalent to what the live harness
    would see after Task 15 materializes the case.
    """
    chunks: list[str] = []
    for rel in sorted(set(before) | set(after)):
        b = before.get(rel, "")
        a = after.get(rel, "")
        if b == a:
            continue
        diff = difflib.unified_diff(
            b.splitlines(keepends=True),
            a.splitlines(keepends=True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
        chunks.append(f"diff --git a/{rel} b/{rel}\n")
        chunks.extend(diff)
    return "".join(chunks)


def _skill_by_name(name: str) -> AgentSkill | None:
    for skill in BUILTIN_SKILLS:
        if skill.name == name:
            return skill
    return None
