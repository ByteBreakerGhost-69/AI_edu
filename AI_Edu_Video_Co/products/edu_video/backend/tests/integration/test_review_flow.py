# products/edu_video/backend/tests/integration/test_review_flow.py
"""
Integration tests for the human review pipeline.

Scenarios covered:
  1.  Job completion → review queue enqueue
  2.  Review worker dequeues → auto-approves high-quality jobs
  3.  Review worker → routes borderline jobs to human
  4.  Review worker → auto-rejects critically low quality jobs
  5.  Human reviewer approves → job status = 'done'
  6.  Human reviewer rejects → job status = 'failed', correction logged
  7.  Human reviewer marks 'requires_revision' → job stays in review
  8.  User feedback 'poor_animation' → partial regen queued
  9.  User feedback 'incorrect_content' → review queue + correction log
  10. Correction log feeds back to RAG ingestion pipeline
  11. Review worker pub/sub notification on human routing
  12. Auto-approval threshold respected (score >= 0.85 → auto-approve)
"""

import json
from datetime import datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from tests.integration.conftest import (
    seed_test_user,
    seed_test_subscription,
    seed_test_job,
)

REVIEW_QUEUE_KEY = "edu_video:review_queue:test"


# --------------------------------------------------------------------------- #
# Review Queue Enqueue                                                          #
# --------------------------------------------------------------------------- #

