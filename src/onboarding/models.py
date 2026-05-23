"""Typed models for HydraFlow-format repository onboarding."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_PROJECT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}[a-z0-9]$")
_OWNER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_LABEL_PREFIX_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class BootstrapSpec(BaseModel):
    """Operator-provided customization knobs for a new HydraFlow-format repo."""

    name: str = Field(
        min_length=3,
        max_length=64,
        description="GitHub repository name, lowercase kebab-case.",
    )
    description: str = Field(min_length=10, max_length=500)
    owner: str = Field(min_length=1, max_length=100)
    visibility: Literal["private", "public"] = "private"
    tech_stack: list[str] = Field(default_factory=lambda: ["python"])
    safety_guards: list[str] = Field(default_factory=list)
    coverage_floor: int = Field(default=80, ge=0, le=100)
    package_name: str | None = Field(default=None, max_length=100)
    label_prefix: str = Field(default="hydraflow", max_length=40)
    main_branch: str = Field(default="main", min_length=1, max_length=100)
    staging_branch: str = Field(default="staging", min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _PROJECT_NAME_RE.fullmatch(normalized):
            raise ValueError("name must be lowercase kebab-case")
        return normalized

    @field_validator("owner")
    @classmethod
    def validate_owner(cls, value: str) -> str:
        normalized = value.strip()
        if not _OWNER_RE.fullmatch(normalized):
            raise ValueError("owner must be a GitHub owner or organization name")
        return normalized

    @field_validator("label_prefix")
    @classmethod
    def validate_label_prefix(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _LABEL_PREFIX_RE.fullmatch(normalized):
            raise ValueError("label_prefix must be lowercase kebab-case")
        return normalized

    @field_validator("tech_stack", "safety_guards")
    @classmethod
    def normalize_string_list(cls, values: list[str]) -> list[str]:
        normalized = [str(value).strip() for value in values if str(value).strip()]
        return list(dict.fromkeys(normalized))


class BootstrapDraft(BaseModel):
    """Persisted onboarding draft state exposed by `/api/onboarding/drafts`."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    spec: BootstrapSpec
    status: Literal[
        "draft", "materializing", "materialized", "pushing", "pushed", "error"
    ] = "draft"
    materialize_status: Literal["not_started", "running", "succeeded", "failed"] = (
        "not_started"
    )
    push_status: Literal["not_started", "running", "succeeded", "failed"] = (
        "not_started"
    )
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)
    events: list[dict[str, str]] = Field(default_factory=list)
    chat_messages: list[dict[str, str]] = Field(default_factory=list)
    extracted_fields: dict[str, object] = Field(default_factory=dict)
    spec_draft: str | None = None
    plan_draft: list[str] = Field(default_factory=list)
    materialized_path: str | None = Field(default=None, max_length=1000)
    repo_url: str | None = Field(default=None, max_length=1000)

    def touch(self) -> None:
        self.updated_at = _utc_now()


class MaterializeRequest(BaseModel):
    """Request body for local draft materialization."""

    output_dir: str | None = Field(
        default=None,
        description="Optional parent directory for generated repos.",
        max_length=1000,
    )

    @field_validator("output_dir")
    @classmethod
    def normalize_output_dir(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DesignChatRequest(BaseModel):
    """Operator chat turn for onboarding design extraction."""

    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message is required")
        return normalized


class DesignRevisionRequest(BaseModel):
    """Optional operator note for regenerating wizard-drafted artifacts."""

    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SaveSpecDraftRequest(BaseModel):
    """Operator-edited wizard spec draft content."""

    spec_draft: str = Field(min_length=1, max_length=20000)

    @field_validator("spec_draft")
    @classmethod
    def normalize_spec_draft(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("spec_draft is required")
        return normalized


class ContinuePlanRequest(BaseModel):
    """Request body for filing the next onboarding plan issue batch."""

    current_plan: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("current_plan", "note")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
