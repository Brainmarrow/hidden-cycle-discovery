# HIDDEN CYCLE DISCOVERY AI

> Institutional-grade quantitative research platform for discovering hidden market cycles, repeating structures, and temporal dependencies.

## Architecture Overview

```
hidden-cycle-discovery/
├── backend/                    # FastAPI + Celery + ML Pipeline
│   ├── app/
│   │   ├── api/v1/endpoints/   # REST API endpoints
│   │   ├── core/               # Config, security, dependencies
│   │   ├── db/                 # Database session, base models
│   │   ├── models/             # SQLAlchemy ORM models
│   │   ├── schemas/            # Pydantic schemas
│   │   ├── services/           # Business logic layer
│   │   ├── tasks/              # Celery async tasks
│   │   └── ml/                 # ML modules (10 engines)
│   └── tests/
├── frontend/                   # Next.js 14 + TypeScript + Tailwind
│   └── src/
│       ├── app/                # App router pages
│       ├── components/         # UI components
│       ├── hooks/              # Custom hooks
│       └── store/              # Zustand state management
└── infrastructure/             # Docker, Nginx, DB init
```

## Modules

| Module | Description |
|--------|-------------|
| 1. Preprocessing Engine | Returns, log-returns, detrending, normalization |
| 2. Cycle Detection Engine | FFT, Lomb-Scargle, Wavelets, Autocorrelation, Hilbert, Hurst |
| 3. Pattern Discovery Engine | DTW, KMeans, hierarchical clustering, regime detection |
| 4. Planetary Correlation Engine | Ephemeris, aspects, retrograde, cross-correlation |
| 5. Feature Discovery Engine | 1000+ engineered features, importance ranking |
| 6. AI Model Engine | Autoencoder, Transformer, LSTM, TCN |
| 7. Analog Engine | Historical similarity matching |
| 8. Stability Engine | Walk-forward, OOS testing, decay analysis |
| 9. Research Engine | NL query, report generation |
| 10. Visualization Engine | Heatmaps, spectrograms, wavelet maps, cycle wheels |

## Quick Start

```bash
# Clone and setup
git clone <repo>
cd hidden-cycle-discovery

# Copy environment files
cp .env.example .env

# Start all services
docker-compose up -d

# Run database migrations
docker-compose exec backend alembic upgrade head

# Access
# Frontend: http://localhost:3000
# API Docs: http://localhost:8000/docs
# Celery Flower: http://localhost:5555
```

## Environment Variables

See `.env.example` for all required variables.

## Production Deployment

See `docs/deployment.md` for production setup with GPU acceleration.
