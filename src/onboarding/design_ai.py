"""Design-chat extraction for onboarding bootstrap drafts."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from onboarding.models import BootstrapDraft, BootstrapSpec

METHODOLOGY_PROMPT = (
    "Use docs/methodology/onboarding-hydraflow-format-repos.md as the canonical "
    "HydraFlow-format bootstrap methodology. Produce hypothesis-quality wizard "
    "output only; factory SHAPE will refine it after push."
)
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"

_NAME_RE = re.compile(r"\b[a-z][a-z0-9]+(?:-[a-z0-9]+)+\b")
_OWNER_RE = re.compile(
    r"\b(?:owner|org|organization)(?:\s+is|\s*:)?\s+([A-Za-z0-9_.-]{1,100})\b"
    r"|\bowned\s+by\s+([A-Za-z0-9_.-]{1,100})\b"
    r"|\bunder\s+(?:the\s+)?(?:org|organization)\s+([A-Za-z0-9_.-]{1,100})\b",
    re.I,
)
_COVERAGE_RE = re.compile(r"\b(\d{2,3})\s*%\s*(?:coverage|test coverage)\b", re.I)
_REVISION_CUES = ("actually", "instead", "switch", "change", "use", "prefer")


@dataclass(frozen=True)
class DesignTurn:
    """Structured output for one onboarding design-chat turn."""

    reply: str
    field_updates: dict[str, object]
    clarification: str | None = None
    source: str = "deterministic"
    fallback_reason: str | None = None


class _ClaudeDesignTurn(BaseModel):
    reply: str = Field(min_length=1, max_length=2000)
    field_updates: dict[str, object] = Field(default_factory=dict)
    clarification: str | None = Field(default=None, max_length=1000)


def apply_field_updates(
    spec: BootstrapSpec, updates: dict[str, object]
) -> BootstrapSpec:
    """Return a new spec with validated structured updates applied."""

    payload = spec.model_dump()
    for key, value in updates.items():
        if value is None or key not in payload:
            continue
        payload[key] = value
    return BootstrapSpec.model_validate(payload)


class DesignAIService:
    """Lightweight design assistant with a Claude-provider seam.

    The deterministic extractor keeps the dashboard usable and testable when no
    external API key is configured. A production Claude provider can replace
    ``chat`` behind this interface without changing the route or UI contracts.
    """

    def __init__(self, provider: AnthropicDesignProvider | None = None) -> None:
        self._provider = provider or AnthropicDesignProvider.from_env()

    async def chat(self, draft: BootstrapDraft, message: str) -> DesignTurn:
        if self._provider is not None:
            try:
                return await self._provider.chat(draft, message)
            except DesignProviderError as exc:
                fallback = self._deterministic_chat(draft, message)
                return DesignTurn(
                    reply=(
                        f"{fallback.reply} Claude design chat is temporarily "
                        "unavailable, so I kept form-fill mode active."
                    ),
                    field_updates=fallback.field_updates,
                    clarification=fallback.clarification,
                    fallback_reason=str(exc),
                )
        return self._deterministic_chat(draft, message)

    def _deterministic_chat(self, draft: BootstrapDraft, message: str) -> DesignTurn:
        updates = self._extract_fields(message, draft.spec)
        updated = apply_field_updates(draft.spec, updates)
        clarification = self._clarification_for(message, updated)
        reply = self._reply_for(updated, updates, clarification)
        return DesignTurn(
            reply=reply, field_updates=updates, clarification=clarification
        )

    def draft_spec(self, draft: BootstrapDraft, note: str | None = None) -> str:
        spec = draft.spec
        ui_choice = _ui_choice(spec.tech_stack)
        backend = _backend_choice(spec.tech_stack)
        note_line = f"\nRevision note: {note}" if note else ""
        return (
            "---\n"
            "status: wizard-draft\n"
            "generated_by: hydraflow-wizard\n"
            "needs_refinement: true\n"
            "methodology_refs:\n"
            "  - docs/methodology/onboarding-hydraflow-format-repos.md\n"
            "---\n\n"
            f"# {spec.name} Bootstrap Spec\n\n"
            f"## Name\n{spec.name}\n\n"
            f"## Description\n{spec.description}\n\n"
            "## Architecture Overview\n"
            f"- Backend: {backend}\n"
            f"- UI: {ui_choice}\n"
            f"- Owner: {spec.owner}\n"
            f"- Branches: {spec.main_branch} + {spec.staging_branch}\n\n"
            "## 10-file Invariant Kernel\n"
            "1. README.md\n"
            "2. CLAUDE.md\n"
            "3. pyproject.toml\n"
            "4. .env.example\n"
            "5. .github/workflows/ci.yml\n"
            "6. .github/ISSUE_TEMPLATE/feature.yml\n"
            "7. .github/pull_request_template.md\n"
            "8. docs/adr/0001-record-architecture-baseline.md\n"
            "9. docs/specs/bootstrap-spec.md\n"
            "10. docs/plans/plan-01-bootstrap.md\n\n"
            "## V1 IN\n"
            f"- {backend} implementation skeleton\n"
            f"- {spec.coverage_floor}% coverage gate\n"
            f"- Safety guards: {', '.join(spec.safety_guards) or 'standard HydraFlow guards'}\n\n"
            "## V1 OUT\n"
            "- Production credentials\n"
            "- Deep fleet-wide SHAPE refinement\n"
            "- Post-bootstrap feature backlog\n"
            f"{note_line}\n"
        )

    def draft_plan(self, draft: BootstrapDraft, note: str | None = None) -> list[str]:
        spec = draft.spec
        has_ui = _has_ui(spec.tech_stack)
        tasks = [
            f"Create the {spec.name} repository shell and invariant kernel",
            "Write README, CLAUDE.md, and environment template",
            "Add CI workflow with lint, typecheck, security scan, and tests",
            f"Set coverage floor to {spec.coverage_floor}%",
            "Create ADR-0001 and bootstrap spec handoff docs",
            "Add issue and PR templates with wizard-draft frontmatter",
            "Add smoke test for generated CLI entry point",
            "Run local quality gate before GitHub provisioning",
        ]
        if has_ui:
            tasks.insert(3, "Add UI scaffold and browser-smoke placeholder")
        if any("branch" in guard.lower() for guard in spec.safety_guards):
            tasks.append("Configure branch-protection expectations and fallback notes")
        if any("decimal" in guard.lower() for guard in spec.safety_guards):
            tasks.append("Add decimal-purity guardrail test")
        tasks.append(
            "Push wizard-drafted spec and Plan 01 for factory SHAPE refinement"
        )
        if note:
            tasks.append(f"Apply operator revision note: {note}")
        return tasks

    def _extract_fields(
        self, message: str, current: BootstrapSpec
    ) -> dict[str, object]:
        lowered = message.lower()
        updates: dict[str, object] = {}

        name_match = _NAME_RE.search(lowered)
        if name_match:
            updates["name"] = name_match.group(0)

        owner_match = _OWNER_RE.search(message)
        if owner_match:
            updates["owner"] = next(
                group for group in owner_match.groups() if group is not None
            )

        if (
            "public" in lowered or "open source" in lowered or "open-source" in lowered
        ) and "not public" not in lowered:
            updates["visibility"] = "public"
        elif "private" in lowered or "internal" in lowered or "not public" in lowered:
            updates["visibility"] = "private"

        coverage_match = _COVERAGE_RE.search(message)
        if coverage_match:
            updates["coverage_floor"] = min(100, max(0, int(coverage_match.group(1))))

        stack = list(current.tech_stack)
        revising = any(cue in lowered for cue in _REVISION_CUES)
        if "no ui" in lowered or "none ui" in lowered or "ui none" in lowered:
            stack = [
                item
                for item in stack
                if item.lower() not in {"react", "next.js", "nextjs"}
            ]
        elif revising and (
            "react" in lowered or "next.js" in lowered or "nextjs" in lowered
        ):
            stack = [item for item in stack if item.lower() != "ui=none"]
            if "next.js" in lowered or "nextjs" in lowered:
                stack = [item for item in stack if item.lower() != "react"]
            if (
                "react" in lowered
                and "next.js" not in lowered
                and "nextjs" not in lowered
            ):
                stack = [
                    item for item in stack if item.lower() not in {"next.js", "nextjs"}
                ]
        if "sqlite" in lowered and revising:
            stack = [item for item in stack if item.lower() != "postgres"]
        if ("postgres" in lowered or "postgresql" in lowered) and revising:
            stack = [item for item in stack if item.lower() != "sqlite"]
        skip_stack_labels: set[str] = set()
        instead_of = (
            lowered.split("instead of", 1)[1] if "instead of" in lowered else ""
        )
        if "postgres" in instead_of or "not postgres" in lowered:
            skip_stack_labels.add("Postgres")
        if "react" in instead_of or "not react" in lowered:
            skip_stack_labels.add("React")
        if "sqlite" in instead_of or "not sqlite" in lowered:
            skip_stack_labels.add("SQLite")
        if "next.js" in instead_of or "nextjs" in instead_of or "not next" in lowered:
            skip_stack_labels.add("Next.js")
        for keyword, label in (
            ("fastapi", "FastAPI"),
            ("django", "Django"),
            ("flask", "Flask"),
            ("python", "python"),
            ("react", "React"),
            ("next.js", "Next.js"),
            ("nextjs", "Next.js"),
            ("sqlite", "SQLite"),
            ("postgres", "Postgres"),
            ("postgresql", "Postgres"),
            ("none ui", "UI=None"),
            ("no ui", "UI=None"),
            ("ui none", "UI=None"),
        ):
            if (
                keyword in lowered
                and label not in stack
                and label not in skip_stack_labels
            ):
                stack.append(label)
        if stack != current.tech_stack:
            updates["tech_stack"] = stack

        guards = list(current.safety_guards)
        for keyword, label in (
            ("branch protection", "branch-protection"),
            ("deterministic", "deterministic-tests"),
            ("decimal", "decimal-purity"),
            ("quality gate", "quality-gates"),
            ("quality gates", "quality-gates"),
            ("adr", "adr-review"),
        ):
            if keyword in lowered and label not in guards:
                guards.append(label)
        if guards != current.safety_guards:
            updates["safety_guards"] = guards

        if len(message.strip()) >= 20:
            updates["description"] = _description_for(message)

        return updates

    def _clarification_for(self, message: str, spec: BootstrapSpec) -> str | None:
        lowered = message.lower()
        if "i don't know" in lowered or "not sure" in lowered:
            return "I can keep the standard Python path unless you want a specific backend or UI."
        if "ui" in lowered and not _has_ui(spec.tech_stack) and "no ui" not in lowered:
            return "Do you want React, Next.js, or no UI for the bootstrap?"
        return None

    def _reply_for(
        self, spec: BootstrapSpec, updates: dict[str, object], clarification: str | None
    ) -> str:
        changed = ", ".join(sorted(updates)) if updates else "no fields"
        base = (
            f"Updated {changed}. Current draft is {spec.name} "
            f"({spec.visibility}) with {_backend_choice(spec.tech_stack)}."
        )
        if clarification:
            return f"{base} {clarification}"
        return f"{base} Draft the spec when these fields look right."


class DesignProviderError(RuntimeError):
    """Raised when the live design provider cannot produce valid output."""


class AnthropicDesignProvider:
    """Claude-backed structured design chat provider."""

    def __init__(self, api_key: str, model: str = DEFAULT_CLAUDE_MODEL) -> None:
        self.api_key = api_key
        self.model = model

    @classmethod
    def from_env(cls) -> AnthropicDesignProvider | None:
        api_key = (
            os.environ.get("HYDRAFLOW_ONBOARDING_ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or ""
        ).strip()
        if not api_key:
            return None
        model = os.environ.get("HYDRAFLOW_ONBOARDING_CLAUDE_MODEL", "").strip()
        return cls(api_key=api_key, model=model or DEFAULT_CLAUDE_MODEL)

    async def chat(self, draft: BootstrapDraft, message: str) -> DesignTurn:
        prompt = _build_claude_prompt(draft, message)
        raw = await self._request(prompt)
        try:
            parsed = _parse_claude_turn(raw)
        except DesignProviderError:
            raw = await self._request(
                f"{prompt}\n\nYour previous response was invalid. Return only valid JSON."
            )
            parsed = _parse_claude_turn(raw)
        updates = _sanitize_field_updates(parsed.field_updates)
        return DesignTurn(
            reply=parsed.reply,
            field_updates=updates,
            clarification=parsed.clarification,
            source="claude",
        )

    async def _request(self, prompt: str) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 1200,
            "temperature": 0,
            "system": METHODOLOGY_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    ANTHROPIC_MESSAGES_URL, headers=headers, json=payload
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DesignProviderError("Claude request failed") from exc
        return _extract_text_content(data)


def _build_claude_prompt(draft: BootstrapDraft, message: str) -> str:
    conversation = "\n".join(
        f"{item.get('role', 'unknown')}: {item.get('content', '')}"
        for item in draft.chat_messages[-12:]
    )
    return (
        "You are HydraFlow's onboarding design assistant.\n"
        "Return ONLY JSON with this schema:\n"
        "{"
        '"reply": "operator-facing response", '
        '"field_updates": {"name": "...", "description": "...", '
        '"owner": "...", "visibility": "private|public", '
        '"tech_stack": ["python", "FastAPI"], '
        '"safety_guards": ["branch-protection"], "coverage_floor": 85}, '
        '"clarification": "optional question or null"'
        "}\n"
        "Only include field_updates when the operator supplied or revised the field. "
        "Surface ambiguity as clarification instead of guessing.\n\n"
        f"Current spec JSON:\n{draft.spec.model_dump_json()}\n\n"
        f"Recent conversation:\n{conversation or '(none)'}\n\n"
        f"Operator message:\n{message}"
    )


def _extract_text_content(data: dict[str, Any]) -> str:
    parts = data.get("content")
    if not isinstance(parts, list):
        raise DesignProviderError("Claude response has no text content")
    text = "".join(
        str(part.get("text", "")) for part in parts if part.get("type") == "text"
    ).strip()
    if not text:
        raise DesignProviderError("Claude response text is empty")
    return text


def _parse_claude_turn(raw: str) -> _ClaudeDesignTurn:
    text = raw.strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise DesignProviderError("Claude response was not JSON")
        text = text[start : end + 1]
    try:
        payload = json.loads(text)
        return _ClaudeDesignTurn.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise DesignProviderError("Claude response did not match schema") from exc


def _sanitize_field_updates(updates: dict[str, object]) -> dict[str, object]:
    allowed = set(BootstrapSpec.model_fields)
    sanitized: dict[str, object] = {}
    for key, value in updates.items():
        if key in allowed and value is not None:
            sanitized[key] = value
    return sanitized


def _description_for(message: str) -> str:
    normalized = " ".join(message.strip().split())
    if len(normalized) > 500:
        normalized = normalized[:497].rstrip() + "..."
    if len(normalized) < 10:
        return "HydraFlow-format bootstrap project."
    return normalized


def _has_ui(stack: list[str]) -> bool:
    lowered = {item.lower() for item in stack}
    return bool({"react", "next.js", "nextjs"} & lowered) and "ui=none" not in lowered


def _ui_choice(stack: list[str]) -> str:
    lowered = {item.lower() for item in stack}
    if "next.js" in lowered or "nextjs" in lowered:
        return "Next.js"
    if "react" in lowered:
        return "React"
    return "None"


def _backend_choice(stack: list[str]) -> str:
    lowered = {item.lower() for item in stack}
    if "fastapi" in lowered:
        return "Python 3.11 + FastAPI"
    if "django" in lowered:
        return "Python 3.11 + Django"
    if "flask" in lowered:
        return "Python 3.11 + Flask"
    return "Python 3.11"
