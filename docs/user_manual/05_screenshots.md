# Screenshots

Real UI captures from DECSI Loan Hub used in this manual pack. Files live in `docs/user_manual/screenshots/`.

## Digital Apply (customers)

![C-01 — Digital Apply landing](screenshots/C-01_landing.png)

![C-02 — Create account / register](screenshots/C-02_register.png)

![C-03 — Customer sign-in](screenshots/C-03_login.png)

![C-11 — Digital Apply Help](screenshots/C-11_help.png)

## Staff hub

![H-01 — Staff hub login](screenshots/H-01_hub_login.png)

## Seqela Market

![M-01 — Market portal (share a local price)](screenshots/M-01_market.png)

## How to refresh captures

With the app running on port 8000:

```bash
mkdir -p docs/user_manual/screenshots
cd docs/user_manual/screenshots
google-chrome --headless --disable-gpu --no-sandbox --window-size=1280,900 \
  --screenshot=C-01_landing.png http://127.0.0.1:8000/
# …repeat for other URLs
docker compose exec web python docs/user_manual/build_pdf.py
```

| ID | URL | File |
|----|-----|------|
| C-01 | `/` | `C-01_landing.png` |
| C-02 | `/register/` | `C-02_register.png` |
| C-03 | `/login/` | `C-03_login.png` |
| C-11 | `/help/` | `C-11_help.png` |
| H-01 | `/hub/login/` | `H-01_hub_login.png` |
| M-01 | `/market-portal/` | `M-01_market.png` |
