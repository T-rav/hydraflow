import pytest
from pydantic import ValidationError

from review_advisor import (
    Disagreement,
    FocusArea,
    PostVerifyInput,
    PostVerifyResult,
    PreFlightInput,
    ReviewPlan,
)


class TestReviewPlanSchema:
    def test_focus_area_requires_description_files_rationale(self):
        fa = FocusArea(description="d", files=["a.py"], rationale="r")
        assert fa.description == "d"
        assert fa.files == ["a.py"]

    def test_review_plan_full_shape(self):
        plan = ReviewPlan(
            risk_summary="r",
            focus_areas=[FocusArea(description="d", files=["a.py"], rationale="r")],
            rubric=["check 1", "check 2"],
            escalation_signals=["see X"],
        )
        assert plan.rubric == ["check 1", "check 2"]

    def test_review_plan_serializes_to_json_round_trip(self):
        plan = ReviewPlan(
            risk_summary="r", focus_areas=[], rubric=[], escalation_signals=[]
        )
        data = plan.model_dump_json()
        restored = ReviewPlan.model_validate_json(data)
        assert restored == plan


class TestPostVerifyResultSchema:
    def test_verdict_must_be_approve_or_veto(self):
        with pytest.raises(ValidationError):
            PostVerifyResult(verdict="MAYBE", reasoning="r", disagreements=[])

    def test_disagreement_severity_constrained(self):
        with pytest.raises(ValidationError):
            Disagreement(
                executor_claim="c",
                advisor_assessment="a",
                severity="critical",
            )

    def test_post_verify_result_minimal(self):
        r = PostVerifyResult(verdict="APPROVE", reasoning="ok", disagreements=[])
        assert r.suggested_fix_direction is None


class TestInputSchemas:
    def test_pre_flight_input_minimal(self):
        inp = PreFlightInput(surface="pr_review", diff="d")
        assert inp.spec is None
        assert inp.related_paths == []
        assert inp.prior_attempts == 0

    def test_post_verify_input_minimal(self):
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
        )
        assert inp.attempt_number == 0
        assert inp.pre_flight_plan is None


from review_advisor import (
    is_advisor_enabled,
    resolve_model,
)


class TestModelResolution:
    def test_per_surface_overrides_global(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_EXECUTOR_MODEL", "haiku")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_EXECUTOR_MODEL", "sonnet")
        assert resolve_model("pr_review", "executor", default="opus") == "haiku"

    def test_global_used_when_per_surface_unset(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_PR_REVIEW_EXECUTOR_MODEL", raising=False)
        monkeypatch.setenv("HYDRAFLOW_REVIEW_EXECUTOR_MODEL", "sonnet")
        assert resolve_model("pr_review", "executor", default="opus") == "sonnet"

    def test_default_used_when_both_unset(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_PR_REVIEW_EXECUTOR_MODEL", raising=False)
        monkeypatch.delenv("HYDRAFLOW_REVIEW_EXECUTOR_MODEL", raising=False)
        assert resolve_model("pr_review", "executor", default="sonnet") == "sonnet"


class TestKillSwitches:
    def test_master_off_disables_all(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "false")
        assert is_advisor_enabled("pr_review", "post_verify") is False

    def test_role_off_disables_role(self, monkeypatch):
        for v in (
            "HYDRAFLOW_REVIEW_ADVISOR_ENABLED",
            "HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED",
        ):
            monkeypatch.delenv(v, raising=False)
        monkeypatch.setenv("HYDRAFLOW_REVIEW_PREFLIGHT_ENABLED", "false")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED", "true")
        assert is_advisor_enabled("pr_review", "pre_flight") is False
        assert is_advisor_enabled("pr_review", "post_verify") is True

    def test_surface_off_disables_surface(self, monkeypatch):
        for v in (
            "HYDRAFLOW_REVIEW_ADVISOR_ENABLED",
            "HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED",
        ):
            monkeypatch.delenv(v, raising=False)
        monkeypatch.setenv("HYDRAFLOW_VISUAL_GATE_ADVISOR_ENABLED", "false")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "true")
        assert is_advisor_enabled("visual_gate", "post_verify") is False
        assert is_advisor_enabled("pr_review", "post_verify") is True

    def test_all_default_true(self, monkeypatch):
        for v in (
            "HYDRAFLOW_REVIEW_ADVISOR_ENABLED",
            "HYDRAFLOW_REVIEW_PREFLIGHT_ENABLED",
            "HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED",
            "HYDRAFLOW_REVIEW_MIDFLIGHT_ENABLED",
            "HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED",
        ):
            monkeypatch.delenv(v, raising=False)
        assert is_advisor_enabled("pr_review", "post_verify") is True


from review_advisor import (
    CRITICAL_PATHS,
    CompositeTrigger,
    DiffStats,
    PRContext,
    should_pre_flight,
)


class TestRoleEnvSegmentConsistency:
    def test_resolve_model_normalizes_role_like_kill_switch(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_REVIEW_PREFLIGHT_MODEL", "opus")
        assert resolve_model("pr_review", "pre_flight", default="x") == "opus"


class TestShouldPreFlight:
    @staticmethod
    def _trivial(paths, lines=5, prior=0):
        return DiffStats(changed_paths=paths, lines_changed=lines), PRContext(
            prior_fix_attempts=prior
        )

    def test_docs_only_returns_false(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["README.md", "docs/wiki/x.md"], lines=200)
        assert should_pre_flight(diff, pr) is False

    def test_test_only_returns_false(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["src/tests/test_foo.py"], lines=200)
        assert should_pre_flight(diff, pr) is False

    def test_small_src_change_returns_false(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["src/foo.py"], lines=10)
        assert should_pre_flight(diff, pr) is False

    def test_large_src_change_returns_true(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["src/foo.py"], lines=50)
        assert should_pre_flight(diff, pr) is True

    def test_critical_path_always_true(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["src/orchestrator.py"], lines=2)
        assert should_pre_flight(diff, pr) is True

    def test_critical_path_glob_persistence(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["src/persistence/store.py"], lines=2)
        assert should_pre_flight(diff, pr) is True

    def test_critical_path_glob_loop(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["src/edge_proposer_loop.py"], lines=2)
        assert should_pre_flight(diff, pr) is True

    def test_prior_fix_attempt_always_true(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["docs/wiki/x.md"], lines=5, prior=1)
        assert should_pre_flight(diff, pr) is True

    def test_force_on_overrides(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", "true")
        diff, pr = self._trivial(["docs/wiki/x.md"], lines=5)
        assert should_pre_flight(diff, pr) is True

    def test_review_phase_self_modification_critical(self):
        assert "src/review_phase.py" in CRITICAL_PATHS
        assert "src/review_advisor.py" in CRITICAL_PATHS

    def test_composite_trigger_delegates_to_should_pre_flight(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        trigger = CompositeTrigger()
        diff, pr = self._trivial(["src/foo.py"], lines=50)
        assert trigger.should_run(diff, pr) is True
        diff, pr = self._trivial(["docs/x.md"], lines=5)
        assert trigger.should_run(diff, pr) is False
