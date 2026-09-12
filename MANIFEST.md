# Complete File Manifest — Hidden Cycle Discovery AI

## Root
- README.md — project overview & quick start
- docker-compose.yml — all 7 services
- Makefile — dev commands (up, down, test, migrate, create-admin...)
- .env.example — all environment variables
- .gitignore
- MANIFEST.md — this file

## Backend (FastAPI + Celery + PyTorch)
### Config & Entry
- backend/Dockerfile — CUDA 12.1 + Python 3.11 image
- backend/requirements.txt — full scientific + ML stack
- backend/alembic.ini — migration config
- backend/pytest.ini — test config
- backend/.dockerignore, backend/.gitignore
- backend/app/main.py — FastAPI app, middleware, metrics, lifespan

### Core
- backend/app/core/config.py — Pydantic settings
- backend/app/core/security.py — JWT, password hashing, API keys
- backend/app/core/redis.py — Redis pool

### Database
- backend/app/db/base.py — declarative base
- backend/app/db/session.py — async engine + session
- backend/app/models/models.py — all 12 ORM tables
- backend/alembic/env.py, script.py.mako
- backend/alembic/versions/0001_initial.py

### ML Engines (10 modules)
- backend/app/ml/preprocessing/engine.py    — Module 1
- backend/app/ml/cycle_detection/engine.py   — Module 2 (FFT/Lomb/Wavelet/Hilbert/Hurst)
- backend/app/ml/pattern_discovery/engine.py — Module 3 (DTW/KMeans/HMM)
- backend/app/ml/planetary/engine.py         — Module 4 (ephemeris correlations)
- backend/app/ml/feature_engine/engine.py    — Module 5 (1000+ features)
- backend/app/ml/ai_models/engine.py         — Module 6 (Autoencoder/Transformer/LSTM/TCN)
- backend/app/ml/analog/engine.py            — Module 7 (historical analogs)
- backend/app/ml/stability/engine.py         — Module 8 (walk-forward/OOS/bootstrap)

### API Endpoints
- backend/app/api/v1/router.py
- backend/app/api/v1/endpoints/{auth,users,market_data,research,cycles,
  patterns,analogs,planetary,features,models,reports,webhooks}.py

### Services & Tasks
- backend/app/services/data_service.py     — data fetch/load/save (Module 9 + 10 data layer)
- backend/app/services/storage_service.py  — S3 operations
- backend/app/tasks/tasks.py               — Celery pipeline orchestration
- backend/app/schemas/auth.py              — Pydantic schemas

### Scripts & Tests
- backend/scripts/create_admin.py
- backend/tests/test_all_modules.py        — 30+ tests across all modules
- backend/tests/conftest.py

## Frontend (Next.js 14 + TypeScript + Tailwind + shadcn)
- frontend/package.json, tsconfig.json, next.config.ts
- frontend/tailwind.config.ts, postcss.config.js
- frontend/Dockerfile, .gitignore, next-env.d.ts
- frontend/src/app/layout.tsx, page.tsx, globals.css
- frontend/src/components/layout/AppShell.tsx
- frontend/src/components/research/{DataInputPanel,JobProgressPanel,ResearchSummaryPanel}.tsx
- frontend/src/components/cycle/{CycleResultsPanel,PatternResultsPanel,AnalogPanel}.tsx
- frontend/src/components/providers.tsx
- frontend/src/lib/{api,utils}.ts
- frontend/src/store/researchStore.ts

## Infrastructure
- infrastructure/nginx/nginx.conf      — SSL, rate limiting, WebSocket/SSE
- infrastructure/postgres/init.sql     — extensions + tuning

## Docs
- docs/deployment.md — production deployment guide
