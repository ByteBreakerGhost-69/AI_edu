# products/edu_video/backend/layer2_orchestrator/agents/memory_agent.py
"""
MemoryAgent: queries Qdrant for semantically similar completed jobs,
then synthesizes a memory context string to guide ScriptAgent.

Called by: node_query_memory (graph.py)
Depends on: curriculum_standards set by CurriculumAgent (used in query text)

Cost breakdown:
  - Embedding call: ~$0.00002 (text-embedding-3-small, ~100 tokens)
  - LLM synthesis: ~500 tokens ≈ $0.0021 (only if similar jobs found)
  - Qdrant search: free (self-hosted) or per-query on cloud

Failure policy:
  - Qdrant failure   → silent warn, return empty context (non-fatal)
  - Embedding failure → _safe_return (non-fatal, adds to errors)
  - LLM failure      → return similar_jobs without synthesized context (non-fatal)
  Memory is an enhancement, never a blocker.
"""

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from core.qdrant import get_qdrant_client
from layer2_orchestrator.agents.base_agent import BaseAgent
from layer2_orchestrator.graph import GraphState

__all__ = ["MemoryAgent"]

# Qdrant similarity thresholds
_SIMILARITY_THRESHOLD: float = 0.82   # minimum score to include in similar_jobs
_REUSE_THRESHOLD: float = 0.92        # minimum score to suggest asset reuse

# LLM token estimates for memory synthesis
_SYNTH_PROMPT_TOKENS: int = 300
_SYNTH_COMPLETION_TOKENS: int = 200

# Embedding query composition
_INPUT_TEXT_PREVIEW_CHARS: int = 200

# Memory context hard cap — prevents bloating ScriptAgent's prompt
_MAX_MEMORY_CONTEXT_CHARS: int = 600

# Synthesis output hard cap — LLM instruction
_MAX_SYNTHESIS_WORDS: int = 150


