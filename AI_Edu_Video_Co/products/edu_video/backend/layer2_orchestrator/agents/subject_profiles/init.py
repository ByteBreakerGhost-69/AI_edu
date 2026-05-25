# products/edu_video/backend/layer2_orchestrator/agents/subject_profiles/__init__.py
"""
Subject profiles package.
Importing this module triggers all @register_profile decorators,
populating PROFILE_REGISTRY so get_profile() works correctly.

Import order matters: base_profile must be imported first,
then all concrete profiles so their decorators fire.
"""

from layer2_orchestrator.agents.subject_profiles.base_profile import (
    PROFILE_REGISTRY,
    BaseSubjectProfile,
    ProfileNotFoundError,
    get_profile,
    register_profile,
)

# Import all concrete profiles to trigger @register_profile decorators
from layer2_orchestrator.agents.subject_profiles.mathematics_profile import MathematicsProfile
from layer2_orchestrator.agents.subject_profiles.physics_profile import PhysicsProfile
from layer2_orchestrator.agents.subject_profiles.chemistry_profile import ChemistryProfile
from layer2_orchestrator.agents.subject_profiles.biology_profile import BiologyProfile
from layer2_orchestrator.agents.subject_profiles.history_profile import HistoryProfile
from layer2_orchestrator.agents.subject_profiles.geography_profile import GeographyProfile
from layer2_orchestrator.agents.subject_profiles.economics_profile import EconomicsProfile
from layer2_orchestrator.agents.subject_profiles.literature_profile import LiteratureProfile
from layer2_orchestrator.agents.subject_profiles.computer_science_profile import ComputerScienceProfile
from layer2_orchestrator.agents.subject_profiles.language_profile import LanguageProfile

__all__ = [
    "BaseSubjectProfile",
    "register_profile",
    "get_profile",
    "PROFILE_REGISTRY",
    "ProfileNotFoundError",
    "MathematicsProfile",
    "PhysicsProfile",
    "ChemistryProfile",
    "BiologyProfile",
    "HistoryProfile",
    "GeographyProfile",
    "EconomicsProfile",
    "LiteratureProfile",
    "ComputerScienceProfile",
    "LanguageProfile",
]
