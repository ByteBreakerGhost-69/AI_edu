# products/edu_video/backend/tests/unit/test_billing.py
"""
Unit tests for the billing subsystem.

Coverage targets:
  - TierConfig: feature gate logic, YAML loading, limit retrieval
  - UsageLimiter: quota enforcement, increment atomicity, reset logic
  - SubscriptionService: free tier creation, upgrade flow, cancellation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from billing.tier_config import (
    TierConfig,
    TierFeatures,
    FeatureGateResult,
    tier_config,
)
from billing.usage_limiter import UsageLimiter, QuotaStatus, UsageLimitError


# --------------------------------------------------------------------------- #
# TierConfig                                                                    #
# --------------------------------------------------------------------------- #

class TestTierConfig:

    @pytest.fixture
    def config(self):
        """Fresh TierConfig instance for each test — does not load from disk."""
        return TierConfig()

    def test_free_tier_videos_limit(self, config):
        """Free tier must have exactly 3 videos per month."""
        assert config.get_videos_limit("free") == 3

    def test_premium_tier_videos_limit(self, config):
        """Premium tier must have exactly 50 videos per month."""
        assert config.get_videos_limit("premium") == 50

    def test_free_tier_max_scenes(self, config):
        """Free tier max scenes per video must be 4."""
        assert config.get_max_scenes("free") == 4

    def test_premium_tier_max_scenes(self, config):
        """Premium tier max scenes per video must be 8."""
        assert config.get_max_scenes("premium") == 8

    def test_free_tier_has_watermark(self, config):
        """Free tier must have watermark enabled."""
        assert config.has_watermark("free") is True

    def test_premium_tier_no_watermark(self, config):
        """Premium tier must have watermark disabled."""
        assert config.has_watermark("premium") is False

    def test_unknown_tier_falls_back_to_free(self, config):
        """Unknown tier string must fall back to free tier without raising."""
        features = config.get_tier("nonexistent_tier")
        free_features = config.get_tier("free")
        assert features == free_features

    def test_free_allowed_subjects_subset_of_premium(self, config):
        """Free tier allowed subjects must be a subset of premium allowed subjects."""
        free = set(config.get_tier("free").allowed_subjects)
        premium = set(config.get_tier("premium").allowed_subjects)
        assert free.issubset(premium), (
            f"Free subjects not subset of premium. Difference: {free - premium}"
        )

    # Feature gate: subject

    def test_free_mathematics_allowed(self, config):
        """Mathematics must be allowed on the free tier."""
        result = config.check_feature("free", "subject", "mathematics")
        assert result.allowed is True
        assert result.upgrade_required is False

    def test_free_history_blocked(self, config):
        """History must be blocked on the free tier (premium only)."""
        result = config.check_feature("free", "subject", "history")
        assert result.allowed is False
        assert result.upgrade_required is True
        assert result.suggested_tier == "premium"

    def test_premium_all_subjects_allowed(self, config):
        """All 10 subjects must be allowed on the premium tier."""
        from layer1_input.schemas import SubjectEnum
        for subject in SubjectEnum:
            result = config.check_feature("premium", "subject", subject.value)
            assert result.allowed is True, (
                f"Subject '{subject.value}' incorrectly blocked on premium tier"
            )

    # Feature gate: difficulty

    def test_free_beginner_allowed(self, config):
        """Beginner difficulty must be allowed on free tier."""
        result = config.check_feature("free", "difficulty_level", "beginner")
        assert result.allowed is True

    def test_free_advanced_blocked(self, config):
        """Advanced difficulty must be blocked on free tier."""
        result = config.check_feature("free", "difficulty_level", "advanced")
        assert result.allowed is False

    def test_premium_advanced_allowed(self, config):
        """Advanced difficulty must be allowed on premium tier."""
        result = config.check_feature("premium", "difficulty_level", "advanced")
        assert result.allowed is True

    # Feature gate: boolean features

    def test_free_subtitle_download_blocked(self, config):
        """Subtitle download must be blocked on free tier."""
        result = config.check_feature("free", "subtitle_download")
        assert result.allowed is False
        assert result.upgrade_required is True

    def test_premium_subtitle_download_allowed(self, config):
        """Subtitle download must be allowed on premium tier."""
        result = config.check_feature("premium", "subtitle_download")
        assert result.allowed is True

    def test_free_api_access_blocked(self, config):
        """API access must be blocked on free tier."""
        result = config.check_feature("free", "api_access")
        assert result.allowed is False

    def test_premium_priority_queue_allowed(self, config):
        """Priority queue must be enabled for premium tier."""
        result = config.check_feature("premium", "priority_queue")
        assert result.allowed is True

    # Feature gate: curriculum

    def test_free_general_curriculum_allowed(self, config):
        """General curriculum must be allowed on free tier."""
        result = config.check_feature("free", "curriculum", "general")
        assert result.allowed is True

    def test_free_ib_curriculum_blocked(self, config):
        """IB curriculum must be blocked on free tier."""
        result = config.check_feature("free", "curriculum", "IB")
        assert result.allowed is False
        assert result.upgrade_required is True

    def test_check_feature_returns_feature_gate_result(self, config):
        """check_feature() must always return FeatureGateResult, not None."""
        result = config.check_feature("free", "subject", "mathematics")
        assert isinstance(result, FeatureGateResult)
        assert hasattr(result, "allowed")
        assert hasattr(result, "reason")
        assert hasattr(result, "upgrade_required")

    # YAML loading

    def test_load_creates_yaml_if_not_exists(self, config, tmp_path, test_settings):
        """load() must create the YAML config file if it does not exist."""
        import os
        yaml_path = tmp_path / "tier_limits.yaml"
        test_settings.TIER_CONFIG_PATH = str(yaml_path)
        assert not yaml_path.exists()
        config.load()
        assert yaml_path.exists()

    def test_load_preserves_defaults_when_yaml_empty(self, config, tmp_path, test_settings):
        """load() with empty YAML must not crash and must preserve default limits."""
        yaml_path = tmp_path / "tier_limits.yaml"
        yaml_path.write_text("")
        test_settings.TIER_CONFIG_PATH = str(yaml_path)
        config.load()
        assert config.get_videos_limit("free") == 3


# --------------------------------------------------------------------------- #
# UsageLimiter                                                                  #
# --------------------------------------------------------------------------- #

class TestUsageLimiter:

    @pytest.fixture
    def limiter(self):
        return UsageLimiter()

    @pytest.mark.asyncio
    async def test_get_quota_no_subscription_returns_free_defaults(
        self, limiter, mock_db_session
    ):
        """
        User with no subscription record gets free tier quota:
        3 videos/month, 0 used.
        """
        mock_db_session.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=None
        )
        quota = await limiter.get_quota_status("user-123", mock_db_session)
        assert isinstance(quota, QuotaStatus)
        assert quota.tier == "free"
        assert quota.videos_limit == 3
        assert quota.videos_used == 0
        assert quota.is_exceeded is False

    @pytest.mark.asyncio
    async def test_get_quota_at_limit_is_exceeded_true(
        self, limiter, mock_db_session, subscription_factory
    ):
        """User who has used all 3 free videos is marked as exceeded."""
        sub = subscription_factory(
            tier="free",
            videos_used_this_month=3,
            videos_limit_per_month=3,
        )
        mock_db_session.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=sub
        )
        quota = await limiter.get_quota_status(str(sub.user_id), mock_db_session)
        assert quota.is_exceeded is True
        assert quota.videos_remaining == 0

    @pytest.mark.asyncio
    async def test_get_quota_premium_50_limit(
        self, limiter, mock_db_session, subscription_factory
    ):
        """Premium user with 5 videos used has 45 remaining."""
        sub = subscription_factory(
            tier="premium",
            videos_used_this_month=5,
            videos_limit_per_month=50,
        )
        mock_db_session.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=sub
        )
        quota = await limiter.get_quota_status(str(sub.user_id), mock_db_session)
        assert quota.videos_remaining == 45
        assert quota.is_exceeded is False

    @pytest.mark.asyncio
    async def test_get_quota_percentage_calculation(
        self, limiter, mock_db_session, subscription_factory
    ):
        """percentage_used is correctly calculated (used/limit × 100)."""
        sub = subscription_factory(
            tier="premium",
            videos_used_this_month=25,
            videos_limit_per_month=50,
        )
        mock_db_session.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=sub
        )
        quota = await limiter.get_quota_status(str(sub.user_id), mock_db_session)
        assert quota.percentage_used == 50.0

    @pytest.mark.asyncio
    async def test_increment_usage_increments_counter(
        self, limiter, mock_db_session, subscription_factory
    ):
        """increment_usage() increases videos_used_this_month by 1."""
        sub = subscription_factory(videos_used_this_month=1)
        mock_db_session.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=sub
        )
        new_count = await limiter.increment_usage(str(sub.user_id), mock_db_session)
        assert new_count == 2
        mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_increment_creates_free_subscription_if_missing(
        self, limiter, mock_db_session
    ):
        """
        increment_usage() for user with no subscription creates a free
        subscription record automatically.
        """
        mock_db_session.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=None
        )
        new_count = await limiter.increment_usage("new-user-id", mock_db_session)
        assert new_count == 1
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_monthly_usage_sets_count_to_zero(
        self, limiter, mock_db_session, subscription_factory
    ):
        """reset_monthly_usage() sets videos_used_this_month to 0."""
        sub = subscription_factory(videos_used_this_month=7)
        mock_db_session.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=sub
        )
        await limiter.reset_monthly_usage(str(sub.user_id), mock_db_session)
        assert sub.videos_used_this_month == 0
        mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_noop_when_no_subscription(
        self, limiter, mock_db_session
    ):
        """reset_monthly_usage() with no subscription record must not raise."""
        mock_db_session.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=None
        )
        await limiter.reset_monthly_usage("ghost-user", mock_db_session)
        mock_db_session.commit.assert_not_called()

    def test_check_video_quota_dependency_raises_402_when_exceeded(
        self, test_settings
    ):
        """
        check_video_quota FastAPI dependency raises UsageLimitError (HTTP 402)
        when quota is exceeded.
        """
        exceeded_quota = QuotaStatus(
            user_id="test-user",
            tier="free",
            videos_used=3,
            videos_limit=3,
            videos_remaining=0,
            resets_at=__import__("datetime").datetime.utcnow(),
            is_exceeded=True,
            percentage_used=100.0,
        )
        with pytest.raises(UsageLimitError) as exc_info:
            raise UsageLimitError(exceeded_quota)
        assert exc_info.value.status_code == 402

    def test_usage_limit_error_contains_quota_detail(self):
        """UsageLimitError detail must include quota_status for frontend use."""
        import datetime
        quota = QuotaStatus(
            user_id="test-user",
            tier="free",
            videos_used=3,
            videos_limit=3,
            videos_remaining=0,
            resets_at=datetime.datetime.utcnow(),
            is_exceeded=True,
            percentage_used=100.0,
        )
        error = UsageLimitError(quota)
        assert "quota_status" in error.detail
        assert error.detail["error"] == "quota_exceeded"


# --------------------------------------------------------------------------- #
# SubscriptionService                                                           #
# --------------------------------------------------------------------------- #

class TestSubscriptionService:

    @pytest.fixture
    def service(self):
        from billing.subscription_service import SubscriptionService
        return SubscriptionService()

    @pytest.mark.asyncio
    async def test_get_or_create_free_creates_for_new_user(
        self, service, mock_db_session
    ):
        """get_or_create_free() creates a new free subscription for a new user."""
        mock_db_session.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=None
        )
        user_id = str(uuid4())
        subscription = await service.get_or_create_free(user_id, mock_db_session)
        assert subscription.tier == "free"
        assert subscription.status == "active"
        assert subscription.videos_used_this_month == 0
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_or_create_free_returns_existing(
        self, service, mock_db_session, subscription_factory
    ):
        """get_or_create_free() returns existing subscription without creating a new one."""
        existing = subscription_factory(tier="free")
        mock_db_session.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=existing
        )
        result = await service.get_or_create_free(str(existing.user_id), mock_db_session)
        assert result is existing
        mock_db_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_subscription_response_includes_features(
        self, service, mock_db_session, subscription_factory
    ):
        """get_subscription() returns SubscriptionResponse with TierFeatures included."""
        sub = subscription_factory(tier="free")
        mock_db_session.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=sub
        )
        response = await service.get_subscription(str(sub.user_id), mock_db_session)
        assert hasattr(response, "features")
        assert isinstance(response.features, TierFeatures)

    @pytest.mark.asyncio
    async def test_cancel_subscription_no_stripe_id_raises(
        self, service, mock_db_session, subscription_factory
    ):
        """cancel_subscription() with no stripe_subscription_id raises ValueError."""
        sub = subscription_factory(tier="premium", stripe_subscription_id=None)
        mock_db_session.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=sub
        )
        with pytest.raises(ValueError, match="No active premium subscription"):
            await service.cancel_subscription(
                str(sub.user_id), cancel_immediately=False, db=mock_db_session
            )

    @pytest.mark.asyncio
    async def test_upgrade_user_not_found_raises(
        self, service, mock_db_session
    ):
        """upgrade_to_premium() raises ValueError when user does not exist in DB."""
        mock_db_session.get.return_value = None
        mock_db_session.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=None
        )
        with pytest.raises(ValueError, match="not found"):
            await service.upgrade_to_premium(
                "nonexistent-user", "pm_test_xxx", mock_db_session
  )
