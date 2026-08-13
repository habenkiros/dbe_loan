# DECSI Loan Hub — Installation Manual for IT Staff

**Audience:** DECSI IT / infrastructure staff installing or upgrading the Loan Hub.  
**Goal:** Bring up a working stack with the **minimum requirements**, then harden for pilot / production.

End-user operations (admin / staff / customers) are in the [user manuals index](README.md).  
This document covers **install, configure, verify, backup**.

---

## 1. What you are installing

| Component | Role |
|-----------|------|
| **Web app** (Django) | Staff hub (`/hub/`), Digital Apply (`/`), Market portal (`/market-portal/`), optional Django Admin (`/admin/`) |
| **PostgreSQL 16** | Primary database |
| **Media volume** | Uploaded documents, photos, OCR inputs |
| **Optional nginx HTTPS** | Secure context for field tablets (GPS / camera) on LAN |

**Recommended path:** Docker Compose (includes Python 3.9, Tesseract eng+amh, poppler, WeasyPrint libs).

---

## 2. Minimum requirements

### 2.1 Server (pilot / single-site minimum)

| Resource | Minimum | Recommended (branch pilot+) |
|----------|---------|------------------------------|
| CPU | 2 vCPU | 4 vCPU |
| RAM | **4 GB** | 8 GB |
| Disk | **40 GB** free SSD | 100 GB+ (media grows with scans/photos) |
| OS | Linux x86_64 (Ubuntu 22.04 LTS or RHEL 8/9 equivalent) | Same |
| Network | LAN access to staff PCs; outbound HTTPS for updates / Chapa / CBS if used | Static IP or DNS name |

> These are **application** minimums. Size disk for expected document volume (loan packs + collateral photos).

### 2.2 Client workstations (staff)

| Item | Minimum |
|------|---------|
| Browser | Current Chrome, Edge, or Firefox |
| Display | 1280×720 (1920×1080 preferred for appraisal / collateral) |
| Network | Reach server on ports below |

Field tablets using GPS/camera need **HTTPS** (see §6).

### 2.3 Software prerequisites (Docker path — preferred)

| Software | Minimum version |
|----------|-----------------|
| Docker Engine | 24+ |
| Docker Compose | v2 (`docker compose`) |
| Git | 2.x (to obtain / update the codebase) |

Host does **not** need a separate Python/PostgreSQL install when using Compose.

### 2.4 Software prerequisites (non-Docker / bare metal)

| Software | Minimum |
|----------|---------|
| Python | **3.9** (3.9.x) |
| PostgreSQL | **16** |
| pip / venv | Matching Python |
| Tesseract OCR | With **eng** + **amh** language packs |
| poppler-utils | For PDF→image |
| WeasyPrint deps | Pango, Cairo, GDK-Pixbuf, shared-mime-info, DejaVu fonts |

### 2.5 Ports

| Port | Service | Notes |
|------|---------|--------|
| **8000/tcp** | Web (HTTP) | Default Compose mapping |
| **5432/tcp** | PostgreSQL | Bind to localhost / Docker network only in production |
| **8443/tcp** | HTTPS proxy | Only if using `docker-compose.https.yml` |

Firewall: allow staff → 8000 (or 8443); do **not** expose PostgreSQL to the internet.

### 2.6 Accounts and secrets you must prepare

| Item | Notes |
|------|--------|
| `SECRET_KEY` | Long random Django secret (never reuse across environments) |
| `DB_PASSWORD` | Strong password for PostgreSQL |
| Superuser | Created after first migrate (`createsuperuser`) |
| SMTP (optional but needed for staff password reset) | Host, port, user, password |
| Chapa keys (optional) | Only if Digital Apply live payments |
| CBS / party API (optional) | Keep mock flags until DECSI core banking access is ready |

---

## 3. Pre-install checklist

- [ ] Server meets §2.1  
- [ ] Docker + Compose installed (`docker --version`, `docker compose version`)  
- [ ] Clock/NTP correct (important for MFA TOTP)  
- [ ] Hostname / DNS planned (`SITE_URL`, `ALLOWED_HOSTS`)  
- [ ] Backup location identified for DB + `media`  
- [ ] Release package or Git access available  

---

## 4. Installation (Docker Compose — recommended)

### 4.1 Obtain the application

```bash
cd /opt   # or your preferred path
# Example: git clone <DECSI-internal-repo-url> decsi_loan
cd decsi_loan
```

### 4.2 Create environment file

```bash
cp .env.example .env
```

Edit `.env` — **minimum required for a non-debug deploy**:

```bash
SECRET_KEY=<generate-a-long-random-value>
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1,<server-ip-or-hostname>
SITE_URL=http://<server-ip-or-hostname>:8000

DB_NAME=decsiloandb
DB_USER=decsiloandbuser
DB_PASSWORD=<strong-password>
DB_HOST=db
DB_PORT=5432
```

Generate `SECRET_KEY`:

