# Screenshot capture notes

Screenshots used in the manuals are **embedded next to the steps** in Admin, Staff, Customers, and Market chapters — not as a separate picture book.

PNG files live in `docs/user_manual/screenshots/`.

## Refresh captures

With the app on port 8000 and Chrome installed:

```bash
node docs/user_manual/capture_manual_shots.js
# optional fixups:
node docs/user_manual/capture_manual_shots_fixup.js

docker compose exec web python docs/user_manual/build_pdf.py
```

| Audience | Typical IDs |
|----------|-------------|
| Customers | C-01 … C-09, C-11, C-13 |
| Staff | H-01, H-04, H-07–H-09, H-15, H-18, H-19, H-23 |
| Market | M-01 |

Missing IDs (e.g. MFA H-02, document pack H-20, closing pack H-24) are caption placeholders until captured on a demo site.
