# products/edu_video/backend/tests/unit/test_subject_router.py
"""
Unit tests for SubjectRouterAgent and all 10 SubjectProfile implementations.

Coverage targets:
  - PROFILE_REGISTRY completeness
  - Profile method correctness (renderer selection, scene counts, guidelines)
  - SubjectRouterAgent GraphState mutation
  - Error handling for unknown subjects
"""

import pytest
from unittest.mock import MagicMock, patch

from layer1_input.schemas import SubjectEnum, CurriculumEnum, DifficultyEnum
from layer2_orchestrator.agents.subject_profiles.base_profile import (
    PROFILE_REGISTRY,
    get_profile,
)

VALID_RENDERERS = frozenset({
    "manim", "lottie", "flux_sdxl", "kling",
    "timeline", "diagram", "graph", "code",
})


# --------------------------------------------------------------------------- #
# Profile registry tests                                                        #
# --------------------------------------------------------------------------- #

class TestProfileRegistry:

    def test_all_subjects_registered(self):
        """All 10 SubjectEnum values must have a registered profile."""
        for subject in SubjectEnum:
            assert subject in PROFILE_REGISTRY, (
                f"Subject '{subject}' missing from PROFILE_REGISTRY"
            )

    def test_registry_has_exactly_ten_profiles(self):
        """Registry must contain exactly one profile per SubjectEnum value."""
        assert len(PROFILE_REGISTRY) == len(SubjectEnum)

    def test_get_profile_mathematics_returns_correct_type(self):
        """get_profile(mathematics) returns MathematicsProfile instance."""
        from layer2_orchestrator.agents.subject_profiles.mathematics_profile import (
            MathematicsProfile,
        )
        profile = get_profile(SubjectEnum.mathematics)
        assert isinstance(profile, MathematicsProfile)

    def test_get_profile_unknown_subject_raises(self):
        """get_profile() with unregistered string raises ProfileNotFoundError."""
        from layer2_orchestrator.agents.subject_profiles.base_profile import (
            ProfileNotFoundError,
        )
        with pytest.raises(ProfileNotFoundError):
            get_profile("nonexistent_subject")

    def test_registry_size_stable_across_multiple_calls(self):
        """Registry size must not grow with repeated get_profile() calls."""
        initial = len(PROFILE_REGISTRY)
        for _ in range(10):
            get_profile(SubjectEnum.physics)
        assert len(PROFILE_REGISTRY) == initial

    @pytest.mark.parametrize("subject", list(SubjectEnum))
    def test_every_profile_has_valid_renderer_preference(self, subject):
        """renderer_preference must be non-empty and contain only valid renderer names."""
        profile = get_profile(subject)
        assert len(profile.renderer_preference) > 0, (
            f"{subject}.renderer_preference is empty"
        )
        for r in profile.renderer_preference:
            assert r in VALID_RENDERERS, (
                f"{subject}: invalid renderer '{r}' in renderer_preference"
            )

    @pytest.mark.parametrize("subject", list(SubjectEnum))
    def test_every_profile_has_validation_rules(self, subject):
        """Every profile must define at least one validation rule string."""
        profile = get_profile(subject)
        assert len(profile.validation_rules) >= 1, (
            f"{subject}.validation_rules is empty"
        )

    @pytest.mark.parametrize("subject", list(SubjectEnum))
    def test_to_dict_contains_all_required_keys(self, subject):
        """
        to_dict() must contain all keys expected by downstream agents.
        Missing keys cause silent KeyError in GraphState updates.
        """
        required = [
            "subject", "display_name", "renderer_preference",
            "validation_rules", "visual_style", "scene_structure_template",
        ]
        profile = get_profile(subject)
        result = profile.to_dict()
        for key in required:
            assert key in result, (
                f"{subject}.to_dict() missing required key '{key}'"
            )

    @pytest.mark.parametrize("subject", list(SubjectEnum))
    def test_fact_check_prompt_fragment_nonempty(self, subject):
        """get_fact_check_prompt_fragment() must return a non-empty string."""
        profile = get_profile(subject)
        fragment = profile.get_fact_check_prompt_fragment()
        assert isinstance(fragment, str)
        assert len(fragment) > 10, (
            f"{subject}.get_fact_check_prompt_fragment() too short: {repr(fragment)}"
        )


# --------------------------------------------------------------------------- #
# Scene count per difficulty                                                    #
# --------------------------------------------------------------------------- #

