# Dedebit (DECSI) — On-Premises Installation Guide

**Audience:** Dedebit Credit and Savings Institution (DECSI) technical / infrastructure team  
**Product:** AI-powered Credit Intelligence (Loan Hub + Digital Apply + collateral + market)  
**Vendor:** Seqela Technologies  
**Deploy model:** On-premises (your data centre / private cloud)  
**Licensing:** Signed **license key** with an **expiry date** (renewed by Seqela)  
**GitHub:** https://github.com/habenkiros/decsi_loan  

This pack is what IT needs to install, license, smoke-test, and hand over to operations.

Related end-user manuals (admin / staff / customers) live under `docs/user_manual/` and inside the app at `/hub/help/`.

---

## Quick start (simplest path)

On a Linux server with Docker 24+, Compose v2, and Git:

```bash
git clone https://github.com/habenkiros/decsi_loan.git
cd decsi_loan
./scripts/install_decsi.sh
```

That one script creates `.env`, applies the evaluation license, starts Docker, migrates the database, and can create a superuser.

Short handout: [`INSTALL_DECSI.md`](../../INSTALL_DECSI.md) at the repo root.

Continue below only if you need manual steps, HTTPS tablets, backups, multi-server HA, or hardening.

Related: [`MULTI_SERVER_HA.md`](MULTI_SERVER_HA.md) (shared Postgres + shared media), [`CBS_CUTOVER_CHECKLIST.md`](CBS_CUTOVER_CHECKLIST.md).

---

## 1. What you receive from Seqela

| Item | Purpose |
|------|---------|
| Application release (Git tag / zip / Docker images) | The software |
| This installation guide | Step-by-step bring-up |
| **`LICENSE_KEY`** (string starting with `SEQLA1.`) | Activates the product until the embedded expiry date |
| Optional: user manuals PDF | Training / ops |

**Current evaluation key (this pack):** **7 days** (expires **2026-08-26**). After commercial agreement, Seqela will issue the **Year‑1** license key for production.

You do **not** receive Seqela’s private signing key. Only Seqela can issue or extend license keys.

---

## 2. Minimum server requirements

| Resource | Minimum (pilot) | Recommended |
|----------|-----------------|-------------|
| CPU | 2 vCPU | 4 vCPU |
| RAM | 4 GB | 8 GB |
| Disk | 40 GB SSD free | 100 GB+ (document media grows) |
| OS | Ubuntu 22.04 LTS or RHEL 8/9 (x86_64) | Same |
| Software | Docker Engine **24+**, Docker Compose **v2**, Git | Same |
| Network | LAN to staff PCs; static IP or DNS name | NTP synchronized (required for MFA) |

**Ports**

| Port | Use |
|------|-----|
| 8000/tcp | Application HTTP (or map via reverse proxy) |
| 5432/tcp | PostgreSQL — **localhost / Docker network only** |
| 8443/tcp | Optional HTTPS overlay for field tablets |

---

## 3. License key model (important)

### 3.1 How it works

1. Seqela issues a signed key for **Dedebit / DECSI** with:
   - Organization name and code  
   - **Issue date** and **expiry date**  
   - Feature flags (hub, Digital Apply, market, collateral, …)
2. Dedebit IT places the key in `.env` as `LICENSE_KEY=...` (or in `deploy/license/license.key`).
3. The app verifies the signature **offline** (no phone-home) using Seqela’s public key baked into the product.
4. While the key is valid, the product runs normally.
5. Hub shows a **warning banner** when ≤ 30 days remain.
6. After expiry, a short **grace period** (default **7 days**) still allows login so IT can install a renewal key.
7. After grace, the product **locks** until a new key is installed (status page `/license/` stays reachable).

### 3.2 Install the license

```bash
# Option A — .env
echo 'LICENSE_KEY=SEQLA1.xxxxx.yyyyy' >> /opt/decsi_loan/.env

# Option B — file (one line, no quotes)
mkdir -p /opt/decsi_loan/deploy/license
nano /opt/decsi_loan/deploy/license/license.key
```

Recommended production settings:

```bash
LICENSE_ENFORCE=True
LICENSE_GRACE_DAYS=7
```

Check status:

```bash
docker compose exec web python manage.py check_license
# or open https://<host>/license/
```

### 3.3 Renew before expiry

1. Contact Seqela with your `org_code` (e.g. `DECSI`) and desired new expiry date.  
2. Receive a new `SEQLA1.…` string.  
3. Replace `LICENSE_KEY` (or `license.key`).  
4. `docker compose restart web`  
5. Confirm `/license/` shows **Valid** and the new expiry.

**Do not** edit the middle of the key — any change invalidates the signature.

---

## 4. Installation steps (Docker Compose — required path)

### Step 1 — Prepare host

```bash
sudo apt update
sudo apt install -y git ca-certificates curl
# Install Docker Engine 24+ and Compose v2 per Docker docs for your OS
docker --version
docker compose version
timedatectl status   # NTP should be active
```

### Step 2 — Obtain the release

```bash
sudo mkdir -p /opt
cd /opt
# Use the URL / media Seqela provides, for example:
# git clone <seqela-release-url> decsi_loan
# or: unzip Dedebit_Loan_Hub_Release_YYYYMMDD.zip -d decsi_loan
cd decsi_loan
```

### Step 3 — Environment file

```bash
cp .env.example .env
nano .env
```

**Minimum required values:**

