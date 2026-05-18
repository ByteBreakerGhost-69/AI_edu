# AI_edu
Orchestrator and specialist AI agents platform for educational technology startup.

#Overall Project Structure (Root)
```
edu_video_ai/
├── backend/                      # Python FastAPI + Agents
├── frontend/                     # Next.js Interactive Player
├── infra/                        # Terraform, Docker, K8s
├── scripts/                      # Ingestion, migration, etc.
├── tests/                        # Unit + Integration + E2E
├── docs/                         # Architecture Decision Records
├── .env.example
├── pyproject.toml
├── docker-compose.yml
└── README.md


#backand structure 
```
backend/
├── main.py                       # FastAPI entry point
├── core/                         # Config, DB, Utils
│   ├── config.py
│   ├── database.py               # PostgreSQL + Redis
│   ├── qdrant.py
│   ├── llm.py                    # LLM factory (Claude, Grok, etc.)
│   └── utils.py
│
├── models/                       # Pydantic Schemas (sangat detail)
│   ├── __init__.py
│   ├── job.py
│   ├── scene.py                  # Scene Breakdown JSON Schema
│   ├── user.py
│   └── feedback.py
│
├── layer1_input/                 # Layer 1
│   ├── api_gateway.py
│   ├── vision_parser.py
│   ├── validator.py
│   ├── queue_service.py
│   └── schemas.py
│
├── layer2_orchestrator/          # Layer 2 - Otak Sistem
│   ├── orchestrator.py           # Main LangGraph
│   ├── agents/
│   │   ├── curriculum_agent.py
│   │   ├── memory_agent.py
│   │   ├── fact_checker_agent.py
│   │   ├── script_agent.py
│   │   ├── visual_asset_agent.py
│   │   ├── animation_router.py
│   │   └── base_agent.py         # Base class semua agent
│   └── graph.py                  # LangGraph workflow definition
│
├── layer3_rag/                   # Layer 3
│   ├── query_expander.py
│   ├── retriever.py              # Hybrid Qdrant
│   ├── reranker.py
│   ├── ingestion/
│   │   ├── pipeline.py
│   │   └── chunker.py
│   └── rag_service.py
│
├── layer4_script_visual/         # Layer 4
│   ├── script_generator.py
│   ├── visual_asset_generator.py
│   └── schemas.py                # Scene JSON Schema lengkap
│
├── layer5_rendering/             # Layer 5 - Paling Berat
│   ├── tts_service.py
│   ├── animation_router.py
│   ├── renderers/
│   │   ├── manim_renderer.py
│   │   ├── lottie_renderer.py
│   │   ├── flux_sdxl_renderer.py
│   │   ├── kling_renderer.py
│   │   └── base_renderer.py
│   ├── compositor.py             # FFmpeg / Remotion
│   └── timing_sync.py
│
├── layer6_delivery/              # Layer 6
│   ├── cdn_service.py
│   ├── feedback_service.py
│   ├── partial_regen.py
│   └── analytics.py
│
├── workers/                      # Celery / Temporal workers
│   ├── video_worker.py
│   └── renderer_worker.py
│
├── prompts/                      # Semua prompt terstruktur
│   ├── curriculum/
│   ├── script/
│   ├── visual/
│   ├── fact_checker/
│   └── system/
│
└── utils/
    ├── logging.py
    ├── monitoring.py
    └── cache.py