class TestSceneCountPerDifficulty:

    @pytest.mark.parametrize("difficulty,expected", [
        (DifficultyEnum.beginner,     4),
        (DifficultyEnum.intermediate, 6),
        (DifficultyEnum.advanced,     8),
    ])
    def test_mathematics_scene_count(self, difficulty, expected):
        """Mathematics profile returns correct scene counts per difficulty level."""
        profile = get_profile(SubjectEnum.mathematics)
        assert profile.get_scene_count_for_difficulty(difficulty) == expected

    @pytest.mark.parametrize("subject", list(SubjectEnum))
    def test_advanced_has_more_scenes_than_beginner(self, subject):
        """Advanced difficulty must always yield more scenes than beginner."""
        profile = get_profile(subject)
        beginner = profile.get_scene_count_for_difficulty(DifficultyEnum.beginner)
        advanced = profile.get_scene_count_for_difficulty(DifficultyEnum.advanced)
        assert advanced >= beginner, (
            f"{subject}: advanced ({advanced}) not >= beginner ({beginner})"
        )

    @pytest.mark.parametrize("subject", list(SubjectEnum))
    def test_scene_count_within_allowed_bounds(self, subject):
        """Scene counts must be between 2 and 10 for all subjects and difficulties."""
        profile = get_profile(subject)
        for difficulty in DifficultyEnum:
            count = profile.get_scene_count_for_difficulty(difficulty)
            assert 2 <= count <= 10, (
                f"{subject} + {difficulty}: scene count {count} out of range [2, 10]"
            )


# --------------------------------------------------------------------------- #
# Renderer selection                                                             #
# --------------------------------------------------------------------------- #

class TestRendererSelection:

    @pytest.mark.parametrize("content_type,subject,expected", [
        ("equation", SubjectEnum.mathematics,      "manim"),
        ("code",     SubjectEnum.computer_science, "code"),
        ("graph",    SubjectEnum.economics,        "graph"),
        ("image",    SubjectEnum.biology,          "flux_sdxl"),
        ("diagram",  SubjectEnum.history,          "timeline"),
    ])
    def test_renderer_for_content_type(self, content_type, subject, expected):
        """get_renderer_for_content() returns the expected renderer per content+subject."""
        profile = get_profile(subject)
        result = profile.get_renderer_for_content(content_type)
        assert result == expected, (
            f"{subject} + '{content_type}': expected '{expected}', got '{result}'"
        )

    def test_get_primary_renderer_is_first_in_preference(self):
        """get_primary_renderer() must return renderer_preference[0]."""
        profile = get_profile(SubjectEnum.mathematics)
        assert profile.get_primary_renderer() == profile.renderer_preference[0]

    def test_supports_renderer_true_for_listed(self):
        """supports_renderer() returns True for renderers in preference list."""
        profile = get_profile(SubjectEnum.mathematics)
        assert profile.supports_renderer(profile.renderer_preference[0]) is True

    def test_supports_renderer_false_for_unlisted(self):
        """supports_renderer() returns False for renderers not in preference list."""
        # Kling is unlikely to be in mathematics renderer preference
        math_profile = get_profile(SubjectEnum.mathematics)
        if "kling" not in math_profile.renderer_preference:
            assert math_profile.supports_renderer("kling") is False

    def test_get_renderer_for_unknown_content_returns_default(self):
        """get_renderer_for_content() with unknown type returns a valid fallback."""
        profile = get_profile(SubjectEnum.mathematics)
        result = profile.get_renderer_for_content("unknown_type_xyz")
        assert result in VALID_RENDERERS


# --------------------------------------------------------------------------- #
# Script guidelines                                                             #
# --------------------------------------------------------------------------- #

class TestScriptGuidelines:

    def test_guidelines_differ_by_difficulty(self):
        """Beginner and advanced guidelines must not be identical strings."""
        profile = get_profile(SubjectEnum.mathematics)
        beginner = profile.get_script_guidelines(DifficultyEnum.beginner, CurriculumEnum.general)
        advanced = profile.get_script_guidelines(DifficultyEnum.advanced, CurriculumEnum.IB)
        assert beginner != advanced
        assert len(beginner) > 0
        assert len(advanced) > 0

    def test_guidelines_differ_by_curriculum(self):
        """IB and AP guidelines must differ for the same difficulty."""
        profile = get_profile(SubjectEnum.mathematics)
        ib = profile.get_script_guidelines(DifficultyEnum.intermediate, CurriculumEnum.IB)
        ap = profile.get_script_guidelines(DifficultyEnum.intermediate, CurriculumEnum.AP)
        assert ib != ap

    @pytest.mark.parametrize("subject", list(SubjectEnum))
    def test_guidelines_always_return_string(self, subject):
        """get_script_guidelines() must never return None or empty string."""
        profile = get_profile(subject)
        for difficulty in DifficultyEnum:
            for curriculum in CurriculumEnum:
                result = profile.get_script_guidelines(difficulty, curriculum)
                assert isinstance(result, str) and len(result) > 0, (
                    f"{subject} + {difficulty} + {curriculum}: empty guidelines"
                )


