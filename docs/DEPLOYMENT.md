# Deployment Rules — GCP

> These rules are learned from production incidents. Follow them exactly.

## Infrastructure

- **GCP Project:** `ai-calling-9238e` (NEVER use `fresh-rain-481419-t6` — terminated)
- **VM:** `wavelength-v3` in `asia-south1-c`
- **SSH:** `gcloud compute ssh wavelength-v3 --zone=asia-south1-c --project=ai-calling-9238e`
- **Backend path:** `/home/animeshmahato/wavelength-v3`
- **Frontend path:** `/home/animeshmahato/wavelength-v3/frontend`
- **Backend:** Docker container `wavelength-backend` on port 8080
- **Database:** Postgres 15 container `wavelength-db` on `wavelength-net` network
- **Frontend:** PM2 process `wavelength-frontend` (Next.js)
- **Cloud Build:** `cloudbuild.yaml` → Artifact Registry → Cloud Run (automated path)

## Backend Deploy — Always Atomic

NEVER deploy partially. All steps run as one command or not at all.

```bash
cd /home/animeshmahato/wavelength-v3 && \
sudo git pull origin main && \
sudo docker compose build backend && \
sudo docker compose up -d backend
```

If there's a new migration, add AFTER `up -d`:
```bash
sleep 5 && sudo docker compose exec backend alembic upgrade head
```

## Frontend Deploy — Always Atomic

```bash
cd /home/animeshmahato/wavelength-v3 && \
sudo git pull origin main && \
sudo chown -R animeshmahato:animeshmahato frontend/.next && \
cd frontend && npm run build && pm2 restart wavelength-frontend
```

## Critical Rules — Learned From Incidents

### Docker
- **NEVER** run `docker volume prune -f` — wipes pip cache, forces 50-minute rebuild
- Use `docker image prune -f` to reclaim space (safe)
- **NEVER** set `--workers` to more than 1 in Dockerfile uvicorn CMD
  - Pipecat/torch/onnxruntime take 30+ seconds to cold-start
  - Multiple workers get killed by gunicorn's 30s startup timeout → infinite crash-loop
  - Single worker handles 100+ concurrent WebSocket connections (all compute offloaded to APIs)

### Dockerfile
- Always use pip cache mount: `RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt`
- NEVER use `--no-cache-dir` — turns 2-minute rebuilds into 50-minute rebuilds on GCP VM

### Frontend
- PM2 runs under default SSH user, NOT root — never use `sudo pm2`
- Never kill next-server processes manually (`kill`, `fuser`) — causes pm2 crash-loop (1000+ restarts)
- Always `chown` frontend/.next before building — previous sudo builds leave root-owned files
- There's also a systemd service `wavelength-frontend.service`

### General
- Always check if someone else is deploying before starting
- Never push directly to production without testing locally first
- Verify the deploy worked: check logs with `sudo docker compose logs -f backend --tail=50`
- Frontend verify: check PM2 status with `pm2 status` and `pm2 logs wavelength-frontend`

## Environment & Secrets
- Backend env vars: stored in `.env` file on VM, mounted via docker-compose
- Cloud Run secrets: managed via GCP Secret Manager (see cloudbuild.yaml `--set-secrets`)
- NEVER commit `.env` files or credentials to git
- Credentials directory mounted read-only: `./credentials:/credentials:ro`
