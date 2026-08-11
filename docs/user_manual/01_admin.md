# Admin User Manual

**Audience:** Super Administrators and System Administrators who configure DECSI Loan Hub.  
**Entry:** Staff hub → `/hub/login/` (Django Admin also available at `/admin/` for data maintenance).

This guide covers day-to-day **configuration** and **oversight**. Operational lending steps are in the [Staff manual](02_staff.md). Customer-facing steps are in the [Customer manual](03_customers.md).

---

## 1. Your role

| Role | What you typically do |
|------|------------------------|
| **Super Administrator** (`superadmin`) / Django **superuser** | Full **Settings** menu: geography, users, loan products, document packs, Digital Apply, committees, collateral policy, estimation mode |
| **System Administrator** (`admin`) | Oversight, checkup views, unlock users (with IT), security audit when permitted |

Menus are role-scoped. If you do not see **Settings**, ask for a superuser account or elevated role.

---

## 2. Sign in and security

### 2.1 Sign in

1. Open `/hub/login/`.
2. Enter your **username** and **password**.
3. If MFA is enabled for your account (or required by policy), open your authenticator app and enter the one-time code at `/hub/mfa/verify/`.

> **Screenshot (H-01):** Staff login — enter username and password for AI-powered Credit Intelligence.
>
> **Screenshot (H-02):** MFA verify — enter the one-time code from your authenticator app.

### 2.2 First-time MFA enrollment

1. After password login (or from security settings), open **MFA setup** (`/hub/mfa/setup/`).
2. Scan the QR code with an authenticator app (Google Authenticator, Microsoft Authenticator, etc.).
3. Confirm with a code from the app.
4. Store recovery practices per DECSI IT policy.

### 2.3 Password

| Need | Where |
|------|--------|
| Forgot password | `/hub/password-reset/` (email token — SMTP must be configured) |
| Change while logged in | `/hub/password-change/` |

### 2.4 Lockouts

Repeated failed logins can lock an account. Unlock from the user edit screen or the unlock action (allowed for admin / VP IT / superuser). Review related events in the **security audit** log.

### 2.5 Security audit

Roles such as admin, auditor, risk & compliance, VP IT, and superuser can open:

- **Audit log:** `/hub/security/audit/`
- **Export:** `/hub/security/audit/export/` (CSV / Excel)

Use this for investigations (failed logins, MFA events, unlocks).

---

## 3. Hub Settings (configuration checklist)

Open the **Settings** dropdown in the hub navigation (superuser). Configure in roughly this order for a new branch or institution go-live:

> **Screenshot (H-19):** Digital Apply settings — open/close portal, fee, and security controls.
>
> **Screenshot (H-20):** Document pack — required and optional docs for one loan category.

```text
1. Districts → Branches → Departments (if HO)
2. Area: Regions → Zones → Cities (Woredas)
3. Users (assign role, branch/district, optional department)
4. Loan categories (products)
5. Document types (global catalog)
6. Document pack per category
7. Approval committees
8. Collateral types, policy, estimation config
9. Digital Apply (open/close, fee, security)
10. Spot-check Online loan intake
```

### 3.1 Geography and organisation

| Setting | Purpose |
|---------|---------|
| **Districts / Branches** | Scope who sees which loans and reports |
| **Departments** | Head-office Cooperative, Finance, Credit, Management, Board |
| **Regions / Zones / Cities (Woredas)** | Location hierarchy used for collateral pricing and market area |

Bulk CSV upload options exist for zones, branches, categories, users, and related data where enabled in the UI.

### 3.2 Users

1. Open **Users** from Settings (or manage-users screens).
2. Create or edit a staff user.
3. Set:
   - **Role** (branch manager, loan officer, finance manager, etc.)
   - **Branch** and/or **district**
   - **Department** for HO users when needed
4. Communicate temporary password and require change on first login if that is your policy.
5. Encourage or enforce MFA enrollment.

Do **not** create borrower accounts here — customers register in Digital Apply as applicant accounts.

### 3.3 Loan categories (products)

**Settings → Loan categories**

- Create/edit products customers and staff select at intake.
- Each category drives **document pack** and **appraisal mode** (MSME vs corporate, as configured).
- Keep names clear for both staff and Digital Apply applicants.

### 3.4 Document types and packs

**Two layers:**

1. **Document types & authentication** — global catalog of document kinds, OCR/auth rules, reference samples.
2. **Document pack per category** — Settings → open a category → **Document pack**  
   Mark each type **required** or **optional** and set display order.

Digital Apply and staff document screens both use the pack for the selected product. After changing packs, test one online draft and one staff loan.

