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
│   │   ├── (landing)/                # Group landing pages (tanpa layout studio)
│   │   │   ├── page.tsx                  # Landing page / Dashboard project
│   │   │   └── layout.tsx                # Layout khusus landing (navbar hero)
│   │   ├── (studio)/                 # Group studio editor (dengan layout studio)
│   │   │   ├── studio/
│   │   │   │   └── [project_id]/
│   │   │   │       ├── page.tsx          # Main editor studio
│   │   │   │       └── loading.tsx       # Loading skeleton saat load project
│   │   │   ├── layout.tsx                # Layout studio (sidebar, header)
│   │   │   └── error.tsx                 # Error boundary untuk studio
│   │   │
│   │   ├── favicon.ico
│   │   ├── globals.css               # Tailwind + CSS variables
│   │   └── layout.tsx                # Root layout (provider wrapper)
│   │
│   ├── components/                   # Komponen reusable
│   │   ├── studio/                   # Komponen khusus studio editor
│   │   │   ├── canvas-player.tsx         # Canvas player + quiz overlay
│   │   │   ├── timeline.tsx              # Timeline tracks & playhead
│   │   │   ├── script-sidebar.tsx        # Script editor (Markdown + prompt)
│   │   │   ├── asset-panel.tsx           # Visual bible adjustments
│   │   │   ├── scene-thumbnails.tsx      # Thumbnail strip untuk navigasi cepat
│   │   │   ├── export-modal.tsx          # Modal export video / render ulang
│   │   │   └── render-progress.tsx       # Progress bar render realtime
│   │   ├── ui/                       # Base UI (Shadcn/ui)
│   │   │   ├── button.tsx
│   │   │   ├── input.tsx
│   │   │   ├── slider.tsx
│   │   │   ├── dialog.tsx
│   │   │   ├── dropdown-menu.tsx
│   │   │   └── ... (komponen shadcn lainnya)
│   │   ├── layout/                   # Layout wrapper
│   │   │   ├── sidebar.tsx               # Sidebar navigasi studio
│   │   │   ├── header.tsx                # Top bar (project title, save, share)
│   │   │   └── provider.tsx              # Gabungan semua provider (Theme, Zustand, WS)
│   │   └── common/                   # Komponen umum
│   │       ├── loading-spinner.tsx
│   │       ├── error-toast.tsx
│   │       └── confirm-dialog.tsx
│   │
│   ├── hooks/                        # Custom React Hooks
│   │   ├── use-websocket.ts              # WebSocket connection (status render, scene update)
│   │   ├── use-video-player.ts           # Play, pause, seek, gapless antar scene
│   │   ├── use-project-data.ts           # Fetch project & subscribe ke store
│   │   ├── use-auto-save.ts              # Auto save script / visual bible ke backend
│   │   └── use-hotkeys.ts                # Shortcuts keyboard (space, arrow keys)
│   │
│   ├── store/                        # Zustand stores (state management)
│   │   ├── use-studio-store.ts           # State global studio (current timestamp, selected scene, playhead)
│   │   ├── use-project-store.ts          # Project metadata, script, visual bible, scenes
│   │   ├── use-render-store.ts           # Render status, progress, error, output URL   
│   │
│   ├── services/                     # Layer komunikasi dengan backend
│   │   ├── api-client.ts                 # Axios instance dengan interceptor (auth, refresh)
│   │   ├── project-service.ts            # CRUD project, upload input, get scenes
│   │   ├── render-service.ts             # Trigger render, get status, cancel render
│   │   └── feedback-service.ts           # Submit feedback, partial regen request
│   │
│   ├── types/                        # TypeScript interfaces (cocok dengan Pydantic backend)
│   │   ├── project.ts                    # Project, Scene, Script, VisualAsset
│   │   ├── feedback.ts                   # Feedback, RegenerationRequest
│   │   ├── render.ts                     # RenderJob, RenderStatus, OutputVideo
│   │   └── index.ts                      # Export semua
│   │
│   ├── lib/                          # Utility & konfigurasi
│   │   ├── utils.ts                     # cn(), formatTime, debounce, dll
│   │   ├── constants.ts                 # API_BASE_URL, WS_URL, DEFAULT_SCENE_COUNT
│   │   └── markdown.ts                  # Markdown parser untuk script sidebar
│   │
│   ├── styles/                       # Styling tambahan
│   │   └── timeline.css                  # Custom styling untuk timeline (jika perlu override)
│   │
│   └── middleware.ts                 # Next.js middleware (auth, redirect, logging)
│
├── public/                           # Static assets
│   ├── fonts/
│   ├── icons/
│   ├── placeholders/
│   └── videos/                       # (optional) video contoh
│
├── .env.local                        # Environment variables lokal (NEXT_PUBLIC_API_URL, NEXT_PUBLIC_WS_URL)
├── .eslintrc.json
├── .prettierrc
├── components.json                   # Konfigurasi Shadcn/ui
├── next.config.js
├── package.json
├── postcss.config.js
├── tailwind.config.js
└── tsconfig.json
