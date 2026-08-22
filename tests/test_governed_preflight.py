"""Strict pre-upstream binding for a governed key (ADR-0141 D3).

Every refusal here happens *before* an upstream request object exists, which is
what "zero upstream bytes" means structurally rather than by observation. The
proxy test that watches a fake origin is the observation; this file pins the
predicate the proxy asks.
"""

from __future__ import annotations

import pytest

from hydraflow_gateway.governed_preflight import (
    GOVERNED_MESSAGE_PATHS,
    GovernedRequestRefused,
    PreflightRefusal,
    check_governed_body,
    governed_path_supported,
)


@pytest.mark.parametrize(
    ("path", "supported"),
    [
        pytest.param("/v1/messages", True, id="the-message-face-is-bound"),
        pytest.param(
            "/v1/messages/count_tokens",
            True,
            id="the-token-count-face-carries-a-model-and-is-bound",
        ),
        pytest.param("/v1/models", False, id="a-catalogue-read-is-not-a-bound-face"),
        pytest.param(
            "/v1/complete", False, id="the-legacy-completion-face-is-not-bound"
        ),
        pytest.param("/", False, id="an-unrecognised-path-is-not-a-bound-face"),
        pytest.param(
            "/v1/messages/batches",
            False,
            id="a-batch-submission-is-not-the-message-face",
        ),
    ],
)
def test_only_the_enumerated_message_faces_are_supported(
    path: str, supported: bool
) -> None:
    """A governed key reaches an explicitly enumerated face, or nothing."""
    assert governed_path_supported(path) is supported


def test_the_supported_face_set_is_the_one_the_module_publishes() -> None:
    """The predicate and the published constant cannot drift apart."""
    assert all(governed_path_supported(path) for path in GOVERNED_MESSAGE_PATHS)


def _refusal(**kwargs: object) -> PreflightRefusal:
    with pytest.raises(GovernedRequestRefused) as caught:
        check_governed_body(**kwargs)  # type: ignore[arg-type]
    return caught.value.refusal


def test_a_body_naming_the_bound_model_passes() -> None:
    """The affirmative case, so every refusal assertion below is not vacuous."""
    check_governed_body(
        b'{"model": "glm-5.3", "messages": []}',
        bound_model="glm-5.3",
        content_type="application/json",
    )


def test_a_bound_model_comparison_ignores_surrounding_whitespace() -> None:
    """A trailing space in an argv-derived model is not a binding violation."""
    check_governed_body(
        b'{"model": " glm-5.3 "}',
        bound_model="glm-5.3",
        content_type="application/json",
    )


@pytest.mark.parametrize(
    ("body", "content_type", "expected"),
    [
        pytest.param(
            b'{"model": "claude-opus-4-8"}',
            "application/json",
            PreflightRefusal.MODEL_NOT_BOUND,
            id="a-different-model-is-refused",
        ),
        pytest.param(
            b'{"messages": []}',
            "application/json",
            PreflightRefusal.MISSING_MODEL_KEY,
            id="a-body-with-no-model-key-is-refused",
        ),
        pytest.param(
            b'{"model": "glm-5.3", "model": "claude-opus-4-8"}',
            "application/json",
            PreflightRefusal.DUPLICATE_MODEL_KEY,
            id="a-duplicated-model-key-is-refused-not-last-write-wins",
        ),
        pytest.param(
            b'{"model": 7}',
            "application/json",
            PreflightRefusal.MISSING_MODEL_KEY,
            id="a-non-string-model-is-not-a-model",
        ),
        pytest.param(
            b"not json at all",
            "application/json",
            PreflightRefusal.BODY_NOT_JSON_OBJECT,
            id="an-unparseable-body-is-refused",
        ),
        pytest.param(
            b'["model"]',
            "application/json",
            PreflightRefusal.BODY_NOT_JSON_OBJECT,
            id="a-json-array-is-not-a-message-body",
        ),
        pytest.param(
            b"",
            "application/json",
            PreflightRefusal.BODY_NOT_JSON_OBJECT,
            id="an-empty-body-cannot-carry-a-binding",
        ),
        pytest.param(
            b'{"model": "glm-5.3"}',
            "text/plain",
            PreflightRefusal.UNSUPPORTED_CONTENT_TYPE,
            id="a-non-json-content-type-is-refused-before-parsing",
        ),
        pytest.param(
            b'{"model": "glm-5.3"}',
            "",
            PreflightRefusal.UNSUPPORTED_CONTENT_TYPE,
            id="an-absent-content-type-is-refused",
        ),
    ],
)
def test_every_way_a_body_can_defeat_the_binding_is_refused(
    body: bytes, content_type: str, expected: PreflightRefusal
) -> None:
    """Each refusal is a distinct code, never a shared generic failure."""
    assert (
        _refusal(body=body, bound_model="glm-5.3", content_type=content_type)
        is expected
    )


def test_a_charset_parameter_does_not_defeat_the_content_type_check() -> None:
    """``application/json; charset=utf-8`` is the CLI's own header."""
    check_governed_body(
        b'{"model": "glm-5.3"}',
        bound_model="glm-5.3",
        content_type="application/json; charset=utf-8",
    )


def test_a_duplicate_key_elsewhere_in_the_body_is_still_refused() -> None:
    """Duplicate-key detection is a property of the whole body, not of ``model``.

    A body that JSON-decodes differently in two parsers is not a body a binding
    can be checked against at all, wherever the ambiguity sits.
    """
    assert (
        _refusal(
            body=b'{"model": "glm-5.3", "max_tokens": 1, "max_tokens": 2}',
            bound_model="glm-5.3",
            content_type="application/json",
        )
        is PreflightRefusal.DUPLICATE_MODEL_KEY
    )


def test_the_refusal_never_quotes_the_body_back() -> None:
    """A refusal can reach a log; a prompt body must not travel with it."""
    with pytest.raises(GovernedRequestRefused) as caught:
        check_governed_body(
            b'{"model": "claude-opus-4-8", "messages": [{"role": "user"}]}',
            bound_model="glm-5.3",
            content_type="application/json",
        )

    assert "role" not in str(caught.value)