### 3.5 Approval committees

**Settings → Approval committees**

- Define who votes at each level.
- Align members with amount thresholds and tie-breaker rules used by your credit policy.
- Credit Department Head and admins typically maintain this.

### 3.6 Collateral configuration

| Screen | Purpose |
|--------|---------|
| **Collateral types** | Types available on requests |
| **Collateral field-work policy** | Field visit / evidence rules |
| **Estimation config** *(superadmin)* | Whether loan officers, engineering, or both value collateral |
| **Unlock queue** | Approve unlocks when a locked valuation must be corrected |
| **Catalog / unit prices** | Maintained mainly by engineering roles; admins oversee consistency |

### 3.7 Digital Apply

**Settings → Digital apply** (superuser)

Typical controls:

| Control | Effect |
|---------|--------|
| Portal open / closed | When closed, applicants see “Digital apply is temporarily closed” |
| Processing fee (ETB) | Amount charged before submit |
| Password / lockout / rate limits | Applicant account security |
| Idle session minutes | Applicant session timeout |
| Terms text | Shown at registration / apply |
| Require CBS customer lookup | When enabled, registration validates customer number against core banking |
| Chapa status | Live vs mock/demo payment mode (environment-driven; shown for operators) |

After go-live, use **Online loan intake** to confirm applications appear for branch staff.

---

## 4. Day-to-day admin tasks

### 4.1 Open or close Digital Apply

1. Settings → **Digital apply**.
2. Toggle portal availability.
3. Notify branches before closing (applicants cannot finish new submissions).

### 4.2 Adjust processing fee

1. Settings → **Digital apply**.
2. Update fee in ETB.
3. Confirm a test payment in mock mode (if available) before relying on live Chapa.

### 4.3 Add a new loan product

1. Create **Loan category**.
2. Attach **Document pack** (required/optional docs).
3. Ensure committees and appraisal expectations cover the product.
4. If Digital Apply should offer it, confirm the category is active/selectable online.

### 4.4 Onboard a branch

1. Create district (if new) → branch.
2. Create users (BM, cooperative manager, LOs, accountant as needed).
3. Assign committee membership if the branch participates.
4. Verify unit prices / woredas for that geography if collateral is used.

### 4.5 Investigate a locked user

1. Open the user record.
2. Confirm lockout reason via **Security audit**.
3. Unlock if policy allows.
4. Advise password reset and MFA check.

### 4.6 Monitor online applications

**Settings → Online loan intake** (or hub online intake screen)

- See drafts and submitted Digital Apply loans.
- Coordinate with branch managers if intake is stuck.

---

## 5. Django Admin (`/admin/`)

Use Django Admin for advanced data maintenance (models, flags, one-off corrections). Prefer hub **Settings** UIs for routine configuration so audits and validation stay consistent.

Common admin areas:

- Loan requests, categories, document requirements  
- Committees and votes  
- Applicant portal settings, accounts, online applications  
- Security / auth-related records as registered  

Treat Admin changes as privileged: log why you changed a record.

---

## 6. Environment and payment notes (for IT admins)

These are usually set in deployment (`.env`), not only in the UI:

| Topic | Notes |
|-------|--------|
| MFA required | Forces staff MFA when policy demands it |
| Login lockout | Max failed attempts and lock duration |
| Session idle | Staff idle timeout (if middleware enabled in deployment) |
| Email (SMTP) | Required for staff password reset |
| Chapa keys | Live vs mock Digital Apply payments |
| Applicant SMS | OTP for customer password reset |

Coordinate with DevOps before changing production secrets.

---

## 7. Admin quick reference

| Task | Navigation |
|------|------------|
| Manage products | Settings → Loan categories |
| Document catalog | Settings → Document types |
| Product checklist | Category → Document pack |
| Committees | Settings → Approval committees |
| Portal fee / open | Settings → Digital apply |
| Online apps | Settings → Online loan intake |
| Collateral rules | Settings → Collateral policy / Estimation config |
| Audit | `/hub/security/audit/` |
| Unlock user | Edit user → unlock |
| Low-level data | `/admin/` |

---

## 8. Related manuals

- [Staff user manual](02_staff.md) · [አማርኛ](02_staff_am.md)  
- [Customer user manual](03_customers.md) · [አማርኛ](03_customers_am.md)  
- [Market partners](04_market_partners.md)  
- [Screenshot captions](05_screenshot_captions.md)  
- [Manual index](README.md) · [Printable HTML pack](DECSI_Loan_Hub_User_Manuals.html)  
- In-app: `/hub/help/`

