# Seqela on-prem license keys

## Customer (Dedebit / DECSI)

1. Receive a `SEQLA1.…` key from Seqela.  
2. Set `LICENSE_KEY` in `.env` **or** write the key to `deploy/license/license.key`.  
3. Restart: `docker compose restart web`.  
4. Verify: `python manage.py check_license` or open `/license/`.

See `docs/deployment/DEDEBIT_ON_PREM_INSTALLATION.md`.

## Seqela (issue / renew)

Private key path (never ship to the customer):

- `deploy/license/private_key.pem` (gitignored), or  
- `LICENSE_PRIVATE_KEY_PEM` / `LICENSE_PRIVATE_KEY_PATH`

Issue a 1-year Dedebit license:

```bash
docker compose exec web python manage.py issue_license \
  --org "Dedebit Credit and Savings Institution" \
  --org-code DECSI \
  --expires 2027-08-19 \
  --note "Year-1 on-prem license" \
  --write deploy/license/license.key
```

Issue a 90-day pilot:

```bash
docker compose exec web python manage.py issue_license \
  --org "Dedebit Credit and Savings Institution" \
  --org-code DECSI \
  --expires 2026-11-19 \
  --note "90-day pilot"
```

Copy the printed `SEQLA1.…` line into the customer’s `.env`.
