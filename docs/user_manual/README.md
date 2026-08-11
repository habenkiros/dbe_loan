# DECSI Loan Hub — User Manuals

Practical guides for people who use **DECSI Loan Hub** (staff brand: *AI-powered Credit Intelligence*) and the public **Digital Apply** portal.

| Manual | Who it is for | Start here |
|--------|---------------|------------|
| [Admin](01_admin.md) | System administrators & superusers who configure the platform | Hub **Settings**, users, security, Digital Apply |
| [Staff](02_staff.md) | Branch, district, head-office, engineering, finance, and committee users | Hub login at `/hub/login/` |
| [Customers](03_customers.md) | Borrowers applying online | Digital Apply at `/` |

---

## Which portal am I on?

| Audience | URL (typical) | Sign-in with |
|----------|---------------|--------------|
| Staff & admin | `/hub/login/` | Staff username & password (+ MFA if required) |
| Customers | `/` (Digital Apply) | Mobile number or customer number & password |
| Market price reporters *(optional)* | `/market-portal/` | Dealer / actor portal account |

Legacy bookmarks: `/staff/` redirects to the hub; `/applicant-portal/` redirects to Digital Apply.

---

## Product at a glance

```text
Customer (Digital Apply)          Staff hub                     Admin
─────────────────────────         ──────────────────────        ─────────────────
Register → Apply → Fee            Intake → Docs → Appraisal     Users & geography
→ Submit → Track status           → Collateral → Committee      Loan categories
                                  → Post-approval → Disburse    Document packs
                                                                Digital Apply settings
                                                                Committees & policies
```

Every submitted loan gets a **Queue ID** (for example `HK-000000001`). Customers and staff should use that ID for branch follow-up.

---

## Glossary (shared)

| Term | Meaning |
|------|---------|
| **Queue ID** | Unique loan reference shown to customers and staff |
| **Loan category / product** | Loan type (drives documents and appraisal style) |
| **Document pack** | Required and optional documents for a product |
| **Digital Apply** | Public online application portal |
| **Online loan intake** | Staff list of applications that came from Digital Apply |
| **Processing fee** | Application fee paid online (ETB) before submit |
| **Cooperative queue** | Branch intake gate before officer work |
| **Approval queue** | Credit committee voting worklist |
| **Post-approval** | Conditions, schedule, and readiness after committee approval |
| **Disbursement queue** | Finance steps before funds are released |
| **Appraisal** | Structured credit analysis (usually 7 steps) |
| **Collateral** | Security valuation (building, land, or other) |
| **Agentic Assist** | Staff AI helper — cannot approve or disburse |

---

## Support

For account lockouts, MFA, or portal outages, contact your DECSI IT / hub administrator. Customers should visit or call their branch with their Queue ID.
