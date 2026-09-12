# Production Deployment Guide

## Prerequisites

- Docker 24+ and Docker Compose v2
- NVIDIA GPU with CUDA 12.1+ (optional, for faster ML)
- Minimum 8GB RAM (16GB recommended for large datasets)
- PostgreSQL 16 (via Docker or managed service)

---

## Quick Start (Development)

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env: set SECRET_KEY, JWT_SECRET_KEY, AWS credentials

# 2. Start all services
docker compose up -d

# 3. Run database migrations
docker compose exec backend alembic upgrade head

# 4. Create first admin user
docker compose exec backend python -c "
from app.core.security import get_password_hash
from app.db.session import async_session_factory
import asyncio

async def create_admin():
    from app.models.models import User
    import uuid
    from app.core.security import generate_api_key
    async with async_session_factory() as db:
        user = User(
            id=uuid.uuid4(),
            email='admin@example.com',
            hashed_password=get_password_hash('changeme'),
            plan='enterprise',
            is_superuser=True,
            api_key=generate_api_key(),
        )
        db.add(user)
        await db.commit()
        print(f'Created admin: admin@example.com / changeme')
        print(f'API Key: {user.api_key}')

asyncio.run(create_admin())
"

# 5. Access
#   Frontend:       http://localhost:3000
#   API Docs:       http://localhost:8000/docs
#   Celery Flower:  http://localhost:5555
```

---

## Production Setup

### 1. SSL Certificates

```bash
# Using Let's Encrypt (certbot)
certbot certonly --webroot -w /var/www/html -d your-domain.com
cp /etc/letsencrypt/live/your-domain.com/fullchain.pem infrastructure/nginx/ssl/
cp /etc/letsencrypt/live/your-domain.com/privkey.pem infrastructure/nginx/ssl/
```

### 2. Environment Variables

Critical production settings in `.env`:

```bash
APP_ENV=production
DEBUG=false
SECRET_KEY=<random 64+ char string>
JWT_SECRET_KEY=<random 64+ char string>
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/hcd_db
AWS_ACCESS_KEY_ID=<your-key>
AWS_SECRET_ACCESS_KEY=<your-secret>
S3_BUCKET_NAME=your-production-bucket
STRIPE_SECRET_KEY=sk_live_...
SENTRY_DSN=https://...@sentry.io/...
```

### 3. GPU Setup (NVIDIA)

```bash
# Install NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/libnvidia-container/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### 4. Database Optimization

```sql
-- Connect to PostgreSQL and run:
ALTER SYSTEM SET shared_buffers = '2GB';
ALTER SYSTEM SET effective_cache_size = '6GB';
ALTER SYSTEM SET work_mem = '64MB';
SELECT pg_reload_conf();
```

### 5. Celery Workers

For production, run specialized workers:

```bash
# Cycle detection worker (CPU-intensive)
celery -A app.tasks.celery_app worker --loglevel=info \
  -Q cycle_detection --concurrency=4 -n cycle_worker@%h

# ML training worker (GPU)
celery -A app.tasks.celery_app worker --loglevel=info \
  -Q ml_training --concurrency=1 -n ml_worker@%h

# Data fetch worker
celery -A app.tasks.celery_app worker --loglevel=info \
  -Q data_fetch --concurrency=8 -n data_worker@%h
```

### 6. Monitoring

- **Prometheus**: http://localhost:9090 (scrapes /metrics)
- **Grafana**: http://localhost:3001 (dashboards for request rates, queue depth)
- **Flower**: http://localhost:5555 (Celery task monitoring)
- **Sentry**: Configure SENTRY_DSN for error tracking

---

## Architecture Overview

```
Internet
    │
    ▼
Nginx (SSL termination, rate limiting)
    │
    ├─► Frontend (Next.js, port 3000)
    │       Static assets cached at CDN
    │
    └─► Backend (FastAPI, port 8000)
            │
            ├─► PostgreSQL (persistence)
            ├─► Redis (cache + queue)
            ├─► Celery Workers (async ML)
            │       ├── cycle_detection queue
            │       ├── ml_training queue (GPU)
            │       └── data_fetch queue
            └─► S3 (market data + model artifacts)
```

---

## Performance Benchmarks

| Dataset | Method | Time (CPU) | Time (GPU) |
|---------|--------|-----------|-----------|
| 20Y NIFTY daily | Full analysis | ~45s | ~12s |
| 5Y hourly | Cycle detection | ~8s | ~3s |
| 1Y 1-min | FFT only | ~2s | <1s |

---

## Data Flow

```
User Request
    │
    ▼
POST /research/analyze
    │
    ▼
Celery Task (run_full_analysis)
    │
    ├── Module 1: Preprocessing
    ├── Module 2: Cycle Detection  ──► DB: cycles table
    ├── Module 3: Pattern Discovery ──► DB: patterns table
    ├── Module 4: Planetary (Pro)
    ├── Module 5: Feature Discovery ──► S3: feature matrix
    ├── Module 6: AI Model (Enterprise)
    ├── Module 7: Analog Engine ──► DB: analogs table
    ├── Module 8: Stability Testing
    └── Report Generation ──► DB: research_reports
    │
    ▼
WebSocket / SSE Progress Updates
    │
    ▼
GET /research/jobs/{id}/result
```

---

## API Reference

Full API documentation available at `/docs` (Swagger) or `/redoc`.

Key endpoints:

```
POST /api/v1/market-data/fetch       Fetch market data
POST /api/v1/market-data/upload      Upload CSV
POST /api/v1/research/analyze        Run full analysis
POST /api/v1/research/query          Natural language query
GET  /api/v1/research/jobs/{id}      Poll job progress
GET  /api/v1/cycles/{market_data_id} Get cycle results
GET  /api/v1/patterns/{id}           Get pattern results
GET  /api/v1/analogs/{id}            Get historical analogs
GET  /api/v1/planetary/positions     Current planetary positions
```

---

## Scaling

For high-load deployments:

1. **Horizontal scaling**: Add more Celery workers for parallel processing
2. **Database**: Use PgBouncer for connection pooling
3. **Cache**: Redis Cluster for high availability
4. **Storage**: Use S3 with CloudFront CDN for fast data access
5. **GPU fleet**: Use NVIDIA A100 80GB for large transformer models
