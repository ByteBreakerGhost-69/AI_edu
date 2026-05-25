# products/edu_video/backend/layer2_orchestrator/orchestrator.py
"""
VideoOrchestrator: job lifecycle manager for the LangGraph pipeline.
Called by video_worker.py after a job is dequeued from Redis.

Owns the full pipeline from "job dequeued" → "scenes written to DB".
Does NOT use FastAPI Depends — opens DB sessions manually.
"""

import asyncio
import time
from datetime import datetime, timezone

import structlog
from pydantic import BaseModel
from sqlalchemy import select

from core.config import get_settings
from core.cost_tracker import CostTracker
from core.database import AsyncSessionLocal
from core.utils import utcnow
from layer2_orchestrator.graph import GraphState, SceneData, build_video_graph
from models.job import Job
from models.scene import Scene

__all__ = [
    "VideoOrchestrator",
    "OrchestratorResult",
    "video_orchestrator",
]

logger = structlog.get_logger(__name__)
settings = get_settings()

_SCENE_COUNT_BY_DIFFICULTY: dict[str, int] = {
    "beginner": 4,
    "intermediate": 6,
    "advanced": 8,
}

_ORCHESTRATION_TIMEOUT_SECONDS = 300  # 5 minutes hard limit


# --- Result model ---

class OrchestratorResult(BaseModel):
    success: bool
    job_id: str
    scene_count: int = 0
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0
    error: str | None = None
    scenes_summary: list[str] = []


# --- Orchestrator ---

