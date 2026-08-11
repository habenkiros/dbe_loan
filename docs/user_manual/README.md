# DECSI Loan Hub — User Manuals

Practical guides for **DECSI Loan Hub** (*AI-powered Credit Intelligence*), **Digital Apply**, and **Seqela Market**.

| Manual | Who it is for | In-app Help |
|--------|---------------|-------------|
| [Admin](01_admin.md) · [አማርኛ](01_admin_am.md) | System administrators | Hub → **Help** (`/hub/help/`) |
| [Staff](02_staff.md) · [አማርኛ](02_staff_am.md) | Branch / HO / eng / finance / committee | Hub → **Help** |
| [Customers](03_customers.md) · [አማርኛ](03_customers_am.md) | Borrowers applying online | Digital Apply → **Help** (`/help/`) |
| [Market partners](04_market_partners.md) | Dealers & price reporters | Market → **Help** (`/market-portal/help/`) |
| [Screenshot captions](05_screenshot_captions.md) | Trainers / doc authors | Hub Help (staff) |
| [IT installation](06_installation_it.md) | DECSI IT — install & minimum requirements | Hub → **Help** |

**Printable pack:** [DECSI_Loan_Hub_User_Manuals.html](DECSI_Loan_Hub_User_Manuals.html) → browser **Print → Save as PDF**.

```bash
python3 docs/user_manual/build_html.py
```

---

## Which portal am I on?

| Audience | URL | Sign-in |
|----------|-----|---------|
| Staff & admin | `/hub/login/` | Staff username & password (+ MFA) |
| Customers | `/` | Mobile or customer number & password |
| Market reporters | `/market-portal/` | Portal account or guest quote |

Legacy: `/staff/` → hub; `/applicant-portal/` → Digital Apply.

---

## Product at a glance

```text
Customer (Digital Apply)          Staff hub                     Admin
Register → Apply → Fee            Intake → Docs → Appraisal     Users & geography
→ Submit → Track Queue ID         → Collateral → Committee      Document packs
                                  → Post-approval → Disburse    Digital Apply settings

Market (Seqela Market): Area → Product & price → price bands
```

---

## Glossary (shared)

| Term | Meaning |
|------|---------|
| **Queue ID** | Unique loan reference (`HK-…`) |
| **Loan category / product** | Loan type (docs + appraisal mode) |
| **Document pack** | Required/optional docs for a product |
| **Digital Apply** | Public online application |
| **Processing fee** | Application fee (ETB) |
| **Cooperative queue** | Branch intake gate |
| **Approval queue** | Committee voting |
| **Post-approval** | Conditions → schedule → ready |
| **Agentic Assist** | Staff AI helper (cannot approve/disburse) |
| **Seqela Market** | External price quotes |

---

## Support

Lockouts / MFA / outages → DECSI IT. Customers → branch with Queue ID. Market actors → DECSI liaison if suspended.
