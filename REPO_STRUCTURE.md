# Wavelength v3 — Repository Structure

> Keep this file updated when creating, moving, or deleting files.

```
app/                              — FastAPI backend
  main.py                         — Entry point, lifespan, asyncpg pool
  config.py                       — Feature flags (ECHO_GATE_ENABLED, GREETING_DIRECT_PLAY, etc.)
  database.py                     — Database connection pool and session management
  utils.py                        — Helper utilities

  api/                            — REST API endpoints
    sequences.py                  — Sequence CRUD and execution
    bots.py                       — Bot configuration endpoints
    calls.py                      — Call history and analytics
    billing.py                    — Billing and subscription management
    queue.py                      — Call queue management
    payments.py                   — Payment processing
    webhook.py                    — External webhook handlers
    sequence_analytics.py         — Analytics aggregation
    telephony.py                  — Phone number management
    messaging_providers.py        — Third-party messaging integrations
    health.py                     — Health check endpoints
    leads.py                      — Lead management endpoints

  audio/                           — Audio assets and loaders
    ambient.py                    — Singleton WAV loader for ambient presets
    presets/                      — WAV files (16kHz mono 16-bit PCM)
      static.wav                  — Phone line static noise (60s loop)
      office_hum.wav              — HVAC hum + room tone (60s loop)
  pipeline/                       — Pipecat call pipeline orchestration
    factory.py                    — Per-call pipeline construction
    runner.py                     — Pipeline execution and greeting playback
    ambient_mixer.py              — Ambient background noise mixer (Phase 5)
    call_guard.py                 — Call validation and filtering
    session_limiter.py            — Concurrent call limits
    silence_watchdog.py           — Silence detection and handling
    early_hangup.py               — Pre-conversation no-speech hangup timer
    hold_music_detector.py        — Hold music detection (VAD without STT)
    idle_handler.py               — Idle timeout management
    phrase_aggregator.py          — Adaptive phrase aggregation

  services/                       — Core business logic and integrations
    sequence_engine.py            — Sequence execution state machine
    sequence_scheduler.py         — Schedule-based sequence triggering
    smart_retry.py                — Adaptive retry scheduling with templates
    callback_scheduler.py         — Callback scheduling with timezone support
    call_analyzer.py              — Real-time call quality analysis
    call_memory.py                — Conversation context management
    sequence_analytics.py         — Analytics calculations
    lead_sync.py                  — GHL lead sync and webhooks
    anthropic_client.py           — Anthropic API wrapper
    google_cloud_tts.py           — Google Cloud TTS gRPC streaming (legacy)
    messaging_client.py           — SMS/messaging provider abstraction
    queue_processor.py            — Background queue job processing
    org_credentials.py            — Organization credential management
    credential_encryption.py      — Encryption utilities
    circuit_breaker.py            — Circuit breaker for external calls
    billing.py                    — Billing calculation and usage tracking

  models/                         — SQLAlchemy ORM models
    user.py                       — User authentication and profile
    organization.py               — Multi-tenant organization container
    user_org.py                   — User-organization relationships
    bot_config.py                 — Bot configuration per organization
    sequence.py                   — Automation sequence definitions
    campaign.py                   — Campaign grouping and execution
    lead.py                       — Lead/contact records
    call_log.py                   — Call history and metadata
    call_queue.py                 — Call queue entries
    call_analytics.py             — Call performance metrics
    phone_number.py               — Phone number assignments
    messaging_provider.py         — Third-party provider configs
    billing.py                    — Billing and subscription data
    schemas.py                    — Pydantic request/response schemas

  auth/                           — Authentication and authorization
    security.py                   — Password hashing, token generation
    dependencies.py               — FastAPI auth dependency injection
    router.py                     — Auth endpoints (login, signup, refresh)

  plivo/                          — Plivo VoIP provider integration
    client.py                     — Plivo API wrapper
    routes.py                     — Plivo webhooks and WS endpoint
    xml_responses.py              — Plivo XML stream config

  ghl/                            — GoHighLevel CRM integration
    client.py                     — GHL API wrapper

  serializers/                    — Custom audio serialization
    plivo_pcm.py                  — PCM 16kHz serializer + echo RTT + ComfortNoiseInjector

frontend/                         — Next.js 14 + React (TypeScript)
  src/
    app/                          — Next.js App Router pages
      layout.tsx                  — Root layout with providers
      (auth)/                     — Auth routes (no sidebar)
        signup/page.tsx           — Signup form
        invite/[inviteId]/page.tsx — Team invitation acceptance
      (app)/                      — Protected routes (with sidebar)
        layout.tsx                — Main app layout with navigation
        dashboard/page.tsx        — Dashboard overview
        calls/page.tsx            — Call history list
        calls/[callId]/page.tsx   — Call detail and transcripts
        leads/page.tsx            — Leads/contacts management
        leads/[leadId]/page.tsx   — Lead detail with sequence history
        sequences/page.tsx        — Sequence builder/list
        sequences/[id]/page.tsx   — Sequence detail and editor
        sequences/monitor/page.tsx — Execution monitoring
        sequences/analytics/page.tsx — Performance analytics
        campaigns/page.tsx        — Campaign management
        campaigns/[campaignId]/page.tsx — Campaign detail
        bots/page.tsx             — Bot configuration list
        bots/[botId]/page.tsx     — Bot settings editor
        queue/page.tsx            — Call queue monitor
        call-logs/page.tsx        — Call logs and filtering
        billing/page.tsx          — Billing and subscription
        analytics/page.tsx        — Organization analytics
        settings/page.tsx         — General settings
        settings/messaging/page.tsx — Messaging provider setup
        team/page.tsx             — Team member management
        admin/page.tsx            — Admin panel (super-admin)

    components/                   — Reusable React components
      layout/                     — Layout building blocks
      sequences/                  — Sequence-specific components
      ui/                         — Shadcn UI components

    hooks/                        — Custom React hooks
      use-calls.ts                — Call list and filtering
      use-leads.ts                — Lead management
      use-analytics.ts            — Analytics queries
      use-bots.ts                 — Bot configuration
      use-campaigns.ts            — Campaign operations
      use-queue.ts                — Queue monitoring
      use-billing.ts              — Billing data
      use-settings.ts             — Settings management
      use-keyboard-shortcuts.ts   — Global keyboard shortcuts
      use-mobile.ts               — Mobile detection
      index.ts                    — Export barrel

    lib/                          — Utility libraries
      api.ts                      — Backend API client
      schemas.ts                  — Zod validation schemas
      utils.ts                    — General utilities
      constants.ts                — App constants and enums
      status-config.ts            — Call/sequence status config
      call-logs-export.ts         — CSV/PDF export utilities
      sequences-api.ts            — Sequence API helpers
      messaging-api.ts            — Messaging API helpers

    contexts/                     — React context providers
      auth-context.tsx            — User auth state and session

    types/                        — TypeScript type definitions
      api.ts                      — API request/response types

    test/                         — Test utilities and setup

alembic/                          — Database migrations
  versions/                       — SQL migration files
  env.py                          — Alembic environment config

tests/                            — Python test suite
docs/                             — Documentation and specs
scripts/                          — Build and utility scripts

infra/                            — GCP infrastructure scripts
  autoscaler/                     — VM CPU auto-scaler (Cloud Function)
    main.py                       — Auto-scale logic (1-4 CPUs based on utilization)
    requirements.txt              — Cloud Function dependencies
    deploy.sh                     — One-command deploy script

Dockerfile                        — Single-process Docker build
docker-compose.yml                — Local dev containers
requirements.txt                  — Python dependencies
alembic.ini                       — Alembic config
cloudbuild.yaml                   — GCP Cloud Build pipeline
```
