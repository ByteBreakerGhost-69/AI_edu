# AI_edu
Orchestrator and specialist AI agents platform for educational technology startup.

# Overall Project Structure (Root)
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
```

# backand structure 
```
backend/
├── main.py                       # FastAPI entry point
├── core/                         # Config, DB, Utils
│   ├── __init__.py
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
```
# frontand structure 
```
frontend/
├── src/
│   ├── app/                          # Next.js App Router
│   │   ├── (landing)/                # Landing pages & dashboard
│   │   │   ├── page.tsx
│   │   │   └── layout.tsx
│   │   ├── (studio)/                 # Studio Editor (protected route)
│   │   │   ├── studio/
│   │   │   │   └── [project_id]/
│   │   │   │       ├── page.tsx          # Main Studio Editor
│   │   │   │       └── loading.tsx
│   │   │   ├── layout.tsx                # Studio Layout (sidebar + header)
│   │   │   └── error.tsx
│   │   ├── favicon.ico
│   │   ├── globals.css
│   │   └── layout.tsx                    # Root layout (providers)
│   │
│   ├── features/                         # ← NEW: Feature Slicing (Paling penting)
│   │   └── studio/
│   │       ├── player/
│   │       │   ├── video-player.tsx
│   │       │   ├── quiz-overlay.tsx
│   │       │   └── index.ts
│   │       ├── timeline/
│   │       │   ├── timeline.tsx
│   │       │   ├── track.tsx
│   │       │   ├── playhead.tsx
│   │       │   └── hooks/
│   │       ├── script-editor/
│   │       │   ├── script-sidebar.tsx
│   │       │   └── script-editor.tsx
│   │       ├── asset-manager/
│   │       │   ├── asset-panel.tsx
│   │       │   └── visual-bible.tsx
│   │       ├── scene-inspector/
│   │       │   └── scene-inspector.tsx
│   │       ├── thumbnails/
│   │       │   └── scene-thumbnails.tsx
│   │       ├── feedback/
│   │       │   ├── feedback-modal.tsx
│   │       │   └── feedback-form.tsx
│   │       └── export/
│   │           └── export-modal.tsx
│   │
│   ├── components/
│   │   ├── ui/                           # Shadcn/ui components
│   │   │   ├── button.tsx
│   │   │   ├── dialog.tsx
│   │   │   ├── dropdown-menu.tsx
│   │   │   ├── slider.tsx
│   │   │   └── ... 
│   │   ├── common/                       # Generic components
│   │   │   ├── loading-spinner.tsx
│   │   │   ├── error-toast.tsx
│   │   │   └── confirm-dialog.tsx
│   │   └── layout/                       # Layout components
│   │       ├── sidebar.tsx
│   │       ├── header.tsx
│   │       └── studio-layout.tsx
│   │
│   ├── providers/                        # ← NEW
│   │   ├── studio-provider.tsx
│   │   ├── query-provider.tsx            # TanStack Query
│   │   ├── websocket-provider.tsx
│   │   ├── theme-provider.tsx
│   │   └── index.tsx                     # Export semua providers
│   │
│   ├── hooks/                            # Custom Hooks
│   │   ├── use-websocket.ts
│   │   ├── use-video-player.ts
│   │   ├── use-project-data.ts
│   │   ├── use-auto-save.ts
│   │   ├── use-hotkeys.ts
│   │   ├── use-tanstack.ts               # Custom query hooks
│   │   └── use-render-progress.ts
│   │
│   ├── store/                            # Zustand Stores (diperkecil)
│   │   ├── use-studio-store.ts
│   │   ├── use-project-store.ts
│   │   ├── use-render-store.ts
│   │   └── index.ts
│   │
│   ├── services/                         # High-level service
│   │   ├── project-service.ts
│   │   ├── render-service.ts
│   │   └── feedback-service.ts
│   │
│   ├── lib/                              # Utilities & Config
│   │   ├── api/                          # ← NEW
│   │   │   ├── client.ts                 # Axios instance
│   │   │   ├── project-api.ts
│   │   │   ├── render-api.ts
│   │   │   └── feedback-api.ts
│   │   ├── video/                        # ← NEW
│   │   │   ├── timecode.ts
│   │   │   ├── hls-utils.ts
│   │   │   └── subtitle-utils.ts
│   │   ├── validators/                   # ← NEW
│   │   │   └── index.ts                  # Zod schemas
│   │   ├── utils.ts                      # cn(), debounce, formatTime, etc.
│   │   ├── constants.ts
│   │   └── markdown.ts
│   │
│   ├── types/                            # TypeScript Definitions
│   │   ├── project.ts
│   │   ├── scene.ts
│   │   ├── render.ts
│   │   ├── feedback.ts
│   │   └── index.ts
│   │
│   ├── contexts/                         # ← NEW (jika diperlukan)
│   │
│   ├── __tests__/                        # ← NEW: Testing
│   │   ├── features/
│   │   ├── components/
│   │   └── hooks/
│   │
│   ├── middleware/                       # ← NEW (dipisah)
│   │   └── auth.ts
│   │
│   └── styles/                           # Custom CSS
│       └── timeline.css
│
├── public/                               # Static files
│   ├── fonts/
│   ├── icons/
│   ├── placeholders/
│   └── videos/
│
├── .env.local
├── .eslintrc.json
├── .prettierrc
├── components.json
├── next.config.js
├── package.json
├── postcss.config.js
├── tailwind.config.js
└── tsconfig.json
```
# structure startup nanti 

```
AI_Edu_Video_Co/
├── products/
│   └── edu_video/
│       ├── backend/
│       │   ├── main.py                          # FastAPI entrypoint
│       │   ├── pyproject.toml
│       │   ├── Dockerfile
│       │   │
│       │   ├── core/
│       │   │   ├── config.py
│       │   │   ├── database.py                  # PostgreSQL + Redis
│       │   │   ├── qdrant.py
│       │   │   ├── llm.py                       # LLM factory: Claude, Grok, dll
│       │   │   ├── auth.py                      # ← BARU WAJIB: JWT + middleware
│       │   │   ├── cost_tracker.py              # ← BARU WAJIB: track cost per job/user
│       │   │   └── utils.py
│       │   │
│       │   ├── models/
│       │   │   ├── job.py
│       │   │   ├── scene.py
│       │   │   ├── user.py
│       │   │   └── feedback.py
│       │   │
│       │   ├── layer1_input/
│       │   │   ├── api_gateway.py
│       │   │   ├── vision_parser.py
│       │   │   ├── validator.py
│       │   │   ├── queue_service.py
│       │   │   └── schemas.py
│       │   │
│       │   ├── layer2_orchestrator/
│       │   │   ├── orchestrator.py              # LangGraph main
│       │   │   ├── graph.py                     # Workflow definition
│       │   │   └── agents/
│       │   │       ├── base_agent.py
│       │   │       ├── curriculum_agent.py
│       │   │       ├── memory_agent.py
│       │   │       ├── fact_checker_agent.py
│       │   │       ├── script_agent.py
│       │   │       ├── visual_asset_agent.py
│       │   │       └── animation_router.py
│       │   │
│       │   ├── layer3_rag/
│       │   │   ├── rag_service.py
│       │   │   ├── query_expander.py
│       │   │   ├── retriever.py                 # Hybrid Qdrant
│       │   │   ├── reranker.py
│       │   │   └── ingestion/
│       │   │       ├── pipeline.py
│       │   │       └── chunker.py
│       │   │
│       │   ├── layer4_script_visual/
│       │   │   ├── script_generator.py
│       │   │   ├── visual_asset_generator.py
│       │   │   └── schemas.py                   # Scene JSON schema
│       │   │
│       │   ├── layer5_rendering/
│       │   │   ├── tts_service.py
│       │   │   ├── animation_router.py
│       │   │   ├── compositor.py                # FFmpeg / Remotion
│       │   │   ├── timing_sync.py
│       │   │   └── renderers/
│       │   │       ├── base_renderer.py
│       │   │       ├── manim_renderer.py
│       │   │       ├── lottie_renderer.py
│       │   │       ├── flux_sdxl_renderer.py
│       │   │       └── kling_renderer.py
│       │   │
│       │   ├── layer6_delivery/
│       │   │   ├── cdn_service.py
│       │   │   ├── feedback_service.py
│       │   │   ├── partial_regen.py
│       │   │   └── analytics.py
│       │   │
│       │   ├── workers/
│       │   │   ├── video_worker.py
│       │   │   └── renderer_worker.py
│       │   │
│       │   ├── prompts/                         # Product-specific prompts
│       │   │   ├── curriculum/
│       │   │   ├── script/
│       │   │   ├── visual/
│       │   │   ├── fact_checker/
│       │   │   └── system/
│       │   │
│       │   ├── utils/
│       │   │   ├── logging.py
│       │   │   ├── monitoring.py
│       │   │   └── cache.py
│       │   │
│       │   └── tests/
│       │       ├── unit/
│       │       └── integration/
│       │
│       └── frontend/
│           ├── package.json
│           ├── next.config.js
│           ├── tailwind.config.js
│           ├── tsconfig.json
│           ├── components.json
│           ├── .env.local
│           ├── Dockerfile
│           │
│           └── src/
│               ├── app/                         # Next.js App Router
│               │   ├── (landing)/
│               │   │   ├── page.tsx
│               │   │   └── layout.tsx
│               │   ├── (auth)/                  # ← BARU: login, register, reset
│               │   │   ├── login/
│               │   │   │   └── page.tsx
│               │   │   ├── register/
│               │   │   │   └── page.tsx
│               │   │   └── layout.tsx
│               │   ├── (dashboard)/             # ← BARU: project list, usage, billing
│               │   │   ├── dashboard/
│               │   │   │   └── page.tsx
│               │   │   ├── projects/
│               │   │   │   └── page.tsx
│               │   │   ├── billing/             # ← BARU WAJIB
│               │   │   │   └── page.tsx
│               │   │   └── layout.tsx
│               │   ├── (studio)/
│               │   │   ├── studio/
│               │   │   │   └── [project_id]/
│               │   │   │       ├── page.tsx
│               │   │   │       └── loading.tsx
│               │   │   ├── layout.tsx
│               │   │   └── error.tsx
│               │   ├── globals.css
│               │   ├── favicon.ico
│               │   └── layout.tsx
│               │
│               ├── features/
│               │   └── studio/
│               │       ├── player/
│               │       │   ├── video-player.tsx
│               │       │   ├── quiz-overlay.tsx
│               │       │   └── index.ts
│               │       ├── timeline/
│               │       │   ├── timeline.tsx
│               │       │   ├── track.tsx
│               │       │   ├── playhead.tsx
│               │       │   └── hooks/
│               │       ├── script-editor/
│               │       │   ├── script-sidebar.tsx
│               │       │   └── script-editor.tsx
│               │       ├── asset-manager/
│               │       │   ├── asset-panel.tsx
│               │       │   └── visual-bible.tsx
│               │       ├── scene-inspector/
│               │       │   └── scene-inspector.tsx
│               │       ├── thumbnails/
│               │       │   └── scene-thumbnails.tsx
│               │       ├── feedback/
│               │       │   ├── feedback-modal.tsx
│               │       │   └── feedback-form.tsx
│               │       └── export/
│               │           └── export-modal.tsx
│               │
│               ├── components/
│               │   ├── ui/                      # Shadcn/ui components
│               │   │   ├── button.tsx
│               │   │   ├── dialog.tsx
│               │   │   ├── dropdown-menu.tsx
│               │   │   ├── slider.tsx
│               │   │   └── ...
│               │   ├── common/
│               │   │   ├── loading-spinner.tsx
│               │   │   ├── error-toast.tsx
│               │   │   └── confirm-dialog.tsx
│               │   └── layout/
│               │       ├── sidebar.tsx
│               │       ├── header.tsx
│               │       └── studio-layout.tsx
│               │
│               ├── providers/
│               │   ├── studio-provider.tsx
│               │   ├── query-provider.tsx       # TanStack Query
│               │   ├── websocket-provider.tsx
│               │   ├── theme-provider.tsx
│               │   └── index.tsx
│               │
│               ├── hooks/
│               │   ├── use-websocket.ts
│               │   ├── use-video-player.ts
│               │   ├── use-project-data.ts
│               │   ├── use-auto-save.ts
│               │   ├── use-hotkeys.ts
│               │   └── use-render-progress.ts
│               │
│               ├── store/                       # Zustand
│               │   ├── use-studio-store.ts
│               │   ├── use-project-store.ts
│               │   ├── use-render-store.ts
│               │   └── index.ts
│               │
│               ├── services/
│               │   ├── project-service.ts
│               │   ├── render-service.ts
│               │   └── feedback-service.ts
│               │
│               ├── lib/
│               │   ├── api/
│               │   │   ├── client.ts            # Axios instance
│               │   │   ├── project-api.ts
│               │   │   ├── render-api.ts
│               │   │   └── feedback-api.ts
│               │   ├── video/
│               │   │   ├── timecode.ts
│               │   │   ├── hls-utils.ts
│               │   │   └── subtitle-utils.ts
│               │   ├── validators/              # Zod schemas
│               │   │   └── index.ts
│               │   ├── utils.ts
│               │   ├── constants.ts
│               │   └── markdown.ts
│               │
│               ├── types/
│               │   ├── project.ts
│               │   ├── scene.ts
│               │   ├── render.ts
│               │   ├── feedback.ts
│               │   └── index.ts
│               │
│               ├── middleware/
│               │   └── auth.ts
│               │
│               ├── styles/
│               │   └── timeline.css
│               │
│               └── __tests__/
│                   ├── features/
│                   ├── components/
│                   └── hooks/
│
├── core/                                        # Shared infra lintas produk
│   ├── orchestrator/
│   │   ├── meta_orchestrator.py
│   │   └── task_router.py                       # ← BARU: routing task ke agent/layer
│   │
│   ├── memory/
│   │   ├── long_term.py
│   │   ├── short_term.py
│   │   └── access_control.py
│   │
│   ├── controllers/
│   │   ├── cost_controller.py
│   │   └── resource_manager.py
│   │
│   ├── agent_lifecycle.py                       # ← BARU WAJIB: spawn, monitor, kill
│   ├── event_bus.py
│   └── rate_limiter.py
│
├── agents/                                      # ← FROZEN: aktifkan saat produk stabil
│   ├── executive/
│   ├── research/
│   ├── engineering/
│   ├── product/
│   ├── operations/
│   ├── growth/
│   └── lobby/
│
├── shared/                                      # Satu sumber kebenaran
│   ├── prompts/
│   │   └── company/                             # Company-level prompts (frozen)
│   │
│   ├── schemas/                                 # ← BARU WAJIB: shared data contracts
│   │   ├── scene_schema.py                      # Pydantic → auto-generate ke TS
│   │   ├── job_schema.py
│   │   └── agent_schema.py
│   │
│   ├── tools/
│   │   ├── web_search.py
│   │   ├── code_executor.py
│   │   ├── video_tools.py
│   │   └── image_generator.py
│   │
│   ├── knowledge_base/
│   ├── vector_db/
│   └── assets/
│
├── infra/
│   ├── docker/
│   │   ├── backend.Dockerfile
│   │   ├── frontend.Dockerfile
│   │   └── worker.Dockerfile
│   ├── nginx/
│   │   └── nginx.conf
│   ├── cloud/
│   │   ├── gcp_storage.tf
│   │   └── cloud_run.tf
│   └── ci/
│       ├── github_actions.yml
│       └── deploy.sh
│
├── config/
│   ├── environment.py
│   ├── token_budget.yaml
│   ├── agent_personalities.yaml                 # frozen dulu
│   ├── floor_config.yaml                        # frozen dulu
│   └── secrets.yaml                             # .gitignore wajib
│
├── logs/
│   ├── activity.log
│   ├── decisions.log
│   ├── cost_tracking.log
│   └── errors.log
│
├── tests/                                       # E2E & integration lintas produk
│   ├── e2e/
│   └── integration/
│
├── scripts/
│   ├── deploy.sh
│   ├── backup.sh
│   ├── seed_db.py                               # ← BARU: seed data awal
│   ├── generate_types.py                        # ← BARU: Pydantic → TypeScript
│   └── spawn_agents.py                          # frozen dulu
│
├── docker-compose.yml                           # Di root, start semua service sekaligus
├── Makefile                                     # ← BARU: make dev, make deploy, dll
├── .env
├── .gitignore
└── README.md