```bash
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

(If Django is not on the host yet, generate any 50+ character random string, or run the same command after the image builds.)

**Auth hardening (recommended from first install):**

```bash
LOGIN_MAX_FAILED_ATTEMPTS=5
LOGIN_LOCKOUT_MINUTES=15
MFA_REQUIRED=True
MFA_TOTP_ISSUER=DECSI Loan Hub
SESSION_IDLE_TIMEOUT=1800
PASSWORD_MIN_LENGTH=10
```

**Keep mocks until integrations are ready:**

```bash
DECSI_CUSTOMER_FALLBACK_MOCK=True
DECSI_CBS_USE_MOCK_LEDGER=True
```

**Digital Apply payments & SMS (optional):**

```bash
# Live Chapa (leave empty + or set CHAPA_FORCE_MOCK=True for demo checkout)
CHAPA_SECRET_KEY=
CHAPA_PUBLIC_KEY=
CHAPA_CURRENCY=ETB
CHAPA_FORCE_MOCK=True

# Applicant OTP / status SMS gateway (optional)
APPLICANT_SMS_URL=
APPLICANT_SMS_API_KEY=
```

**OCR language (Docker image already includes eng+amh):**

```bash
DOCUMENT_OCR_LANG=eng+amh
```

Never commit `.env` to Git.

### 4.3 Build and start

```bash
docker compose up --build -d
```

Wait until `db` is healthy and `web` is running:

```bash
docker compose ps
docker compose logs -f web
```

### 4.4 Database migrate and superuser

Compose may already run migrations depending on entrypoint; always verify:

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

Follow prompts (username, email optional, password).

### 4.5 Open the application

| Surface | URL |
|---------|-----|
| Digital Apply (public) | `http://<host>:8000/` |
| Staff hub login | `http://<host>:8000/hub/login/` |
| Django Admin | `http://<host>:8000/admin/` |
| In-app Help (staff) | `http://<host>:8000/hub/help/` |

Sign in with the superuser, then create staff users and configure Settings (see [Admin user manual](01_admin.md)).

---

## 5. Installation (bare metal — optional)

Use only if Docker is not allowed.

1. Install PostgreSQL 16; create DB/user matching `.env`.  
2. Install system packages: Tesseract (`eng`, `amh`), poppler, Pango/Cairo stack (see Dockerfile for the package list).  
3. Python 3.9 venv:

```bash
python3.9 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

4. `.env` with `DB_HOST=127.0.0.1` (not `db`).  
5. Migrate, createsuperuser, then either:

```bash
python manage.py runserver 0.0.0.0:8000          # lab only
# or production-style:
python manage.py collectstatic --noinput
gunicorn decsi_loan.wsgi:application -c gunicorn.conf.py
```

Put nginx/Apache in front for TLS in production.

---

## 6. HTTPS for field tablets (optional overlay)

Browsers require a **secure context** for camera/GPS on many devices.

```bash
./scripts/gen_field_https_certs.sh
# optionally pass LAN IP: ./scripts/gen_field_https_certs.sh 192.168.x.x
docker compose -f docker-compose.yml -f docker-compose.https.yml up --build -d
```

- App via proxy: `https://<lan-ip>:8443`  
- Accept the self-signed certificate once (or install a bank-signed cert in `deploy/https/certs/`).  
- Set HTTPS-related env vars as documented in `.env.example` / `deploy/https/.env.https`.

---

## 7. Post-install configuration (minimum go-live)

Complete in hub **Settings** (superuser) or Admin:

1. Districts → Branches → geography (Regions / Zones / Cities)  
2. Staff users with correct **roles** and branch/district  
3. Loan categories + **document packs**  
4. Approval committees  
5. Collateral policy / estimation mode  
6. Digital Apply: open/closed, processing fee, password/lockout, CBS lookup, terms checkbox  
7. SMTP for staff password reset (if not set in `.env`)  
8. MFA enrollment for privileged accounts  
9. Confirm **Delegations** works (staff request → admin approve)  
10. If using Seqela Market, schedule `recompute_market_bands` (see §9.5)

CSV imports (optional):

```bash
docker compose exec web python manage.py import_zones <file>
docker compose exec web python manage.py import_branches <file>
docker compose exec web python manage.py import_loan_categories <file>
docker compose exec web python manage.py import_users <file>
```

---

## 8. Smoke test (IT acceptance)

| # | Test | Expected |
|---|------|----------|
| 1 | `docker compose ps` | `web` Up, `db` healthy |
| 2 | Open `/hub/login/` | Login form loads |
| 3 | Login as superuser | Hub home / Settings / **Delegations** visible |
| 4 | Open `/` | Digital Apply landing (or closed page if disabled) |
| 5 | `/hub/help/` | User manuals list; **Download PDF** if built |
| 6 | Create test loan (staff) | Queue ID issued |
| 7 | Upload a PDF/image document | File stored under media |
| 8 | (If MFA on) Setup + verify TOTP | Login succeeds with code |
| 9 | Digital Apply fee (mock) | Mock/waived fee path reaches Submit |
| 10 | Submit online app | Appears in Online loan intake + staff Notification |
| 11 | `/market-portal/` | Guest price quote saves |
| 12 | Restart stack | `docker compose restart` — data persists |
| 13 | Migrations | Includes loan delegation (`0064`–`0066`) and applicant portal latest |