class VideoOrchestrator:
    """
    Manages the full job lifecycle from Redis payload to DB-persisted scenes.
    The compiled LangGraph is built once at instantiation and reused for all jobs.
    """

    def __init__(self) -> None:
        self.graph = build_video_graph()
        self.cost_tracker = CostTracker.__new__(CostTracker)  # instantiated without redis; passed per-job
        self.settings = get_settings()
        self.log = structlog.get_logger(__name__)

    async def run(self, job_payload: dict) -> OrchestratorResult:
        """
        Execute the full orchestration pipeline for a single job.

        Args:
            job_payload: Dict dequeued from Redis. Expected keys:
                job_id, user_id, title, subject, curriculum,
                difficulty_level, language, input_text, input_image_url, created_at

        Returns:
            OrchestratorResult with success status, scene count, and cost.
        """
        wall_start = time.perf_counter()
        job_id = str(job_payload.get("job_id", ""))
        log = self.log.bind(job_id=job_id)

        log.info("orchestrator.run_started")

        # ------------------------------------------------------------------ #
        # STEP 1 — Load DB records                                            #
        # ------------------------------------------------------------------ #
        async with AsyncSessionLocal() as session:
            job = await self._get_job(session, job_id)
            if job is None:
                log.error("orchestrator.job_not_found")
                return OrchestratorResult(
                    success=False,
                    job_id=job_id,
                    error="job_not_found",
                )

            job.status = "orchestrating"
            job.updated_at = utcnow()
            await session.commit()
            log.info("orchestrator.job_status_updated", status="orchestrating")

        # ------------------------------------------------------------------ #
        # STEP 2 — Build initial GraphState                                   #
        # ------------------------------------------------------------------ #
        target_scene_count = _SCENE_COUNT_BY_DIFFICULTY.get(
            job_payload.get("difficulty_level", "intermediate"), 6
        )

        initial_state: GraphState = {
            # Input fields
            "job_id": job_id,
            "user_id": str(job_payload.get("user_id", "")),
            "title": str(job_payload.get("title", "")),
            "subject": str(job_payload.get("subject", "mathematics")),
            "curriculum": str(job_payload.get("curriculum", "general")),
            "difficulty_level": str(job_payload.get("difficulty_level", "intermediate")),
            "language": str(job_payload.get("language", "en")),
            "input_text": job_payload.get("input_text") or None,
            "input_image_url": job_payload.get("input_image_url") or None,
            "target_scene_count": target_scene_count,
            # Enrichment fields (empty at start)
            "curriculum_standards": [],
            "learning_objectives": [],
            "prerequisite_concepts": [],
            "subject_profile": {},
            "renderer_preference": [],
            "validation_rules": [],
            "similar_jobs": [],
            "memory_context": "",
            "reuse_assets": [],
            "scenes": [],
            # Fact check
            "fact_check_passed": False,
            "fact_check_issues": [],
            "fact_check_iteration": 0,
            # Animation routing
            "animation_assignments": {},
            # Cost
            "total_cost_usd": 0.0,
            "cost_breakdown": [],
            # Control flow
            "current_node": "start",
            "errors": [],
            "retry_count": 0,
            "pipeline_metadata": {
                "started_at": utcnow().isoformat(),
                "target_scene_count": target_scene_count,
            },
        }

        log.info(
            "orchestrator.graph_state_built",
            target_scene_count=target_scene_count,
            subject=initial_state["subject"],
            curriculum=initial_state["curriculum"],
        )

        # ------------------------------------------------------------------ #
        # STEP 3 — Run LangGraph pipeline                                     #
        # ------------------------------------------------------------------ #
        result_state: GraphState | None = None
        graph_error: str | None = None

        try:
            result_state = await asyncio.wait_for(
                self.graph.ainvoke(
                    initial_state,
                    config={"configurable": {"thread_id": job_id}},
                ),
                timeout=_ORCHESTRATION_TIMEOUT_SECONDS,
            )
            log.info("orchestrator.graph_completed", job_id=job_id)

        except asyncio.TimeoutError:
            graph_error = "Orchestration timeout after 300 seconds."
            log.error("orchestrator.graph_timeout", job_id=job_id)
            await self._update_job_status(job_id, "failed", graph_error)
            return OrchestratorResult(
                success=False,
                job_id=job_id,
                duration_seconds=time.perf_counter() - wall_start,
                error=graph_error,
            )

        except Exception as exc:
            graph_error = str(exc)
            log.error("orchestrator.graph_failed", job_id=job_id, error=graph_error)
            await self._update_job_status(job_id, "failed", graph_error)
            return OrchestratorResult(
                success=False,
                job_id=job_id,
                duration_seconds=time.perf_counter() - wall_start,
                error=graph_error,
            )

        if result_state is None:
            await self._update_job_status(job_id, "failed", "Graph returned no state.")
            return OrchestratorResult(
                success=False,
                job_id=job_id,
                error="graph_returned_no_state",
            )

        # ------------------------------------------------------------------ #
        # STEP 4 — Persist scenes to DB                                       #
        # ------------------------------------------------------------------ #
        scenes_data: list[SceneData] = result_state.get("scenes", [])
        total_cost = float(result_state.get("total_cost_usd", 0.0))
        scenes_summary: list[str] = []

        async with AsyncSessionLocal() as session:
            try:
                # Re-load job in this session
                job = await self._get_job(session, job_id)
                if job is None:
                    log.error("orchestrator.job_disappeared_before_scene_write")
                    return OrchestratorResult(
                        success=False,
                        job_id=job_id,
                        error="job_not_found_on_scene_write",
                    )

                # Insert all scenes
                for scene_data in scenes_data:
                    scene = Scene(
                        job_id=job.id,
                        scene_index=scene_data["scene_index"],
                        title=scene_data.get("title"),
                        narration_text=scene_data["narration_text"],
                        visual_description=scene_data.get("visual_description"),
                        renderer_type=scene_data.get("renderer_type", "lottie"),
                        duration_seconds=scene_data.get("duration_seconds"),
                        render_metadata=scene_data.get("render_metadata", {}),
                        llm_cost_usd=scene_data.get("llm_cost_usd", 0.0),
                        render_cost_usd=0.0,  # set later by renderer worker
                        status="pending",
                        created_at=utcnow(),
                        updated_at=utcnow(),
                    )
                    session.add(scene)
                    scenes_summary.append(scene_data.get("title") or f"Scene {scene_data['scene_index']}")

                # Update job
                job.status = "rendering"
                job.total_cost_usd = total_cost  # type: ignore[assignment]
                job.updated_at = utcnow()
                job.metadata = {  # type: ignore[assignment]
                    **(job.metadata or {}),
                    "orchestration_errors": result_state.get("errors", []),
                    "pipeline_metadata": result_state.get("pipeline_metadata", {}),
                    "fact_check_passed": result_state.get("fact_check_passed", False),
                    "cost_breakdown": result_state.get("cost_breakdown", []),
                }

                await session.commit()
                log.info(
                    "orchestrator.scenes_persisted",
                    scene_count=len(scenes_data),
                    total_cost_usd=total_cost,
                )

            except Exception as exc:
                await session.rollback()
                log.error("orchestrator.scene_persist_failed", error=str(exc))
                await self._update_job_status(job_id, "failed", f"Scene persist error: {exc}")
                return OrchestratorResult(
                    success=False,
                    job_id=job_id,
                    error=f"scene_persist_failed: {exc}",
                    duration_seconds=time.perf_counter() - wall_start,
                )

        # ------------------------------------------------------------------ #
        # STEP 5 — Update Redis job status                                    #
        # ------------------------------------------------------------------ #
        await self._update_redis_status(job_id, "rendering")

        # ------------------------------------------------------------------ #
        # STEP 6 — Return result                                              #
        # ------------------------------------------------------------------ #
        duration = time.perf_counter() - wall_start
        log.info(
            "orchestrator.run_complete",
            success=True,
            scene_count=len(scenes_data),
            total_cost_usd=total_cost,
            duration_seconds=round(duration, 2),
            fact_check_passed=result_state.get("fact_check_passed", False),
            pipeline_errors=len(result_state.get("errors", [])),
        )

        return OrchestratorResult(
            success=True,
            job_id=job_id,
            scene_count=len(scenes_data),
            total_cost_usd=total_cost,
            duration_seconds=round(duration, 2),
            scenes_summary=scenes_summary,
        )

    # ---------------------------------------------------------------------- #
    # Helper methods                                                          #
    # ---------------------------------------------------------------------- #

    async def _get_job(self, session, job_id: str) -> Job | None:
        """Fetch Job by string UUID. Returns None if not found."""
        try:
            result = await session.execute(
                select(Job).where(Job.id == job_id)
            )
            return result.scalar_one_or_none()
        except Exception as exc:
            self.log.error("orchestrator.db_fetch_failed", job_id=job_id, error=str(exc))
            return None

    async def _update_job_status(
        self,
        job_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        """
        Open a fresh DB session to update job status.
        Used in error paths where the main session may be closed or rolled back.
        """
        try:
            async with AsyncSessionLocal() as session:
                job = await self._get_job(session, job_id)
                if job is None:
                    return
                job.status = status
                job.updated_at = utcnow()
                if error:
                    job.error_message = error[:2000]  # cap error string length
                await session.commit()
                self.log.info(
                    "orchestrator.job_status_updated",
                    job_id=job_id,
                    status=status,
                )
        except Exception as exc:
            self.log.error(
                "orchestrator.status_update_failed",
                job_id=job_id,
                error=str(exc),
            )

    async def _update_redis_status(self, job_id: str, status: str) -> None:
        """
        Update the job's Redis hash with current status.
        Non-fatal: logs on failure but does not raise.
        """
        try:
            from core.database import _redis_client  # noqa: PLC0415

            if _redis_client is None:
                return

            key = f"edu_video:job:{job_id}"
            await _redis_client.hset(
                key,
                mapping={
                    "status": status,
                    "updated_at": utcnow().isoformat(),
                },
            )
            self.log.info(
                "orchestrator.redis_status_updated",
                job_id=job_id,
                status=status,
            )
        except Exception as exc:
            self.log.warning(
                "orchestrator.redis_update_failed",
                job_id=job_id,
                error=str(exc),
            )


video_orchestrator = VideoOrchestrator()