```bash
SECRET_KEY=<long-random-string>
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1,<server-ip-or-hostname>
SITE_URL=http://<server-ip-or-hostname>:8000

DB_NAME=decsiloandb
DB_USER=decsiloandbuser
DB_PASSWORD=<strong-password>
DB_HOST=db
DB_PORT=5432

LICENSE_KEY=<paste-SEQLA1-key-from-Seqela>
LICENSE_ENFORCE=True
LICENSE_GRACE_DAYS=7

LOGIN_MAX_FAILED_ATTEMPTS=5
LOGIN_LOCKOUT_MINUTES=15
MFA_REQUIRED=True
MFA_TOTP_ISSUER=DECSI Loan Hub
SESSION_IDLE_TIMEOUT=1800

DECSI_CUSTOMER_FALLBACK_MOCK=True
DECSI_CBS_USE_MOCK_LEDGER=True
CHAPA_FORCE_MOCK=True
```

Generate `SECRET_KEY` (any machine with Python):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

### Step 4 — Build and start

```bash
cd /opt/decsi_loan
docker compose up --build -d
docker compose ps
docker compose logs -f web
```

Wait until `db` is healthy and `web` is Up.

### Step 5 — Migrate and create superuser

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py check_license
```

### Step 6 — Open the surfaces

| Surface | URL |
|---------|-----|
| License status | `http://<host>:8000/license/` |
| Digital Apply | `http://<host>:8000/` |
| Staff hub | `http://<host>:8000/hub/login/` |
| Django Admin | `http://<host>:8000/admin/` |
| In-app Help | `http://<host>:8000/hub/help/` |

### Step 7 — Post-install configuration (functional go-live)

As superuser in the hub **Settings** (see Admin user manual):

1. Districts → Branches → geography  
2. Staff users + roles + branch/district  
3. Loan categories + document packs  
4. Approval committees  
5. Collateral / estimation mode  
6. Digital Apply open/fee/security  
7. MFA enrollment for privileged accounts  
8. SMTP for password reset (if used)

Optional Excel imports (templates in `docs/migration_templates/`):

```bash
docker compose exec web python manage.py import_migration_pack docs/migration_templates/DECSI_Migration_Pack.xlsx --default-password "ChangeMeNow!"
# or: import_districts, import_zones (geographic), import_branches, import_loan_categories, import_users, …
```

---

## 5. HTTPS for field tablets (optional)

Camera / GPS often require HTTPS:

```bash
./scripts/gen_field_https_certs.sh
docker compose -f docker-compose.yml -f docker-compose.https.yml up --build -d
```

Use `https://<any-current-server-ip>:8443`. The cert script discovers LAN addresses and covers each private /24 (DHCP). Do not bake a single IP into `SITE_URL` / `CSRF_TRUSTED_ORIGINS`. Re-run the script if the server moves to a new subnet.

---

## 6. Smoke test checklist (IT acceptance)

| # | Test | Expected |
|---|------|----------|
| 1 | `docker compose ps` | `web` Up, `db` healthy |
| 2 | `/license/` | Valid · correct org · future expiry |
| 3 | `/hub/login/` | Login form (not license blocked page) |
| 4 | Superuser login | Hub home |
| 5 | `/` | Digital Apply landing |
| 6 | Create staff loan | Queue ID issued |
| 7 | Upload document | Stored under media |
| 8 | Digital Apply mock fee → submit | Appears in Online loan intake |
| 9 | Restart | `docker compose restart` — data persists |

---

## 7. Backup and update

**Automatic (midnight)** — Compose service `backup` runs every night at **00:00 Africa/Addis_Ababa** and writes archives under `./backups/`:

```bash
docker compose up -d --build backup
docker compose logs -f backup
# Manual run now:
docker compose run --rm backup /scripts/run_backup.sh
```

Each archive contains Postgres (`database.dump` + `database.sql`) and uploaded files (`media.tar.gz`). Retention defaults to **14 days** (`BACKUP_RETENTION_DAYS`). See `deploy/backup/README.md`.

**Manual one-shot**

```bash
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > backup_$(date +%F).sql
# Or use the scheduled script above; also keep a secure offline copy of `.env` + license.key
```

**Update**

```bash
cd /opt/decsi_loan
# apply new release (git pull / unzip)
docker compose up -d --build
docker compose exec web python manage.py migrate
```

License keys survive updates if `.env` / `license.key` are preserved.

---

## 8. Troubleshooting

| Symptom | Action |
|---------|--------|
| Page says “Product license inactive” | Check `LICENSE_KEY`, expiry, then `check_license` |
| `DisallowedHost` | Add host to `ALLOWED_HOSTS` |
| MFA codes fail | Fix server NTP / timezone |
| DB connection errors | Confirm `DB_HOST=db`, password, `docker compose logs db` |
| Need renewal | Email Seqela with org code + desired expiry |

---

## 9. Support contacts

| Role | Contact |
|------|---------|
| Seqela product / license renewal | Your Seqela account manager (request renewal key with desired expiry) |
| DECSI IT operations | Local Dedebit technical team |

---

## Document control

| Item | Value |
|------|--------|
| Customer | Dedebit Credit and Savings Institution (DECSI) |
| Product | AI-powered Credit Intelligence / Loan Hub |
| Install | Docker Compose on-premises |
| License | `SEQLA1` Ed25519-signed key with expiry + grace |
| Companion | `docs/user_manual/06_installation_it.md`, user manuals PDF |