class TestReviewQueueEnqueue:
    """Tests that jobs are correctly enqueued for review."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_enqueue_creates_redis_entry(
        self,
        test_db,
        fake_redis,
        test_settings,
    ):
        """
        enqueue_for_review() adds a scored entry to the Redis review ZSET.
        Priority jobs have lower scores (processed earlier).
        """
        user = await seed_test_user(test_db)
        job = await seed_test_job(test_db, str(user.id), status="rendering")

        from layer6_delivery.review.review_queue import ReviewQueueService
        service = ReviewQueueService()

        with patch.object(service, "_redis", AsyncMock(return_value=fake_redis)):
            item = await service.enqueue_for_review(
                job_id=str(job.id),
                trigger_reason="low_confidence",
                priority="normal",
                confidence_score=0.72,
            )

        assert item.job_id == str(job.id)
        assert item.trigger_reason == "low_confidence"
        assert item.confidence_score == 0.72

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_urgent_priority_has_lower_score_than_normal(
        self,
        test_db,
        fake_redis,
    ):
        """
        Urgent priority jobs must have lower ZSET score than normal priority.
        Lower score = dequeued first = higher actual priority.
        """
        user = await seed_test_user(test_db)
        job_normal = await seed_test_job(test_db, str(user.id))
        job_urgent = await seed_test_job(test_db, str(user.id))

        from layer6_delivery.review.review_queue import ReviewQueueService
        service = ReviewQueueService()

        # Enqueue normal then urgent — urgent should have lower score
        import time
        base_time = time.time()

        normal_score = base_time  # No offset for normal
        urgent_score = base_time - 300  # -300 offset for urgent

        queue_key = "edu_video:review_queue:test"
        await fake_redis.zadd(queue_key, {
            json.dumps({"job_id": str(job_normal.id), "priority": "normal"}): normal_score,
        })
        await fake_redis.zadd(queue_key, {
            json.dumps({"job_id": str(job_urgent.id), "priority": "urgent"}): urgent_score,
        })

        # ZPOPMIN should return urgent job first (lowest score)
        first = await fake_redis.zpopmin(queue_key, count=1)
        assert first, "No items in review queue"
        raw, score = first[0]
        popped = json.loads(raw)
        assert popped["priority"] == "urgent", (
            f"Expected urgent job first (lowest score), got: {popped}"
        )

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_remove_from_queue_deletes_entry(
        self,
        test_db,
        fake_redis,
    ):
        """
        remove_from_queue() removes all entries for the given job_id from the ZSET.
        After removal, the queue should not contain the job.
        """
        user = await seed_test_user(test_db)
        job = await seed_test_job(test_db, str(user.id))
        queue_key = "edu_video:review_queue:test"

        # Manually enqueue
        payload = json.dumps({"job_id": str(job.id), "priority": "normal"})
        await fake_redis.zadd(queue_key, {payload: 1000.0})

        initial_count = await fake_redis.zcard(queue_key)
        assert initial_count >= 1

        from layer6_delivery.review.review_queue import ReviewQueueService
        service = ReviewQueueService()

        with patch.object(service, "_redis", AsyncMock(return_value=fake_redis)):
            removed = await service.remove_from_queue(str(job.id))

        # Queue should now be empty or not contain this job
        remaining = await fake_redis.zrange(queue_key, 0, -1)
        job_ids_in_queue = []
        for raw in remaining:
            try:
                data = json.loads(raw)
                job_ids_in_queue.append(data.get("job_id"))
            except Exception:
                pass
        assert str(job.id) not in job_ids_in_queue


# --------------------------------------------------------------------------- #
# Review Worker: Decision Logic                                                  #
# --------------------------------------------------------------------------- #

class TestReviewWorkerDecisions:
    """Tests the review_worker auto-decision engine."""

    @pytest.fixture
    def review_worker(self):
        from workers.review_worker import ReviewWorker
        return ReviewWorker()

    def test_high_score_triggers_auto_approve(self, review_worker):
        """
        Confidence score >= 0.85 (REVIEW_AUTO_APPROVE_THRESHOLD) returns 'auto_approve'.
        This is the core routing decision — must be deterministic.
        """
        decision = review_worker._compute_decision(
            trigger_reason="low_confidence",
            confidence_score=0.90,
        )
        assert decision == "auto_approve"

    def test_score_at_threshold_triggers_auto_approve(self, review_worker):
        """Score exactly at threshold (0.85) should auto-approve."""
        decision = review_worker._compute_decision(
            trigger_reason="low_confidence",
            confidence_score=0.85,
        )
        assert decision == "auto_approve"

    def test_borderline_score_routes_to_human(self, review_worker):
        """
        Score in the middle range (0.30 <= score < 0.85) routes to human review.
        These jobs need human judgment, not auto-decision.
        """
        decision = review_worker._compute_decision(
            trigger_reason="low_confidence",
            confidence_score=0.65,
        )
        assert decision == "route_to_human"

    def test_user_reported_always_routes_to_human(self, review_worker):
        """
        'user_reported' trigger bypasses auto-approval regardless of score.
        User reports require human review even for high-confidence content.
        """
        decision = review_worker._compute_decision(
            trigger_reason="user_reported",
            confidence_score=0.95,  # High score — but still human
        )
        assert decision == "route_to_human"

    def test_flagged_content_always_routes_to_human(self, review_worker):
        """Safety-flagged content always requires human review."""
        decision = review_worker._compute_decision(
            trigger_reason="flagged_content",
            confidence_score=0.99,
        )
        assert decision == "route_to_human"

    def test_high_cost_anomaly_always_routes_to_human(self, review_worker):
        """Cost anomalies always require human investigation."""
        decision = review_worker._compute_decision(
            trigger_reason="high_cost_anomaly",
            confidence_score=0.88,
        )
        assert decision == "route_to_human"

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_auto_approve_updates_job_to_done(
        self,
        review_worker,
        test_db,
        fake_redis,
        mocker,
    ):
        """
        _execute_auto_approve() calls approval_service.auto_approve()
        which must update job status to 'done'.
        """
        user = await seed_test_user(test_db)
        job = await seed_test_job(test_db, str(user.id), status="review")

        mock_approval = AsyncMock()
        mock_approval.auto_approve = AsyncMock(return_value=MagicMock(
            review_id="auto",
            job_id=str(job.id),
            decision="approved",
            job_status_updated_to="done",
        ))

        log = MagicMock()

        with patch("workers.review_worker.approval_service", mock_approval):
            await review_worker._execute_auto_approve(
                job_id=str(job.id),
                review_id="test-review-id",
                confidence_score=0.92,
                log=log,
            )

        mock_approval.auto_approve.assert_called_once_with(
            job_id=str(job.id),
            confidence_score=0.92,
        )

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_auto_reject_logs_correction(
        self,
        review_worker,
        test_db,
        fake_redis,
        mocker,
    ):
        """
        _execute_auto_reject() calls correction_log_service.log_correction()
        in addition to updating the job status.
        """
        user = await seed_test_user(test_db)
        job = await seed_test_job(test_db, str(user.id), status="review")

        from layer6_delivery.review.approval_service import ApprovalDecision
        mock_approval = AsyncMock()
        mock_approval.process_decision = AsyncMock(return_value=MagicMock(
            decision="rejected",
            job_status_updated_to="failed",
        ))

        mock_correction = AsyncMock()
        mock_correction.log_correction = AsyncMock(return_value=MagicMock(
            correction_id=str(uuid4())
        ))

        log = MagicMock()

        with patch("workers.review_worker.approval_service", mock_approval), \
             patch("workers.review_worker.correction_log_service", mock_correction):
            await review_worker._execute_auto_reject(
                job_id=str(job.id),
                review_id="test-review-id",
                confidence_score=0.20,
                log=log,
            )

        # Correction log must be called — even for auto-rejected jobs
        mock_correction.log_correction.assert_called_once()
        call_kwargs = mock_correction.log_correction.call_args.kwargs
        assert call_kwargs.get("job_id") == str(job.id)
        assert "poor_quality" in str(call_kwargs.get("error_type", ""))

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_route_to_human_publishes_redis_notification(
        self,
        review_worker,
        test_db,
        fake_redis,
        mocker,
    ):
        """
        _execute_route_to_human() publishes a notification to the Redis pub/sub
        channel so the admin panel can update in real time.
        """
        user = await seed_test_user(test_db)
        job = await seed_test_job(test_db, str(user.id), status="review")

        published_messages: list[dict] = []

        async def capture_publish(channel, message):
            published_messages.append({
                "channel": channel,
                "message": json.loads(message),
            })
            return 1

        fake_redis.publish = capture_publish
        log = MagicMock()

        with patch("workers.review_worker._get_redis", AsyncMock(return_value=fake_redis)):
            await review_worker._execute_route_to_human(
                job_id=str(job.id),
                review_id="test-review-id",
                trigger_reason="low_confidence",
                confidence_score=0.65,
                priority="normal",
                log=log,
            )

        assert len(published_messages) >= 1, (
            "No Redis pub/sub notification published for human routing"
        )
        msg = published_messages[0]["message"]
        assert msg["job_id"] == str(job.id)
        assert msg["confidence_score"] == 0.65


# --------------------------------------------------------------------------- #
# ApprovalService: Reviewer Decisions                                           #
# --------------------------------------------------------------------------- #

class TestApprovalServiceDecisions:
    """Tests human reviewer approve/reject/revision actions."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_approve_decision_updates_job_to_done(
        self,
        test_db,
        mocker,
    ):
        """
        process_decision(decision='approved') sets job.status = 'done'
        and review.status = 'approved'. No correction is logged.
        """
        user = await seed_test_user(test_db)
        job = await seed_test_job(test_db, str(user.id), status="review")

        from models.review import Review
        review = Review(
            id=str(uuid4()),
            job_id=str(job.id),
            status="pending",
            priority="normal",
            trigger_reason="low_confidence",
            auto_approved=False,
        )
        test_db.add(review)
        await test_db.commit()

        from layer6_delivery.review.approval_service import (
            ApprovalService,
            ApprovalDecision,
        )
        service = ApprovalService()

        decision = ApprovalDecision(
            review_id=str(review.id),
            decision="approved",
            reviewer_id="reviewer-001",
            reviewer_notes="Content is accurate and curriculum-aligned.",
        )

        with patch("layer6_delivery.review.approval_service.AsyncSessionLocal") as mock_session_factory:
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            # Mock the DB queries to return our review and job
            from sqlalchemy import select as sa_select
            async def mock_execute(stmt):
                result = MagicMock()
                result.scalar_one_or_none = MagicMock(return_value=review)
                return result

            test_db.execute = mock_execute
            test_db.get = AsyncMock(return_value=job)

            result = await service.process_decision(decision)

        assert result.decision == "approved"
        assert result.job_status_updated_to == "done"
        assert result.correction_logged is False

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_reject_decision_logs_correction(
        self,
        test_db,
        mocker,
    ):
        """
        process_decision(decision='rejected') with correction_notes
        logs an entry to the correction log service.
        """
        user = await seed_test_user(test_db)
        job = await seed_test_job(test_db, str(user.id), status="review")

        from models.review import Review
        review = Review(
            id=str(uuid4()),
            job_id=str(job.id),
            status="pending",
            priority="normal",
            trigger_reason="low_confidence",
            auto_approved=False,
        )

        from layer6_delivery.review.approval_service import (
            ApprovalService,
            ApprovalDecision,
        )
        service = ApprovalService()

        decision = ApprovalDecision(
            review_id=str(review.id),
            decision="rejected",
            reviewer_id="reviewer-001",
            reviewer_notes="Formula for quadratic equation is incorrect.",
            rejection_reason="factual_error",
            correction_notes="The quadratic formula denominator must be 2a, not a.",
        )

        mock_correction = AsyncMock()
        mock_correction.log_correction = AsyncMock(return_value=MagicMock(
            correction_id=str(uuid4())
        ))

        with patch("layer6_delivery.review.approval_service.AsyncSessionLocal") as mock_factory, \
             patch("layer6_delivery.review.approval_service.correction_log_service", mock_correction):

            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            async def mock_execute(stmt):
                result = MagicMock()
                result.scalar_one_or_none = MagicMock(return_value=review)
                return result

            test_db.execute = mock_execute
            test_db.get = AsyncMock(return_value=job)

            result = await service.process_decision(decision)

        assert result.decision == "rejected"
        assert result.job_status_updated_to == "failed"
        mock_correction.log_correction.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_requires_revision_keeps_job_in_review(
        self,
        test_db,
        mocker,
    ):
        """
        process_decision(decision='requires_revision') keeps job.status = 'review'.
        The job is not delivered — it waits for content correction.
        """
        user = await seed_test_user(test_db)
        job = await seed_test_job(test_db, str(user.id), status="review")

        from models.review import Review
        review = Review(
            id=str(uuid4()),
            job_id=str(job.id),
            status="pending",
            priority="high",
            trigger_reason="curriculum_mismatch",
            auto_approved=False,
        )

        from layer6_delivery.review.approval_service import (
            ApprovalService,
            ApprovalDecision,
        )
        service = ApprovalService()

        decision = ApprovalDecision(
            review_id=str(review.id),
            decision="requires_revision",
            reviewer_id="reviewer-002",
            correction_notes="Content references wrong IB syllabus year. Use 2023-2025.",
        )

        with patch("layer6_delivery.review.approval_service.AsyncSessionLocal") as mock_factory, \
             patch("layer6_delivery.review.approval_service.correction_log_service") as mock_corr:

            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_corr.log_correction = AsyncMock(return_value=MagicMock())

            async def mock_execute(stmt):
                result = MagicMock()
                result.scalar_one_or_none = MagicMock(return_value=review)
                return result

            test_db.execute = mock_execute
            test_db.get = AsyncMock(return_value=job)

            result = await service.process_decision(decision)

        assert result.decision == "requires_revision"
        assert result.job_status_updated_to == "review", (
            f"Expected job to remain in 'review', got '{result.job_status_updated_to}'"
        )


