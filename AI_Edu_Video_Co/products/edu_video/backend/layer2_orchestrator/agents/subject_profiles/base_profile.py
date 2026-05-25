# products/edu_video/backend/layer2_orchestrator/agents/subject_profiles/base_profile.py
"""
Abstract base class for all subject profiles.
Defines the interface that every profile must implement, plus shared concrete
methods used by subject_router, script_agent, visual_asset_agent, and fact_checker_agent.
"""

from abc import ABC, abstractmethod

import structlog
from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum

__all__ = [
    "BaseSubjectProfile",
    "register_profile",
    "get_profile",
    "PROFILE_REGISTRY",
    "ProfileNotFoundError",
]

logger = structlog.get_logger(__name__)

_SCENE_COUNT: dict[str, int] = {
    "beginner": 4,
    "intermediate": 6,
    "advanced": 8,
}


class ProfileNotFoundError(Exception):
    """Raised when no profile is registered for the requested SubjectEnum."""
    pass


# Module-level registry populated by @register_profile decorator
PROFILE_REGISTRY: dict[SubjectEnum, type["BaseSubjectProfile"]] = {}


def register_profile(subject: SubjectEnum):
    """
    Class decorator factory. Registers a BaseSubjectProfile subclass into
    PROFILE_REGISTRY under the given SubjectEnum key.

    Usage:
        @register_profile(SubjectEnum.mathematics)
        class MathematicsProfile(BaseSubjectProfile):
            ...
    """
    def decorator(cls: type["BaseSubjectProfile"]) -> type["BaseSubjectProfile"]:
        PROFILE_REGISTRY[subject] = cls
        logger.debug("profile_registered", subject=subject.value, cls=cls.__name__)
        return cls
    return decorator


def get_profile(subject: SubjectEnum) -> "BaseSubjectProfile":
    """
    Instantiate and return the registered profile for a given SubjectEnum.

    Raises:
        ProfileNotFoundError: if no profile is registered for the subject.
    """
    cls = PROFILE_REGISTRY.get(subject)
    if cls is None:
        raise ProfileNotFoundError(
            f"No subject profile registered for '{subject.value}'. "
            f"Registered: {[s.value for s in PROFILE_REGISTRY]}"
        )
    return cls()


class BaseSubjectProfile(ABC):
    """
    Abstract base class for per-subject configuration profiles.

    Subclasses define subject-specific renderer preferences, validation rules,
    visual styles, and scene structure templates. They are stateless configuration
    objects — no LLM calls, no DB access.
    """

    # ------------------------------------------------------------------ #
    # Abstract properties                                                  #
    # ------------------------------------------------------------------ #

    @property
    @abstractmethod
    def subject(self) -> SubjectEnum:
        """The SubjectEnum this profile covers."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable subject name."""
        ...

    @property
    @abstractmethod
    def renderer_preference(self) -> list[str]:
        """
        Ordered list of preferred renderer types for this subject.
        Valid values: "manim"|"lottie"|"flux_sdxl"|"kling"|"timeline"
                      |"diagram"|"graph"|"code"
        First item is the primary/default renderer.
        """
        ...

    @property
    @abstractmethod
    def validation_rules(self) -> list[str]:
        """
        Machine-readable rule IDs applied by fact_checker_agent.
        e.g. ["check_equation_syntax", "check_unit_consistency"]
        """
        ...

    @property
    @abstractmethod
    def visual_style(self) -> dict:
        """
        Visual styling configuration for this subject.
        Keys: color_palette, layout, font_emphasis, animation_speed.
        """
        ...

    @property
    @abstractmethod
    def scene_structure_template(self) -> list[dict]:
        """
        Intermediate-difficulty (6-scene) blueprint for scene breakdown.
        Each entry: {scene_role, content_focus, suggested_duration_seconds}.
        Beginner/advanced variants are returned by get_script_guidelines.
        """
        ...

    # ------------------------------------------------------------------ #
    # Abstract methods                                                     #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def get_renderer_for_content(self, content_type: str) -> str:
        """
        Return the best renderer for a given content type.

        Args:
            content_type: One of "equation"|"diagram"|"text"|"graph"|"code"|"image"

        Returns:
            Renderer name string.
        """
        ...

    @abstractmethod
    def get_script_guidelines(
        self,
        difficulty: DifficultyEnum,
        curriculum: CurriculumEnum,
    ) -> str:
        """
        Return a natural-language prompt fragment injected into script_agent's
        system prompt. Should encode subject-specific narration conventions,
        notation preferences, and curriculum-specific standards.
        """
        ...

    @abstractmethod
    def get_fact_check_prompt_fragment(self) -> str:
        """
        Return a subject-specific instruction fragment injected into
        fact_checker_agent's prompt to direct domain-aware validation.
        """
        ...

    # ------------------------------------------------------------------ #
    # Concrete shared methods                                              #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        """
        Serialize all profile properties to a plain dict for storage in
        GraphState.subject_profile. Called by subject_router.
        """
        return {
            "subject": self.subject.value,
            "display_name": self.display_name,
            "renderer_preference": self.renderer_preference,
            "validation_rules": self.validation_rules,
            "visual_style": self.visual_style,
            "scene_structure_template": self.scene_structure_template,
        }

    def get_scene_count_for_difficulty(self, difficulty: DifficultyEnum) -> int:
        """Return the target scene count for the given difficulty level."""
        return _SCENE_COUNT.get(difficulty.value, 6)

    def get_primary_renderer(self) -> str:
        """Return the highest-priority renderer for this subject."""
        if not self.renderer_preference:
            return "lottie"
        return self.renderer_preference[0]

    def supports_renderer(self, renderer: str) -> bool:
        """Return True if the given renderer is in this profile's preference list."""
        return renderer in self.renderer_preference

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"subject={self.subject.value!r} "
            f"primary_renderer={self.get_primary_renderer()!r}>"
        )
