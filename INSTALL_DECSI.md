# DECSI / Dedebit — quick install (from GitHub)

**Repo:** https://github.com/habenkiros/decsi_loan  

You need a Linux server with **Docker Engine 24+**, **Docker Compose v2**, and **Git**. Minimum: 2 vCPU · 4 GB RAM · 40 GB disk.

---

## Fast path (recommended)

```bash
git clone https://github.com/habenkiros/decsi_loan.git
cd decsi_loan
chmod +x scripts/install_decsi.sh
./scripts/install_decsi.sh
```

The script will:

1. Create a secure `.env` (if missing)  
2. Install the **license key** (from `LICENSE_KEY` env, or `deploy/license/license.key`, or the evaluation key in `docs/deployment/`)  
3. `docker compose up --build -d`  
4. Run database migrations  
5. Optionally create a superuser  

Then open:

| Page | URL |
|------|-----|
| Staff login | `http://<server-ip>:8000/hub/login/` |
| Digital Apply | `http://<server-ip>:8000/` |
| License | `http://<server-ip>:8000/license/` |

---

## License key

**Evaluation (this release):** 7-day key — see `docs/deployment/DEDEbit_LICENSE_KEY_7DAY.txt`  
**After agreement:** Seqela sends a Year‑1 `SEQLA1.…` key. Put it in `.env`:

```bash
LICENSE_KEY=SEQLA1.xxxxx.yyyyy
docker compose restart web
```

Or:

```bash
echo 'SEQLA1.xxxxx.yyyyy' > deploy/license/license.key
docker compose restart web
```

---

## Already cloned?

```bash
cd decsi_loan
git pull
./scripts/install_decsi.sh
```

If `.env` already exists, the script **does not overwrite** it.

---

## Non-interactive (automation)

```bash
export LICENSE_KEY='SEQLA1.…'
export NONINTERACTIVE=1
export CREATE_SUPERUSER=0
./scripts/install_decsi.sh
docker compose exec -it web python manage.py createsuperuser
```

---

## More detail

- Full on-prem guide: [`docs/deployment/DEDEBIT_ON_PREM_INSTALLATION.md`](docs/deployment/DEDEBIT_ON_PREM_INSTALLATION.md)  
- IT manual: [`docs/user_manual/06_installation_it.md`](docs/user_manual/06_installation_it.md)  
- HTTPS for field tablets: `./scripts/gen_field_https_certs.sh` then compose HTTPS overlay  

---

## Support

License / install issues → Seqela · quote your server hostname and `/license/` status.
