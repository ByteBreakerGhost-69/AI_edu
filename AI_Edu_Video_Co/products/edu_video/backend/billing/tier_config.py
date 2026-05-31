# products/edu_video/backend/billing/tier_config.py
"""
TierConfig: single source of truth for all feature gates and limits per tier.
Loaded at startup. Readable by all layers without DB or Redis calls.
Writes config/tier_limits.yaml on first run; accepts ops overrides from that file.
"""

from pathlib import Path

import structlog
import yaml
from pydantic import BaseModel

from core.config import get_settings

__all__ = ["TierConfig", "TierFeatures", "FeatureGateResult", "tier_config"]

logger = structlog.get_logger(__name__)
settings = get_settings()


class TierFeatures(BaseModel):
    tier: str
    videos_per_month: int
    max_scenes_per_video: int
    allowed_subjects: list[str]
    allowed_curricula: list[str]
    allowed_languages: list[str]
    allowed_difficulty_levels: list[str]
    priority_queue: bool
    human_review: bool
    watermark: bool
    subtitle_download: bool
    api_access: bool
    storage_retention_days: int
    max_video_duration_seconds: int
    monthly_cost_usd: float


class FeatureGateResult(BaseModel):
    allowed: bool
    reason: str | None = None
    upgrade_required: bool = False
    suggested_tier: str | None = None


class TierConfig:
    """
    Manages feature gates and limits for free and premium tiers.
    TIER_DEFINITIONS is the runtime source of truth — ops can override
    values via TIER_CONFIG_PATH yaml without redeploying.
    """

    TIER_DEFINITIONS: dict[str, TierFeatures] = {
        "free": TierFeatures(
            tier="free",
            videos_per_month=3,
            max_scenes_per_video=4,
            allowed_subjects=["mathematics", "physics", "chemistry", "biology"],
            allowed_curricula=["general"],
            allowed_languages=["en", "id"],
            allowed_difficulty_levels=["beginner"],
            priority_queue=False,
            human_review=False,
            watermark=True,
            subtitle_download=False,
            api_access=False,
            storage_retention_days=7,
            max_video_duration_seconds=180,
            monthly_cost_usd=0.0,
        ),
        "premium": TierFeatures(
            tier="premium",
            videos_per_month=50,
            max_scenes_per_video=8,
            allowed_subjects=[
                "mathematics", "physics", "chemistry", "biology",
                "history", "geography", "economics", "literature",
                "computer_science", "language",
            ],
            allowed_curricula=["IB", "Cambridge", "AP", "general"],
            allowed_languages=["en", "id", "es", "fr", "de", "zh", "ar", "ja", "pt", "ko"],
            allowed_difficulty_levels=["beginner", "intermediate", "advanced"],
            priority_queue=True,
            human_review=True,
            watermark=False,
            subtitle_download=True,
            api_access=True,
            storage_retention_days=365,
            max_video_duration_seconds=600,
            monthly_cost_usd=29.0,
        ),
    }

    def __init__(self) -> None:
        self.log = structlog.get_logger(self.__class__.__name__)

    def load(self) -> None:
        """
        Load tier config from YAML. Writes defaults if file doesn't exist.
        Accepts partial overrides — only listed keys are updated.
        Call once at startup from main.py lifespan.
        """
        config_path = Path(settings.TIER_CONFIG_PATH)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        if not config_path.exists():
            config_data = {
                tier: features.model_dump()
                for tier, features in self.TIER_DEFINITIONS.items()
            }
            config_path.write_text(
                yaml.dump(config_data, default_flow_style=False),
                encoding="utf-8",
            )
            self.log.info("tier_config_created", path=str(config_path))
            return

        with config_path.open(encoding="utf-8") as f:
            overrides = yaml.safe_load(f) or {}

        for tier, data in overrides.items():
            if tier not in self.TIER_DEFINITIONS:
                self.log.warning("tier_config_unknown_tier", tier=tier)
                continue
            if not isinstance(data, dict):
                continue
            current = self.TIER_DEFINITIONS[tier].model_dump()
            current.update(data)
            try:
                self.TIER_DEFINITIONS[tier] = TierFeatures(**current)
            except Exception as exc:
                self.log.error(
                    "tier_config_parse_error", tier=tier, error=str(exc)
                )

        self.log.info("tier_config_loaded", path=str(config_path))

    def get_tier(self, tier: str) -> TierFeatures:
        """Return TierFeatures for given tier. Falls back to free on unknown tier."""
        return self.TIER_DEFINITIONS.get(tier, self.TIER_DEFINITIONS["free"])

    def check_feature(
        self,
        tier: str,
        feature: str,
        value: str | None = None,
    ) -> FeatureGateResult:
        """
        Check whether a tier allows a feature or feature value.

        List features (pass value=):
            "subject", "curriculum", "language", "difficulty_level"

        Boolean features (value ignored):
            "subtitle_download", "api_access", "human_review", "priority_queue"

        Returns FeatureGateResult — caller decides whether to raise.
        """
        features = self.get_tier(tier)

        _list_gates: dict[str, list[str]] = {
            "subject":           features.allowed_subjects,
            "curriculum":        features.allowed_curricula,
            "language":          features.allowed_languages,
            "difficulty_level":  features.allowed_difficulty_levels,
        }
        _bool_gates: dict[str, bool] = {
            "subtitle_download": features.subtitle_download,
            "api_access":        features.api_access,
            "human_review":      features.human_review,
            "priority_queue":    features.priority_queue,
            "watermark_free":    not features.watermark,
        }

        if feature in _list_gates:
            if value and value not in _list_gates[feature]:
                return FeatureGateResult(
                    allowed=False,
                    reason=(
                        f"'{value}' is not available on the {tier} plan. "
                        f"Available: {', '.join(_list_gates[feature])}"
                    ),
                    upgrade_required=(tier == "free"),
                    suggested_tier="premium" if tier == "free" else None,
                )

        elif feature in _bool_gates:
            if not _bool_gates[feature]:
                return FeatureGateResult(
                    allowed=False,
                    reason=f"'{feature}' is not available on the {tier} plan.",
                    upgrade_required=(tier == "free"),
                    suggested_tier="premium" if tier == "free" else None,
                )

        return FeatureGateResult(
            allowed=True,
            reason=None,
            upgrade_required=False,
            suggested_tier=None,
        )

    def get_max_scenes(self, tier: str) -> int:
        return self.get_tier(tier).max_scenes_per_video

    def get_videos_limit(self, tier: str) -> int:
        return self.get_tier(tier).videos_per_month

    def has_watermark(self, tier: str) -> bool:
        return self.get_tier(tier).watermark


tier_config = TierConfig()