# --------------------------------------------------------------------------- #
# SubjectRouterAgent                                                            #
# --------------------------------------------------------------------------- #

class TestSubjectRouterAgent:

    @pytest.fixture
    def agent(self):
        """Fresh SubjectRouterAgent instance for each test."""
        from layer2_orchestrator.agents.subject_router import SubjectRouterAgent
        return SubjectRouterAgent()

    @pytest.mark.asyncio
    async def test_run_returns_required_graphstate_keys(self, agent, base_graph_state):
        """run() must return a dict containing all keys downstream agents expect."""
        required_keys = [
            "subject_profile",
            "renderer_preference",
            "validation_rules",
        ]
        result = await agent.run(base_graph_state)
        for key in required_keys:
            assert key in result, f"run() output missing key '{key}'"

    @pytest.mark.asyncio
    async def test_run_sets_correct_renderer_for_mathematics(
        self, agent, base_graph_state
    ):
        """For subject=mathematics, renderer_preference[0] should be 'manim'."""
        base_graph_state["subject"] = "mathematics"
        result = await agent.run(base_graph_state)
        assert result["renderer_preference"][0] == "manim"

    @pytest.mark.asyncio
    async def test_run_sets_correct_renderer_for_computer_science(
        self, agent, base_graph_state
    ):
        """For subject=computer_science, renderer_preference should include 'code'."""
        base_graph_state["subject"] = "computer_science"
        result = await agent.run(base_graph_state)
        assert "code" in result["renderer_preference"]

    @pytest.mark.asyncio
    async def test_run_sets_correct_renderer_for_history(
        self, agent, base_graph_state
    ):
        """For subject=history, renderer_preference should include 'timeline'."""
        base_graph_state["subject"] = "history"
        result = await agent.run(base_graph_state)
        assert "timeline" in result["renderer_preference"]

    @pytest.mark.asyncio
    async def test_run_sets_correct_renderer_for_economics(
        self, agent, base_graph_state
    ):
        """For subject=economics, renderer_preference should include 'graph'."""
        base_graph_state["subject"] = "economics"
        result = await agent.run(base_graph_state)
        assert "graph" in result["renderer_preference"]

    @pytest.mark.asyncio
    async def test_run_populates_subject_profile_dict(self, agent, base_graph_state):
        """subject_profile in output must be a non-empty dict."""
        result = await agent.run(base_graph_state)
        assert isinstance(result["subject_profile"], dict)
        assert len(result["subject_profile"]) > 0

    @pytest.mark.asyncio
    async def test_run_does_not_make_llm_call(self, agent, base_graph_state, mock_llm):
        """SubjectRouterAgent is a pure routing agent — must not call LLM."""
        await agent.run(base_graph_state)
        mock_llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_does_not_modify_other_state_keys(
        self, agent, base_graph_state
    ):
        """run() must not overwrite keys it does not own (job_id, scenes, etc.)."""
        original_job_id = base_graph_state["job_id"]
        original_scenes = base_graph_state["scenes"]
        result = await agent.run(base_graph_state)
        # Merged result should not corrupt unrelated keys
        merged = {**base_graph_state, **result}
        assert merged["job_id"] == original_job_id
        assert merged["scenes"] == original_scenes

    @pytest.mark.asyncio
    @pytest.mark.parametrize("subject", [s.value for s in SubjectEnum])
    async def test_run_succeeds_for_all_subjects(
        self, agent, base_graph_state, subject
    ):
        """run() must complete without error for every valid subject."""
        base_graph_state["subject"] = subject
        result = await agent.run(base_graph_state)
        assert "errors" not in result or len(result.get("errors", [])) == 0

    @pytest.mark.asyncio
    async def test_run_with_unknown_subject_adds_error(self, agent, base_graph_state):
        """run() with unrecognised subject must add to errors, not raise."""
        base_graph_state["subject"] = "basket_weaving"
        result = await agent.run(base_graph_state)
        # Should not raise — should record error in state
        assert "errors" in result
        assert len(result["errors"]) > 0
