"""The raw ``gh`` CLI seam of ``FakeGitHub``.

Extracted VERBATIM from ``src/mockworld/fakes/fake_github.py``
(god-class decomposition, Refs #11547) as a mixin. ``FakeGitHub`` inherits it,
so every method here still resolves as an attribute of ``FakeGitHub`` and every
seam that drives the fake through a Port resolves to the same object as before.

The cluster boundary mirrors the real adapter's: this module is the fake's side
of ``pr_manager.PRManager._run_gh``, so the fake and the thing it doubles read alike.

One concern: the loops that build ``gh`` argv by hand instead of going through a
Port method. ``_run_gh`` models the shapes the fake understands, renders the
``gh issue view --json`` projection from in-memory state, and fails LOUD
(``FakeGitHubUnmodelledCommand``, #11372) on anything it does not model, so a
fidelity gap surfaces as a stack rather than a passing scenario. The real
``PRManager`` keeps ``_run_gh`` in its own class body; here it earns a module
because the dispatcher and its argv/projection helpers are one concern.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ._common import _QUIET_UNKNOWN_GH_SHAPES, FakeGitHubUnmodelledCommand

if TYPE_CHECKING:
    from typing import Any

    from ._common import FakeIssue, FakePR


class FakeGitHubCliMixin:
    """The raw ``gh`` CLI seam of ``FakeGitHub``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``FakeGitHub.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``FakeGitHub``'s MRO.
    # ------------------------------------------------------------------
    _issues: dict[int, FakeIssue]
    _prs: dict[int, FakePR]
    issue_view_unmodelled_fields: set[str]

    if TYPE_CHECKING:

        def _maybe_rate_limit(self) -> None: ...  # provided by _seeding

        async def close_issue(
            self, issue_number: int, *, reason: str | None = None
        ) -> bool: ...  # provided by _issues

        async def update_issue_body(
            self, issue_number: int, body: str
        ) -> None: ...  # provided by _issues

    def _modelled_api_payload(self, path: str) -> str | None:
        """Payloads for the ``gh api`` shapes real loops call (#11413).

        StaleIssueLoop's branch-GC makes both of these live — the sampled
        re-audit of #11372 falsified that PR's "no loop relied on the
        silent empty answer" claim by finding them. They are MODELLED, not
        allowlisted quiet: allowlisting would reintroduce exactly the blind
        spot fail-loud exists to remove. ``None`` means "not modelled here".
        """
        if "/git/matching-refs/heads/" in path:
            prefix = path.rsplit("/heads/", 1)[-1]
            return json.dumps(
                [
                    f"refs/heads/{pr.branch}"
                    for pr in self._prs.values()
                    if pr.branch and pr.branch.startswith(prefix)
                ]
            )
        if path.endswith("/commits"):
            # The loop reads only the newest commit's date/sha to age a
            # branch; an empty list is the honest "no commits recorded".
            return json.dumps([])
        return None

    @staticmethod
    def _option_value(args: list[str], option: str) -> str | None:
        """Return the value following *option*, or ``None`` when absent."""
        if option not in args:
            return None
        value_index = args.index(option) + 1
        return args[value_index] if value_index < len(args) else None

    @staticmethod
    def _option_values(args: list[str], option: str) -> list[str]:
        """Return every value supplied for a repeatable CLI *option*."""
        return [
            args[index + 1]
            for index, argument in enumerate(args[:-1])
            if argument == option
        ]

    def _issue_edit_body(self, args: list[str]) -> str | None:
        """Read the body-file value, falling back to an inline body."""
        path = self._option_value(args, "--body-file")
        if path is not None:
            try:
                return Path(path).read_text(encoding="utf-8")
            except OSError:
                pass
        return self._option_value(args, "--body")

    @classmethod
    def _issue_view_fields(cls, args: list[str]) -> tuple[list[str], list[str]]:
        """Return raw selectors and their ordered, de-duplicated field union."""
        selectors = cls._option_values(args, "--json")
        fields = [
            field.strip()
            for selector in selectors
            for field in selector.split(",")
            if field.strip()
        ]
        return selectors, list(dict.fromkeys(fields))

    @staticmethod
    def _issue_view_projections(issue: FakeIssue) -> dict[str, Any]:
        """Return every FakeIssue field modelled by the gh view boundary."""
        state_reason = issue.state_reason or (
            "COMPLETED" if issue.state == "closed" else ""
        )
        comments = [
            {
                "author": {"login": comment.login},
                "body": str(comment),
                "createdAt": comment.created_at,
            }
            for comment in issue.comments
        ]
        return {
            "number": issue.number,
            "labels": [{"name": label} for label in issue.labels],
            "body": issue.body,
            "title": issue.title,
            "state": issue.state.upper(),
            "stateReason": state_reason,
            "updatedAt": issue.updated_at,
            "comments": comments,
        }

    async def _handle_issue_edit(self, args: list[str]) -> None:
        """Model ``gh issue edit <n> --body-file <path>`` / ``--body <text>``.

        The production issuer is ``PRManager.update_issue_body``, which sends
        the body through a temp ``--body-file`` (``_run_with_body_file``)
        (#11419) — the fake reads the same file the real CLI would. Inline
        ``--body <text>`` (#11246) covers direct CLI callers so a
        passthrough-routed repair is observable in fake state too.
        Best-effort: extracts the issue number (first digit-only positional)
        and the body from either flag (``--body-file`` wins if both appear),
        then delegates to :meth:`update_issue_body` so the CLI route and the
        Port-method route end up in the same place. A missing file, a
        valueless flag, or an edit without a body flag (e.g. label-only
        edits) is a no-op.
        """
        number = next((int(a) for a in args[2:] if a.isdigit()), None)
        body = self._issue_edit_body(args)
        if number is None or body is None:
            return
        if number not in self._issues:
            raise RuntimeError(f"FakeGitHub: issue {number} not found")
        await self.update_issue_body(number, body)

    def _render_issue_view(self, args: list[str]) -> str:
        """Project requested ``gh issue view --json`` fields from fake state.

        The old dispatcher returned a hardcoded ``{"comments": []}`` for
        every selector. That matched the command while silently giving
        consumers the wrong shape. Unsupported fields are deliberately
        omitted and recorded instead of fabricated (#11246).
        """
        issue_number = next((int(a) for a in args[2:] if a.isdigit()), 0)
        selectors, fields = self._issue_view_fields(args)
        issue = self._issues.get(issue_number)
        if issue is None:
            raise RuntimeError(f"FakeGitHub: issue {issue_number} not found")

        if not selectors:
            self.issue_view_unmodelled_fields.add("--json")
        if "--jq" in args:
            self.issue_view_unmodelled_fields.add("--jq")

        projections = self._issue_view_projections(issue)
        payload: dict[str, Any] = {}
        for field_name in fields:
            if field_name in projections:
                payload[field_name] = projections[field_name]
            else:
                self.issue_view_unmodelled_fields.add(field_name)
        return json.dumps(payload)

    async def _run_gh(self, *cmd: str, cwd: Any = None) -> str:
        """Generic ``gh`` CLI passthrough — returns minimal-shape JSON.

        Production ``PRManager._run_gh`` exec's the ``gh`` CLI and returns
        stdout. The Fake parses *cmd* far enough to identify which API
        call it represents (``gh issue list``, ``gh pr list``, etc.) and
        synthesizes a JSON payload from in-memory state.

        Unknown commands RAISE (#11372) unless the shape is explicitly
        allowlisted in :data:`_QUIET_UNKNOWN_GH_SHAPES`. The old silent
        ``"[]"`` made every fidelity gap invisible: a loop probing an
        unmodelled endpoint got a plausible empty answer, its scenario
        passed, and the real adapter's behaviour was never exercised —
        the gaps were then discovered one at a time by the fake-coverage
        auditor and filed as separate issues. Failing loud converts that
        class from "discovered one escape at a time" to "enumerated once,
        at the call".
        """
        self._maybe_rate_limit()
        _ = cwd
        import json as _json

        args = list(cmd)
        # Strip leading "gh" if the caller included it (some sites do).
        if args and args[0] == "gh":
            args = args[1:]
        if not args:
            return "[]"

        verb = args[0]

        if verb == "issue" and len(args) > 1:
            sub = args[1]
            if sub == "list":
                # Return minimally-shaped issue list. StaleIssueLoop expects
                # number/title/updatedAt/labels.
                payload = [
                    {
                        "number": issue.number,
                        "title": issue.title,
                        "updatedAt": getattr(
                            issue, "updated_at", "2026-01-01T00:00:00Z"
                        ),
                        "labels": [{"name": lbl} for lbl in issue.labels],
                    }
                    for issue in self._issues.values()
                    if issue.state == "open"
                ]
                return _json.dumps(payload)
            if sub in ("close", "edit"):
                if sub == "close":
                    # Best-effort: extract issue number from positional args.
                    for a in args[2:]:
                        if a.isdigit():
                            await self.close_issue(int(a))
                            break
                else:
                    await self._handle_issue_edit(args)
                return ""
            if sub == "view":
                return self._render_issue_view(args)

        if verb == "pr" and len(args) > 1:
            sub = args[1]
            if sub == "list":
                payload = [
                    {
                        "number": pr.number,
                        "title": "",
                        "url": pr.url or "",
                        "labels": [{"name": lbl} for lbl in pr.labels],
                    }
                    for pr in self._prs.values()
                    if not pr.merged
                ]
                return _json.dumps(payload)

        # Unknown shape: FAIL LOUD (#11372). Quiet shapes are allowlisted
        # above; anything else is a fidelity gap the scenario would
        # otherwise paper over with a plausible empty answer.
        # Modelled `gh api` shapes (#11413) and the quiet allowlist share one
        # exit so the dispatcher keeps a single fall-through.
        modelled = (
            self._modelled_api_payload(args[1])
            if verb == "api" and len(args) > 1
            else None
        )
        shape = " ".join(args[:3])
        quiet = any(shape.startswith(prefix) for prefix in _QUIET_UNKNOWN_GH_SHAPES)
        if modelled is not None or quiet:
            return modelled if modelled is not None else "[]"
        raise FakeGitHubUnmodelledCommand(
            f"FakeGitHub has no model for `gh {' '.join(args)}`. Either model "
            "the command (preferred — that is the fidelity fix) or, if the "
            "caller genuinely tolerates an empty answer in the sandbox, add "
            "its prefix to _QUIET_UNKNOWN_GH_SHAPES with a one-line reason. "
            "Do NOT reintroduce a blanket empty default (#11372)."
        )