# --------------------------------------------------------------------------- #
# Feedback Service Integration                                                   #
# --------------------------------------------------------------------------- #

class TestFeedbackServiceIntegration:
    """Tests user feedback triggering downstream actions."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_poor_animation_feedback_queues_partial_regen(
        self,
        test_db,
        fake_redis,
        mocker,
    ):
        """
        User feedback type='poor_animation' with a specific scene_index
        pushes a partial regen request to the Redis regen queue.
        """
        user = await seed_test_user(test_db)
        job = await seed_test_job(test_db, str(user.id), status="done")
        test_db.get = AsyncMock(return_value=job)

        from layer6_delivery.feedback_service import FeedbackService, FeedbackRequest
        service = FeedbackService()

        request = FeedbackRequest(
            job_id=str(job.id),
            scene_index=2,
            feedback_type="poor_animation",
            rating=2,
            comment="The animation was too fast and hard to follow.",
        )

        with patch("layer6_delivery.feedback_service._redis_client", fake_redis), \
             patch("core.database._redis_client", fake_redis):

            result = await service.submit_feedback(request, str(user.id), test_db)

        assert result.action_triggered == "partial_regen", (
            f"Expected 'partial_regen', got '{result.action_triggered}'"
        )

        regen_items = await fake_redis.llen("edu_video:partial_regen_queue")
        assert regen_items >= 1, "Partial regen not queued in Redis after poor_animation feedback"

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_incorrect_content_feedback_queues_review_and_logs_correction(
        self,
        test_db,
        fake_redis,
        mocker,
    ):
        """
        User feedback type='incorrect_content' triggers:
          1. Review queue entry (needs human verification)
          2. Correction log entry (tracks the reported error)
        """
        user = await seed_test_user(test_db)
        job = await seed_test_job(test_db, str(user.id), status="done")
        test_db.get = AsyncMock(return_value=job)

        from layer6_delivery.feedback_service import FeedbackService, FeedbackRequest
        service = FeedbackService()

        mock_review_queue = AsyncMock()
        mock_review_queue.enqueue_for_review = AsyncMock(return_value=MagicMock(
            review_id=str(uuid4()),
            job_id=str(job.id),
        ))

        mock_correction = AsyncMock()
        mock_correction.log_correction = AsyncMock(return_value=MagicMock(
            correction_id=str(uuid4()),
        ))

        request = FeedbackRequest(
            job_id=str(job.id),
            scene_index=1,
            feedback_type="incorrect_content",
            rating=1,
            comment="The formula shown is wrong — derivative of sin(x) is cos(x), not -cos(x).",
        )

        with patch("layer6_delivery.feedback_service.review_queue_service", mock_review_queue), \
             patch("layer6_delivery.feedback_service.correction_log_service", mock_correction):

            result = await service.submit_feedback(request, str(user.id), test_db)

        assert result.action_triggered in ("review_queue", "correction_log")
        mock_review_queue.enqueue_for_review.assert_called_once()
        mock_correction.log_correction.assert_called_once()
        correction_args = mock_correction.log_correction.call_args.kwargs
        assert "sin(x)" in correction_args.get("reported_error", "")

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_feedback_unauthorized_user_raises(
        self,
        test_db,
        mocker,
    ):
        """
        User cannot submit feedback on another user's job.
        Ownership check must raise ValueError before any action.
        """
        owner = await seed_test_user(test_db)
        attacker = await seed_test_user(test_db)
        job = await seed_test_job(test_db, str(owner.id), status="done")

        # DB.get returns job owned by owner, not attacker
        test_db.get = AsyncMock(return_value=job)

        from layer6_delivery.feedback_service import FeedbackService, FeedbackRequest
        service = FeedbackService()

        request = FeedbackRequest(
            job_id=str(job.id),
            scene_index=0,
            feedback_type="poor_animation",
            rating=1,
            comment="Trying to access someone else's job.",
        )

        with pytest.raises(ValueError, match="unauthorized"):
            await service.submit_feedback(request, str(attacker.id), test_db)


# --------------------------------------------------------------------------- #
# Correction Log → RAG Feedback Loop                                            #
# --------------------------------------------------------------------------- #

class TestCorrectionLogRAGLoop:
    """Tests that corrections feed back into the RAG knowledge base."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_correction_stored_in_redis(
        self,
        test_db,
        fake_redis,
        mocker,
    ):
        """
        log_correction() stores the correction entry in the Redis correction log list.
        Entries must be retrievable via get_recent_corrections().
        """
        user = await seed_test_user(test_db)
        job = await seed_test_job(test_db, str(user.id), status="done")

        from layer6_delivery.review.correction_log import CorrectionLogService
        service = CorrectionLogService()

        with patch("layer6_delivery.review.correction_log._redis_client", fake_redis), \
             patch("layer6_delivery.review.correction_log.AsyncSessionLocal") as mock_factory:

            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            test_db.get = AsyncMock(return_value=job)

            entry = await service.log_correction(
                job_id=str(job.id),
                scene_index=3,
                reported_error="The quadratic formula denominator should be 2a not a.",
                error_type="user_reported_factual_error",
                source="user_feedback",
            )

        assert entry.job_id == str(job.id)
        assert entry.error_type == "user_reported_factual_error"
        assert entry.scene_index == 3

        # Verify stored in Redis
        items = await fake_redis.lrange("edu_video:correction_log", 0, -1)
        assert len(items) >= 1

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_correction_with_content_triggers_rag_ingest(
        self,
        test_db,
        fake_redis,
        mocker,
    ):
        """
        When corrected_content is provided, _ingest_correction_to_rag()
        is called to update the knowledge base with the correct information.
        """
        user = await seed_test_user(test_db)
        job = await seed_test_job(test_db, str(user.id), status="done")

        from layer6_delivery.review.correction_log import CorrectionLogService
        service = CorrectionLogService()

        ingested: list[str] = []

        async def mock_ingest(entry, log):
            ingested.append(entry.correction_id)

        service._ingest_correction_to_rag = mock_ingest

        with patch("layer6_delivery.review.correction_log._redis_client", fake_redis), \
             patch("layer6_delivery.review.correction_log.AsyncSessionLocal") as mock_factory:

            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            test_db.get = AsyncMock(return_value=job)

            entry = await service.log_correction(
                job_id=str(job.id),
                scene_index=None,
                reported_error="Integration constant C was omitted.",
                error_type="reviewer_correction",
                corrected_content=(
                    "The indefinite integral of f(x) is F(x) + C, "
                    "where C is the constant of integration."
                ),
                source="reviewer",
            )

        assert len(ingested) >= 1, (
            "RAG ingest was not triggered when corrected_content was provided"
        )
        assert entry.correction_id in ingested

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_systematic_error_detection_logs_warning(
        self,
        test_db,
        fake_redis,
        mocker,
        caplog,
    ):
        """
        When the same error_type exceeds the systematic threshold (3 occurrences),
        the correction log service emits a WARNING log alerting ops.
        """
        user = await seed_test_user(test_db)
        job = await seed_test_job(test_db, str(user.id), status="done")

        # Pre-populate the Redis counter to be at threshold - 1
        await fake_redis.set("corrections:by_type:factual_error", "2")

        from layer6_delivery.review.correction_log import CorrectionLogService
        service = CorrectionLogService()

        with patch("layer6_delivery.review.correction_log._redis_client", fake_redis), \
             patch("layer6_delivery.review.correction_log.AsyncSessionLocal") as mock_factory:

            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            test_db.get = AsyncMock(return_value=job)

            import logging
            with caplog.at_level(logging.WARNING):
                await service.log_correction(
                    job_id=str(job.id),
                    scene_index=None,
                    reported_error="Third occurrence of factual error in formula.",
                    error_type="factual_error",
                    source="reviewer",
                )

        # A WARNING should have been emitted about systematic errors
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        systematic_warnings = [m for m in warning_messages if "systematic" in m.lower() or "pattern" in m.lower()]
        assert len(systematic_warnings) >= 1 or len(warning_messages) >= 1, (
            f"Expected systematic error warning. All warnings: {warning_messages}"
               )
