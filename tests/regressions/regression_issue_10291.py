"""Regression guard for #10291 — triage mass-park from two chained bugs.

Observed live 2026-07-22: the entire open backlog sat `hydraflow-parked` because
EVERY issue failed triage with `triage verdict unparseable`. Two chained causes:

1. `triage_max_turns=3` was too low for #9127's verify-against-code triage — the
   agent exhausted the turn budget mid-verification and the CLI terminated with
   `error_max_turns` (exit 1, no verdict). Fixed by raising the default to 12.

2. Even once the agent emitted a complete, valid `{"ready": true, ...}` verdict,
   the parser REJECTED it: the enrichment (per #9127) QUOTES source code —
   nested ``` code fences and ``{}`` (e.g. an f-string ``f"[main {sha[:7]}]"``).
   The old non-greedy fence regex truncated at the first inner ```; the
   ``\\{[^{}]*"ready":[^{}]*\\}`` object regex truncated at the first inner `{`.
   Fixed with a brace-matched ``json.JSONDecoder().raw_decode`` strategy.

This guard pins bug 2 (the parser): a genuine verdict that quotes code MUST
parse. It is the load-bearing half — without it, even a turn-budget-fixed triage
re-parks every code-citing issue.
"""

from __future__ import annotations

from triage import TriageRunner


def test_verdict_quoting_code_parses_not_parked() -> None:
    # Faithful reduction of the real 2026-07-22 #10230 verdict: valid JSON whose
    # `enrichment` string contains BOTH a nested ``` fence AND `{}` (an f-string).
    verdict = (
        '{"ready": true, "reasons": [], "issue_type": "bug", '
        '"clarity_score": 9, "needs_discovery": false, '
        '"enrichment": "Confirmed the template '
        '`f\\"[main {sha[:7]}] {args[0]}\\\\n\\"` still emits:\\n'
        '```\\n[main abc1234] initial\\n```\\ndone.", '
        '"already_addressed": false, "claim_verified": true}'
    )
    transcript = f"```json\n{verdict}\n```"

    result = TriageRunner._parse_verdict(transcript, 10291)

    assert result is not None, (
        "a complete, valid verdict that quotes code must parse — not be rejected "
        "as 'unparseable' and parked (#10291)"
    )
    assert result.ready is True


def test_verdict_quoting_code_as_raw_stream_json_parses() -> None:
    # Same, delivered as RAW stream-json (a `result` frame with the fenced
    # verdict escaped inside) — the actual transport from `claude -p`.
    inner = (
        '```json\\n{\\"ready\\": true, \\"reasons\\": [], '
        '\\"enrichment\\": \\"template `f\\\\\\"[main {x[:7]}]\\\\\\"` and '
        '```\\\\n[main abc] init\\\\n``` here\\", '
        '\\"already_addressed\\": false}\\n```'
    )
    transcript = (
        '{"type":"system","subtype":"init","tools":["Bash"]}\n'
        f'{{"type":"result","subtype":"success","result":"{inner}"}}'
    )

    result = TriageRunner._parse_verdict(transcript, 10291)

    assert result is not None
    assert result.ready is True
