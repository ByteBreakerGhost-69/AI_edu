# AI_edu
Orchestrator and specialist AI agents platform for educational technology startup.

# structure startup nanti 

```
AI_Edu_Video_Co/
├── products/
│   └── edu_video/
│       ├── backend/
│       │   ├── main.py                                      # FastAPI entrypoint
│       │   ├── pyproject.toml
│       │   ├── Dockerfile
│       │   │
│       │   ├── core/
│       │   │   ├── config.py
│       │   │   ├── database.py                              # PostgreSQL + Redis
│       │   │   ├── qdrant.py
│       │   │   ├── llm.py                                   # LLM factory: Claude, Grok, dll
│       │   │   ├── auth.py                                  # JWT + middleware
│       │   │   ├── cost_tracker.py                          # Track cost per job/user
│       │   │   └── utils.py
│       │   │
│       │   ├── models/
│       │   │   ├── job.py
│       │   │   ├── scene.py
│       │   │   ├── user.py
│       │   │   ├── feedback.py
│       │   │   ├── subscription.py                          # ← BARU: free/premium tier model
│       │   │   ├── invoice.py                               # ← BARU: billing record
│       │   │   └── review.py                                # ← BARU: human review record
│       │   │
│       │   ├── layer1_input/
│       │   │   ├── api_gateway.py
│       │   │   ├── vision_parser.py
│       │   │   ├── validator.py
│       │   │   ├── queue_service.py
│       │   │   ├── subject_detector.py                      # ← BARU: deteksi mapel dari input
│       │   │   ├── curriculum_selector.py                   # ← BARU: pilih kurikulum (IB/Cambridge/AP)
│       │   │   └── schemas.py
│       │   │
│       │   ├── layer2_orchestrator/
│       │   │   ├── orchestrator.py                          # LangGraph main
│       │   │   ├── graph.py                                 # Workflow definition
│       │   │   └── agents/
│       │   │       ├── base_agent.py
│       │   │       ├── curriculum_agent.py
│       │   │       ├── memory_agent.py
│       │   │       ├── fact_checker_agent.py
│       │   │       ├── script_agent.py
│       │   │       ├── visual_asset_agent.py
│       │   │       ├── animation_router.py
│       │   │       ├── subject_router.py                    # ← BARU: routing berdasarkan mapel
│       │   │       └── subject_profiles/                    # ← BARU: profil per mapel
│       │   │           ├── base_profile.py
│       │   │           ├── mathematics_profile.py           # renderer: Manim, validator: equation
│       │   │           ├── physics_profile.py               # renderer: diagram, validator: formula
│       │   │           ├── chemistry_profile.py             # renderer: molekul, validator: reaksi
│       │   │           ├── biology_profile.py               # renderer: ilustrasi, validator: taksonomi
│       │   │           ├── history_profile.py               # renderer: timeline, validator: fact DB
│       │   │           ├── geography_profile.py             # renderer: peta, validator: data geografis
│       │   │           ├── economics_profile.py             # renderer: grafik, validator: data ekonomi
│       │   │           ├── literature_profile.py            # renderer: text-heavy, validator: grammar
│       │   │           ├── computer_science_profile.py      # renderer: code, validator: logic
│       │   │           ├── language_profile.py              # renderer: dialog, validator: grammar
│       │   │           └── init.py
│       │   │
│       │   ├── layer3_rag/
│       │   │   ├── rag_service.py
│       │   │   ├── query_expander.py
│       │   │   ├── retriever.py                             # Hybrid Qdrant
│       │   │   ├── reranker.py
│       │   │   ├── curriculum_filter.py                     # ← BARU: filter RAG per kurikulum
│       │   │   ├── validators/                              # ← BARU: validator per domain
│       │   │   │   ├── base_validator.py
│       │   │   │   ├── math_validator.py                    # cek rumus, dimensi matriks, sintaks
│       │   │   │   ├── science_validator.py                 # cek formula kimia/fisika
│       │   │   │   ├── fact_validator.py                    # cross-check knowledge base
│       │   │   │   ├── curriculum_validator.py              # sesuai silabus IB/Cambridge/AP
│       │   │   │   └── language_validator.py                # grammar, vocabulary level
│       │   │   └── ingestion/
│       │   │       ├── pipeline.py
│       │   │       ├── chunker.py
│       │   │       └── curriculum_ingestion.py              # ← BARU: ingest dokumen kurikulum resmi
│       │   │
│       │   ├── layer4_script_visual/
│       │   │   ├── script_generator.py
│       │   │   ├── visual_asset_generator.py
│       │   │   ├── difficulty_adapter.py                    # ← BARU: sesuaikan level kesulitan
│       │   │   ├── language_localizer.py                    # ← BARU: EN/ID/multilingual output
│       │   │   └── schemas.py                               # Scene JSON schema
│       │   │
│       │   ├── layer5_rendering/
│       │   │   ├── tts_service.py
│       │   │   ├── animation_router.py
│       │   │   ├── compositor.py                            # FFmpeg / Remotion
│       │   │   ├── timing_sync.py
│       │   │   ├── subtitle_generator.py                    # ← BARU: auto subtitle per scene
│       │   │   ├── quality_check/                           # ← BARU: validasi output video
│       │   │   │   ├── audio_validator.py                   # cek TTS tidak cutoff, volume normal
│       │   │   │   ├── timing_validator.py                  # narasi sync dengan visual
│       │   │   │   └── content_completeness.py              # semua scene ter-render
│       │   │   └── renderers/
│       │   │       ├── base_renderer.py
│       │   │       ├── manim_renderer.py                    # matematika, fisika
│       │   │       ├── lottie_renderer.py                   # animasi umum
│       │   │       ├── flux_sdxl_renderer.py                # image generation
│       │   │       ├── kling_renderer.py                    # video generation
│       │   │       ├── timeline_renderer.py                 # ← BARU: untuk sejarah/kronologi
│       │   │       ├── diagram_renderer.py                  # ← BARU: flowchart, struktur, siklus
│       │   │       ├── graph_renderer.py                    # ← BARU: grafik ekonomi, statistik
│       │   │       └── code_renderer.py                     # ← BARU: syntax highlight untuk CS
│       │   │
│       │   ├── layer6_delivery/
│       │   │   ├── cdn_service.py
│       │   │   ├── feedback_service.py
│       │   │   ├── partial_regen.py
│       │   │   ├── analytics.py
│       │   │   └── review/                                  # ← BARU: human review pipeline
│       │   │       ├── review_queue.py                      # antrian video butuh review manual
│       │   │       ├── approval_service.py                  # approve/reject sebelum publish
│       │   │       └── correction_log.py                    # track kesalahan yang pernah lolos
│       │   │
│       │   ├── billing/                                     # ← BARU: backend billing lengkap
│       │   │   ├── subscription_service.py                  # free vs premium logic
│       │   │   ├── usage_limiter.py                         # kuota video per tier per bulan
│       │   │   ├── payment_gateway.py                       # Stripe integration
│       │   │   ├── invoice_service.py                       # generate & kirim invoice
│       │   │   ├── webhook_handler.py                       # Stripe webhook events
│       │   │   └── tier_config.py                           # define free/premium feature gates
│       │   │
│       │   ├── workers/
│       │   │   ├── video_worker.py
│       │   │   ├── renderer_worker.py
│       │   │   └── review_worker.py                         # ← BARU: proses review queue
│       │   │
│       │   ├── prompts/
│       │   │   ├── curriculum/
│       │   │   │   ├── ib_curriculum.yaml                   # ← BARU: prompt IB spesifik
│       │   │   │   ├── cambridge_curriculum.yaml            # ← BARU: prompt Cambridge spesifik
│       │   │   │   └── ap_curriculum.yaml                   # ← BARU: prompt AP spesifik
│       │   │   ├── script/
│       │   │   │   ├── math_script.yaml                     # ← BARU: gaya penjelasan matematika
│       │   │   │   ├── science_script.yaml                  # ← BARU: gaya penjelasan sains
│       │   │   │   ├── history_script.yaml                  # ← BARU: gaya narasi sejarah
│       │   │   │   └── general_script.yaml
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
│       │       │   ├── test_subject_router.py
│       │       │   ├── test_validators.py
│       │       │   ├── test_billing.py
│       │       │   └── test_renderers.py
│       │       └── integration/
│       │           ├── test_full_pipeline.py
│       │           └── test_review_flow.py
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
│               ├── app/
│               │   ├── (landing)/
│               │   │   ├── page.tsx
│               │   │   └── layout.tsx
│               │   ├── (auth)/
│               │   │   ├── login/
│               │   │   │   └── page.tsx
│               │   │   ├── register/
│               │   │   │   └── page.tsx
│               │   │   ├── forgot-password/                 # ← BARU
│               │   │   │   └── page.tsx
│               │   │   └── layout.tsx
│               │   ├── (dashboard)/
│               │   │   ├── dashboard/
│               │   │   │   └── page.tsx
│               │   │   ├── projects/
│               │   │   │   └── page.tsx
│               │   │   ├── billing/
│               │   │   │   ├── page.tsx
│               │   │   │   ├── upgrade/                     # ← BARU: halaman upgrade ke premium
│               │   │   │   │   └── page.tsx
│               │   │   │   └── invoices/                    # ← BARU: riwayat invoice
│               │   │   │       └── page.tsx
│               │   │   ├── usage/                           # ← BARU: usage tracker per user
│               │   │   │   └── page.tsx
│               │   │   └── layout.tsx
│               │   ├── (studio)/
│               │   │   ├── studio/
│               │   │   │   └── [project_id]/
│               │   │   │       ├── page.tsx
│               │   │   │       └── loading.tsx
│               │   │   ├── layout.tsx
│               │   │   └── error.tsx
│               │   ├── (admin)/                             # ← BARU: admin panel internal
│               │   │   ├── admin/
│               │   │   │   ├── review-queue/                # monitor video pending review
│               │   │   │   │   └── page.tsx
│               │   │   │   ├── users/                       # manage users & subscriptions
│               │   │   │   │   └── page.tsx
│               │   │   │   └── analytics/                   # platform analytics
│               │   │   │       └── page.tsx
│               │   │   └── layout.tsx
│               │   ├── globals.css
│               │   ├── favicon.ico
│               │   └── layout.tsx
│               │
│               ├── features/
│               │   ├── studio/
│               │   │   ├── player/
│               │   │   │   ├── video-player.tsx
│               │   │   │   ├── quiz-overlay.tsx
│               │   │   │   └── index.ts
│               │   │   ├── timeline/
│               │   │   │   ├── timeline.tsx
│               │   │   │   ├── track.tsx
│               │   │   │   ├── playhead.tsx
│               │   │   │   └── hooks/
│               │   │   ├── script-editor/
│               │   │   │   ├── script-sidebar.tsx
│               │   │   │   └── script-editor.tsx
│               │   │   ├── asset-manager/
│               │   │   │   ├── asset-panel.tsx
│               │   │   │   └── visual-bible.tsx
│               │   │   ├── scene-inspector/
│               │   │   │   └── scene-inspector.tsx
│               │   │   ├── thumbnails/
│               │   │   │   └── scene-thumbnails.tsx
│               │   │   ├── feedback/
│               │   │   │   ├── feedback-modal.tsx
│               │   │   │   └── feedback-form.tsx
│               │   │   └── export/
│               │   │       └── export-modal.tsx
│               │   │
│               │   ├── billing/                             # ← BARU: billing feature components
│               │   │   ├── plan-selector.tsx                # pilih free/premium
│               │   │   ├── usage-meter.tsx                  # tampilkan sisa kuota
│               │   │   ├── payment-form.tsx                 # Stripe Elements
│               │   │   ├── invoice-list.tsx
│               │   │   └── upgrade-banner.tsx               # banner saat kuota habis
│               │   │
│               │   └── admin/                               # ← BARU: admin features
│               │       ├── review-panel.tsx                 # approve/reject video
│               │       ├── user-table.tsx
│               │       └── analytics-dashboard.tsx
│               │
│               ├── components/
│               │   ├── ui/                                  # Shadcn/ui components
│               │   │   ├── button.tsx
│               │   │   ├── dialog.tsx
│               │   │   ├── dropdown-menu.tsx
│               │   │   ├── slider.tsx
│               │   │   └── ...
│               │   ├── common/
│               │   │   ├── loading-spinner.tsx
│               │   │   ├── error-toast.tsx
│               │   │   ├── confirm-dialog.tsx
│               │   │   ├── premium-gate.tsx                 # ← BARU: wrapper block fitur premium
│               │   │   └── quota-warning.tsx                # ← BARU: warning kuota hampir habis
│               │   └── layout/
│               │       ├── sidebar.tsx
│               │       ├── header.tsx
│               │       └── studio-layout.tsx
│               │
│               ├── providers/
│               │   ├── studio-provider.tsx
│               │   ├── query-provider.tsx
│               │   ├── websocket-provider.tsx
│               │   ├── theme-provider.tsx
│               │   ├── subscription-provider.tsx            # ← BARU: expose tier & quota ke seluruh app
│               │   └── index.tsx
│               │
│               ├── hooks/
│               │   ├── use-websocket.ts
│               │   ├── use-video-player.ts
│               │   ├── use-project-data.ts
│               │   ├── use-auto-save.ts
│               │   ├── use-hotkeys.ts
│               │   ├── use-render-progress.ts
│               │   ├── use-subscription.ts                  # ← BARU: cek tier & quota
│               │   └── use-billing.ts                       # ← BARU: trigger upgrade flow
│               │
│               ├── store/
│               │   ├── use-studio-store.ts
│               │   ├── use-project-store.ts
│               │   ├── use-render-store.ts
│               │   ├── use-subscription-store.ts            # ← BARU: state tier & quota
│               │   └── index.ts
│               │
│               ├── services/
│               │   ├── project-service.ts
│               │   ├── render-service.ts
│               │   ├── feedback-service.ts
│               │   └── billing-service.ts                   # ← BARU: Stripe + subscription API calls
│               │
│               ├── lib/
│               │   ├── api/
│               │   │   ├── client.ts
│               │   │   ├── project-api.ts
│               │   │   ├── render-api.ts
│               │   │   ├── feedback-api.ts
│               │   │   └── billing-api.ts                   # ← BARU
│               │   ├── video/
│               │   │   ├── timecode.ts
│               │   │   ├── hls-utils.ts
│               │   │   └── subtitle-utils.ts
│               │   ├── validators/
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
│               │   ├── subscription.ts                      # ← BARU: Tier, Quota, Invoice types
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
├── core/
│   ├── orchestrator/
│   │   ├── meta_orchestrator.py
│   │   └── task_router.py
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
│   ├── agent_lifecycle.py
│   ├── event_bus.py
│   └── rate_limiter.py
│
├── agents/                                                  # FROZEN: aktifkan saat produk stabil
│   ├── executive/
│   ├── research/
│   ├── engineering/
│   ├── product/
│   ├── operations/
│   ├── growth/
│   └── lobby/
│
├── shared/
│   ├── prompts/
│   │   └── company/
│   │
│   ├── schemas/
│   │   ├── scene_schema.py
│   │   ├── job_schema.py
│   │   ├── agent_schema.py
│   │   └── billing_schema.py                               # ← BARU: shared billing contracts
│   │
│   ├── tools/
│   │   ├── web_search.py
│   │   ├── code_executor.py
│   │   ├── video_tools.py
│   │   └── image_generator.py
│   │
│   ├── knowledge_base/                                     # ← BARU: diperluas per kurikulum
│   │   ├── ib/                                             # dokumen resmi IB
│   │   │   ├── mathematics/
│   │   │   ├── sciences/
│   │   │   ├── humanities/
│   │   │   └── languages/
│   │   ├── cambridge/                                      # dokumen IGCSE/A-Level
│   │   │   ├── mathematics/
│   │   │   ├── sciences/
│   │   │   ├── humanities/
│   │   │   └── languages/
│   │   ├── ap/                                             # dokumen AP College Board
│   │   │   ├── mathematics/
│   │   │   ├── sciences/
│   │   │   ├── humanities/
│   │   │   └── languages/
│   │   └── ingestion_pipeline.py                          # proses dokumen ke vector DB
│   │
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
│   ├── agent_personalities.yaml                            # frozen
│   ├── floor_config.yaml                                   # frozen
│   ├── tier_limits.yaml                                    # ← BARU: define free/premium limits
│   ├── subject_config.yaml                                 # ← BARU: config per mapel & renderer
│   ├── curriculum_config.yaml                              # ← BARU: IB/Cambridge/AP settings
│   └── secrets.yaml                                        # .gitignore wajib
│
├── logs/
│   ├── activity.log
│   ├── decisions.log
│   ├── cost_tracking.log
│   ├── errors.log
│   ├── review_decisions.log                                # ← BARU: log approve/reject manual
│   └── billing_events.log                                  # ← BARU: log semua transaksi
│
├── tests/
│   ├── e2e/
│   │   ├── test_video_generation_flow.py
│   │   └── test_billing_flow.py                            # ← BARU
│   └── integration/
│       ├── test_rag_per_curriculum.py                      # ← BARU
│       └── test_subject_routing.py                         # ← BARU
│
├── scripts/
│   ├── deploy.sh
│   ├── backup.sh
│   ├── seed_db.py
│   ├── generate_types.py                                   # Pydantic → TypeScript
│   ├── ingest_curriculum.py                                # ← BARU: ingest knowledge base kurikulum
│   ├── seed_billing_tiers.py                               # ← BARU: setup free/premium tiers di DB
│   └── spawn_agents.py                                     # frozen
│
├── docker-compose.yml
├── Makefile
├── .env
├── .gitignore
└── README.md          