---

## 9. Day-2 operations

### 9.1 Useful commands

```bash
docker compose ps
docker compose logs -f web
docker compose logs -f db
docker compose restart web
docker compose down          # stop (keeps volumes)
docker compose up -d --build # start / rebuild after code update
```

### 9.2 Backup (minimum)

| What | How |
|------|-----|
| Database | `docker compose exec -T db pg_dump -U $DB_USER $DB_NAME > backup_$(date +%F).sql` |
| Media files | Backup Docker volume `media_data` or `/app/media` bind path |
| Config | Keep a secure offline copy of `.env` (not in Git) |

Restore DB only after stopping writers; test restore on a non-prod host first.

### 9.3 Update / upgrade

```bash
cd /opt/decsi_loan
git pull   # or extract new release
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py collectstatic --noinput   # if using gunicorn entrypoint
```

After upgrades that change manuals:

```bash
docker compose exec web python docs/user_manual/build_pdf.py
```

### 9.4 Default Gunicorn sizing (production image/entrypoint)

From `gunicorn.conf.py` (override via env):

| Variable | Default |
|----------|---------|
| `GUNICORN_WORKERS` | 3 |
| `GUNICORN_THREADS` | 2 |
| `GUNICORN_TIMEOUT` | 120 |
| `GUNICORN_BIND` | `0.0.0.0:8000` |

On a 4 GB host, do not raise workers aggressively without more RAM.

### 9.5 Market price bands (optional)

If Seqela Market is used for local quotes that feed collateral reference prices:

```bash
docker compose exec web python manage.py recompute_market_bands
```

Schedule this periodically (cron) after go-live. Manage actors / trust in Django Admin.

---

## 10. Security baseline for DECSI IT

- [ ] `DEBUG=False` in every non-lab environment  
- [ ] Strong unique `SECRET_KEY` and `DB_PASSWORD`  
- [ ] PostgreSQL not published to public internet  
- [ ] `ALLOWED_HOSTS` and `SITE_URL` match real hostname  
- [ ] `MFA_REQUIRED=True` for staff (or phased enrollment)  
- [ ] HTTPS for any internet-facing or tablet field use  
- [ ] Restrict `/admin/` to admin roles / VPN  
- [ ] Regular DB + media backups with restore drills  
- [ ] Keep OS and Docker images patched  

See also `docs/INSA_SECURITY_CLEARANCE_CHECKLIST.md` for security control mapping.

---

## 11. Troubleshooting

| Symptom | Check |
|---------|--------|
| `web` restarts / cannot connect DB | `DB_HOST=db`, password match, `docker compose logs db` |
| 400 Bad Request / DisallowedHost | Add host to `ALLOWED_HOSTS` |
| Static/CSS missing (prod) | Run `collectstatic`; confirm reverse proxy static config |
| OCR / PDF features fail | Confirm Tesseract eng+amh inside container (`tesseract --list-langs`) |
| Staff password reset email never arrives | Configure SMTP env vars; check mail logs |
| MFA codes rejected | Server time/NTP skew |
| Out of disk | Media volume growth; archive old uploads |
| Port 8000 in use | Set `WEB_PORT=8080` in `.env` / Compose |

---

## 12. URL quick reference

| Path | Purpose |
|------|---------|
| `/` | Digital Apply |
| `/hub/login/` | Staff login |
| `/hub/` | Staff hub |
| `/hub/help/` | In-app manuals (staff) + PDF download |
| `/hub/delegations/` | Authority delegation |
| `/hub/online_loan_intake/` | Digital Apply intake list |
| `/admin/` | Django Admin |
| `/market-portal/` | Market price portal |
| `/collateral/` | Collateral module (staff auth) |
| `/payments/chapa/webhook/` | Chapa payment webhook (must be reachable when live) |

---

## 13. Related documents

| Document | Use |
|----------|-----|
| [Admin user manual](01_admin.md) | Configure products, users, Digital Apply |
| [Staff user manual](02_staff.md) | Day-to-day lending operations |
| [INSA security checklist](../INSA_SECURITY_CLEARANCE_CHECKLIST.md) | Security clearance controls |
| `.env.example` | Full environment variable template |
| Project `README.md` | Architecture and developer reference |

---

## Document control

| Item | Value |
|------|--------|
| Product | DECSI Loan Hub / AI-powered Credit Intelligence |
| Audience | DECSI IT staff |
| Install path | Docker Compose (preferred) |
| Min server | 2 vCPU · 4 GB RAM · 40 GB SSD · Linux · Docker 24+ |