class MemoryAgent(BaseAgent):
    """
    Performs semantic search over Qdrant to find similar completed jobs.
    If similar jobs are found above the similarity threshold, synthesizes
    a short memory context string for ScriptAgent to use as creative guidance.

    Reads from GraphState:
        job_id, subject, curriculum, difficulty_level,
        input_text, title, curriculum_standards

    Writes to GraphState:
        similar_jobs     — list[dict]: jobs above similarity threshold
        memory_context   — str: synthesized guidance (empty if no similar jobs)
        reuse_assets     — list[str]: asset URLs from high-similarity jobs
        total_cost_usd   — accumulated via _record_cost (only if LLM called)
        cost_breakdown   — accumulated via _record_cost (only if LLM called)
        current_node     — "node_query_memory"
    """

    @property
    def agent_name(self) -> str:
        return "memory_agent"

    async def run(self, state: GraphState) -> dict:
        job_id = state["job_id"]
        log = self.log.bind(
            job_id=job_id,
            subject=state["subject"],
            curriculum=state["curriculum"],
        )
        log.info("memory_agent.started")

        with self._timer() as t:

            # ---------------------------------------------------------- #
            # Step 1 — Build query vector                                 #
            # ---------------------------------------------------------- #
            query_vector = await self._build_query_vector(state, log)
            if query_vector is None:
                # Embedding failed — _safe_return already logged
                log.warning(
                    "memory_agent.skipped_due_to_embedding_failure",
                    duration_ms=t["elapsed_ms"],
                )
                return self._safe_return(
                    state,
                    error="embedding_failed — memory skipped",
                    defaults=_empty_defaults(),
                )

            # ---------------------------------------------------------- #
            # Step 2 — Search Qdrant                                      #
            # ---------------------------------------------------------- #
            similar_jobs, reuse_assets = await self._search_qdrant(
                query_vector, state, log
            )
            # Qdrant failure returns ([], []) — not a hard error

            # ---------------------------------------------------------- #
            # Step 3 — Synthesize memory context                          #
            # ---------------------------------------------------------- #
            memory_context, tokens_used, cost_usd = await self._synthesize_context(
                similar_jobs, job_id, state, log
            )

            log.info(
                "memory_agent.completed",
                similar_jobs_found=len(similar_jobs),
                reuse_assets_found=len(reuse_assets),
                memory_context_chars=len(memory_context),
                llm_called=bool(similar_jobs),
                duration_ms=t["elapsed_ms"],
            )

            return {
                **_empty_defaults(),
                "similar_jobs": similar_jobs,
                "memory_context": memory_context,
                "reuse_assets": reuse_assets,
                "current_node": "node_query_memory",
                **self._record_cost(job_id, tokens_used, cost_usd, state),
            }

    # ------------------------------------------------------------------ #
    # Step implementations                                                 #
    # ------------------------------------------------------------------ #

    async def _build_query_vector(
        self,
        state: GraphState,
        log,
    ) -> list[float] | None:
        """
        Embed a composite query string that captures subject, curriculum,
        difficulty, and a snippet of the actual topic content.

        Returns None on failure so the caller can short-circuit gracefully.
        """
        # Include curriculum_standards if already populated by CurriculumAgent
        # — richer embedding than subject alone
        standards_fragment = ""
        if state.get("curriculum_standards"):
            standards_fragment = " ".join(state["curriculum_standards"][:3])

        input_preview = (state["input_text"] or state["title"] or "")
        input_preview = input_preview[:_INPUT_TEXT_PREVIEW_CHARS]

        query_text = " ".join(
            filter(None, [
                state["subject"],
                state["curriculum"],
                state["difficulty_level"],
                standards_fragment,
                input_preview,
            ])
        ).strip()

        log.debug("memory_agent.embedding_query", query_preview=query_text[:100])

        try:
            embedding_model = self._get_embedding_model()
            vector = await embedding_model.aembed_query(query_text)
            log.info(
                "memory_agent.embedding_complete",
                vector_dims=len(vector),
            )
            return vector

        except Exception as exc:
            log.error("memory_agent.embedding_failed", error=str(exc))
            return None

    async def _search_qdrant(
        self,
        query_vector: list[float],
        state: GraphState,
        log,
    ) -> tuple[list[dict], list[str]]:
        """
        Search Qdrant for completed jobs matching subject + similarity threshold.

        Returns:
            similar_jobs  — list of job summary dicts above _SIMILARITY_THRESHOLD
            reuse_assets  — list of asset URLs from jobs above _REUSE_THRESHOLD

        On any Qdrant error: logs warning, returns ([], []).
        This is intentional — memory is optional, never a pipeline blocker.
        """
        try:
            qdrant = get_qdrant_client()
            results = await qdrant.search_vectors(
                query_vector=query_vector,
                top_k=3,
                filter_payload={
                    "subject": state["subject"],
                    "status": "done",
                },
            )

            similar_jobs: list[dict] = []
            reuse_assets: list[str] = []

            for hit in results:
                score = round(float(hit.score), 4)

                if score < _SIMILARITY_THRESHOLD:
                    continue

                similar_jobs.append({
                    "job_id": hit.payload.get("job_id"),
                    "title": hit.payload.get("title"),
                    "subject": hit.payload.get("subject"),
                    "curriculum": hit.payload.get("curriculum"),
                    "difficulty_level": hit.payload.get("difficulty_level"),
                    "score": score,
                    "scene_titles": hit.payload.get("scene_titles", []),
                })

                if score >= _REUSE_THRESHOLD:
                    asset_urls = hit.payload.get("asset_urls", [])
                    if asset_urls:
                        reuse_assets.extend(asset_urls)
                        log.info(
                            "memory_agent.reuse_candidate_found",
                            job_id=hit.payload.get("job_id"),
                            score=score,
                            asset_count=len(asset_urls),
                        )

            log.info(
                "memory_agent.qdrant_search_complete",
                total_results=len(results),
                above_threshold=len(similar_jobs),
                reuse_candidates=len(reuse_assets),
            )
            return similar_jobs, reuse_assets

        except Exception as exc:
            # Non-fatal — Qdrant may be unavailable in dev or Phase 1
            log.warning(
                "memory_agent.qdrant_failed",
                error=str(exc),
                note="Continuing without memory context",
            )
            return [], []

    async def _synthesize_context(
        self,
        similar_jobs: list[dict],
        job_id: str,
        state: GraphState,
        log,
    ) -> tuple[str, int, float]:
        """
        Call Claude to synthesize a short memory context string from similar jobs.
        Only called if similar_jobs is non-empty.

        Returns:
            memory_context  — synthesized string (empty on failure or no jobs)
            tokens_used     — int (0 if LLM not called)
            cost_usd        — float (0.0 if LLM not called)
        """
        if not similar_jobs:
            log.info("memory_agent.synthesis_skipped", reason="no_similar_jobs")
            return "", 0, 0.0

        try:
            system_msg = SystemMessage(
                content=(
                    "You are an educational content assistant helping a scriptwriter "
                    "avoid repeating mistakes and reuse effective patterns from past videos.\n\n"
                    f"Summarize what the similar videos below covered, in max {_MAX_SYNTHESIS_WORDS} words. "
                    "Focus on:\n"
                    "1. Topics and angles already covered well (to avoid redundancy)\n"
                    "2. Structural patterns worth reusing (scene order, explanation style)\n"
                    "3. Gaps or weaknesses in past videos (to improve on)\n\n"
                    "Write in plain prose. No JSON. No bullet lists. No headers."
                )
            )
            user_msg = HumanMessage(
                content=(
                    f"Similar completed jobs for subject '{state['subject']}', "
                    f"curriculum '{state['curriculum']}':\n\n"
                    f"{json.dumps(similar_jobs, indent=2)}"
                )
            )

            response = await self.llm_with_fallback.ainvoke([system_msg, user_msg])
            raw_context = str(response.content).strip()

            # Hard cap — prevent memory context from bloating ScriptAgent's prompt
            memory_context = raw_context[:_MAX_MEMORY_CONTEXT_CHARS]
            if len(raw_context) > _MAX_MEMORY_CONTEXT_CHARS:
                log.warning(
                    "memory_agent.context_truncated",
                    original_chars=len(raw_context),
                    cap=_MAX_MEMORY_CONTEXT_CHARS,
                )

            tokens_used = _SYNTH_PROMPT_TOKENS + _SYNTH_COMPLETION_TOKENS
            cost_usd = self._estimate_cost(
                _SYNTH_PROMPT_TOKENS, _SYNTH_COMPLETION_TOKENS
            )

            log.info(
                "memory_agent.synthesis_complete",
                context_chars=len(memory_context),
                tokens=tokens_used,
                cost_usd=cost_usd,
            )
            return memory_context, tokens_used, cost_usd

        except Exception as exc:
            # LLM synthesis failure is non-fatal:
            # ScriptAgent can still use similar_jobs raw data
            log.warning(
                "memory_agent.synthesis_failed",
                error=str(exc),
                note="Returning similar_jobs without synthesized context",
            )
            return "", 0, 0.0

    # ------------------------------------------------------------------ #
    # Dependency injection hook                                            #
    # ------------------------------------------------------------------ #

    def _get_embedding_model(self):
        """
        Isolated so tests can monkeypatch without touching llm_factory globally.

        Note: requires OPENAI_API_KEY in environment.
        For Phase 1 math MVP, consider returning a mock that always returns
        a zero-vector — memory is optional and Qdrant will be empty anyway.
        """
        from core.llm import llm_factory  # noqa: PLC0415
        return llm_factory.get_embedding_model()


# --------------------------------------------------------------------------- #
# Module-level helpers                                                         #
# --------------------------------------------------------------------------- #

def _empty_defaults() -> dict:
    """
    Safe default values for all keys this agent writes.
    Used both in early-return paths and as the base for the success return,
    ensuring no GraphState key is ever left unset by this agent.
    """
    return {
        "similar_jobs": [],
        "memory_context": "",
        "reuse_assets": [],
        "current_node": "node_query_memory",
}
