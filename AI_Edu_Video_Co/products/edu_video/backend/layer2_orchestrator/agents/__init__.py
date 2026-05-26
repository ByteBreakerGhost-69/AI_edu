# products/edu_video/backend/layer2_orchestrator/agents/__init__.py
"""
Agents package for the Layer 2 LangGraph orchestration pipeline.

Import contract:
  - All agent classes are importable directly from this package.
  - graph.py imports agents via this __init__ (lazy, inside node functions)
    so this module is NOT imported at graph compile time — only when a
    node actually executes. This keeps startup fast and avoids circular
    imports between graph.py ↔ agents/.

  - subject_profiles subpackage is imported here to trigger all
    @register_profile decorators before any agent runs.
    If a profile fails to import, the error surfaces here at worker
    startup rather than mid-job inside SubjectRouterAgent.

Import order matters:
  base_agent        — no internal deps, must be first
  subject_profiles  — registers all profiles into PROFILE_REGISTRY
  subject_router    — depends on subject_profiles
  curriculum_agent  — depends on base_agent only
  memory_agent      — depends on base_agent only
  script_agent      — depends on base_agent only
  visual_asset_agent — depends on base_agent only
  fact_checker_agent — depends on base_agent only
  animation_router  — depends on subject_profiles
"""

# --- Base class (must be first) ---
from layer2_orchestrator.agents.base_agent import BaseAgent

# --- Subject profiles (triggers all @register_profile decorators) ---
from layer2_orchestrator.agents.subject_profiles import (
    PROFILE_REGISTRY,
    BaseSubjectProfile,
    ProfileNotFoundError,
    get_profile,
    register_profile,
)

# --- Concrete agents ---
from layer2_orchestrator.agents.subject_router import SubjectRouterAgent
from layer2_orchestrator.agents.curriculum_agent import CurriculumAgent
from layer2_orchestrator.agents.memory_agent import MemoryAgent
from layer2_orchestrator.agents.script_agent import ScriptAgent
from layer2_orchestrator.agents.visual_asset_agent import VisualAssetAgent
from layer2_orchestrator.agents.fact_checker_agent import FactCheckerAgent
from layer2_orchestrator.agents.animation_router import AnimationRouterAgent

__all__ = [
    # Base
    "BaseAgent",
    # Profile registry (re-exported so callers don't need two imports)
    "BaseSubjectProfile",
    "PROFILE_REGISTRY",
    "ProfileNotFoundError",
    "get_profile",
    "register_profile",
    # Agents
    "SubjectRouterAgent",
    "CurriculumAgent",
    "MemoryAgent",
    "ScriptAgent",
    "VisualAssetAgent",
    "FactCheckerAgent",
    "AnimationRouterAgent",
]


# --------------------------------------------------------------------------- #
# Startup integrity check                                                      #
# --------------------------------------------------------------------------- #

def _verify_profile_registry() -> None:
    """
    Confirm all SubjectEnum values have a registered profile.
    Called once at import time — surfaces missing profiles immediately
    at worker startup rather than mid-job inside SubjectRouterAgent.

    Logs a warning per missing subject rather than raising, so a partially
    complete profile set (e.g. Phase 1 with only mathematics) does not
    crash workers that only process mathematics jobs.
    """
    import structlog  # noqa: PLC0415
    from layer1_input.schemas import SubjectEnum  # noqa: PLC0415

    log = structlog.get_logger(__name__)
    registered = set(PROFILE_REGISTRY.keys())
    all_subjects = set(SubjectEnum)
    missing = all_subjects - registered

    if missing:
        log.warning(
            "agents.profile_registry_incomplete",
            missing=[s.value for s in sorted(missing, key=lambda s: s.value)],
            registered=[s.value for s in sorted(registered, key=lambda s: s.value)],
            note=(
                "Jobs for missing subjects will use empty profile fallback "
                "via SubjectRouterAgent._safe_return(). "
                "Implement the missing profiles before enabling those subjects."
            ),
        )
    else:
        log.info(
            "agents.profile_registry_complete",
            count=len(registered),
            subjects=[s.value for s in sorted(registered, key=lambda s: s.value)],
        )


_verify_profile_registry()
