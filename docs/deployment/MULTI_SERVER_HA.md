# Multi-server / HA deployment (shared Postgres + shared media)

Pilot pack (`docker-compose.yml`) is **single app node**. The Loan Hub can scale to several app servers when Dedebit needs HA or capacity. This note is the ops write-up — no extra product features required.

## Architecture

```
                    ┌─────────────┐
  Staff / tablets → │ LB / nginx  │
                    └──────┬──────┘
               ┌───────────┼───────────┐
               ▼           ▼           ▼
            web-1       web-2       web-N     (stateless Django / gunicorn)
               └───────────┼───────────┘
                           ▼
                    ┌──────────────┐
                    │  PostgreSQL  │  ← one primary (or managed HA Postgres)
                    └──────────────┘
                           ▲
               ┌───────────┴───────────┐
               ▼                       ▼
         shared MEDIA            optional Redis
      (NFS / SAN / S3)         (sessions/cache)
```

| Layer | Pilot today | Multi-server |
|-------|-------------|--------------|
| App (`web`) | One container | N identical nodes behind a load balancer |
| Database | One Postgres (`db`) | Still **one logical primary** shared by all app nodes |
| Media (docs, signatures, photos) | Docker volume `media_data` | **Must be shared** across all app nodes |
| Sessions | Django DB sessions | Keep DB sessions (works across nodes) or Redis |
| Backup | `backup` service → `./backups/` | Run against the shared DB + shared media mount |

## Shared media (required)

Documents, remote agreement images, collateral photos, and OCR inputs live under `MEDIA_ROOT` (`/app/media` in Docker).

If each app node has its own disk:

- Upload on node A → 404 / missing file on node B
- Nightly backup on one node misses files written on another

**Choose one:**

1. **NFS / SAN** mounted at the same path on every app node (`/app/media` or host path bind-mounted into each container).
2. **Object storage** (S3-compatible) with a Django storage backend — only if Dedebit standardises on that later.

Compose sketch (NFS host path):

```yaml
services:
  web:
    # scale: docker compose up --scale web=3
    volumes:
      - /mnt/decsi-media:/app/media
    environment:
      USE_GUNICORN: "1"
```

Keep Postgres on dedicated storage; do not put the database on the same NFS share as media.

## Load balancer notes

- Terminate TLS at nginx / F5 / HAProxy; set `USE_HTTPS_PROXY=1` and `CSRF_TRUSTED_ORIGINS`.
- Sticky sessions are **optional** if sessions stay in Postgres (default).
- Health check: `GET /hub/` (or a dedicated health URL) should hit a node that can reach Postgres.
- Upload size limits on the LB must be ≥ Django / nginx body limits (large PDFs, field photos).

## What stays single

- **Postgres primary** — do not run multiple independent databases. Read replicas are optional for reporting only; writes (loan files, cases, disbursement) go to primary.
- **License key** — same `LICENSE_KEY` on every app node (shared `.env` or secret store).
- **Midnight backup** — one scheduler (current `backup` service or host cron) dumping primary DB + shared media; retention as today.

## Cutover checklist

1. Provision shared media mount; migrate existing `media_data` once.
2. Point 2+ app nodes at the same `DATABASE_URL` / DB_* and same media mount.
3. Put LB in front; smoke-test login, document upload, open file on another node.
4. Set `USE_GUNICORN=1` (see `.env.example`).
5. Confirm backup job targets shared media + primary DB.
6. Keep CBS / Chapa / SMS env identical across nodes.

## Related

- `docs/deployment/DEDEBIT_ON_PREM_INSTALLATION.md` — pilot install
- `docs/deployment/CBS_CUTOVER_CHECKLIST.md` — live CBS endpoints
- `.env.example` — `USE_GUNICORN`, CBS, Chapa, SMS
