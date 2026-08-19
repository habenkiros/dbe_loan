# Admin User Manual

**Audience:** Super Administrators and System Administrators who configure DECSI Loan Hub.  
**Entry:** Staff hub → `/hub/login/` (Django Admin also available at `/admin/` for data maintenance).

This guide covers day-to-day **configuration** and **oversight**. Operational lending steps are in the [Staff manual](02_staff.md). Customer-facing steps are in the [Customer manual](03_customers.md).

---

## 1. Your role

| Role | What you typically do |
|------|------------------------|
| **Super Administrator** (`superadmin`) / Django **superuser** | Full **Settings** menu: geography, users, loan products, document packs, Digital Apply, committees, collateral policy, estimation mode; **approve/reject authority delegations** |
| **System Administrator** (`admin`) | Oversight, checkup views, unlock users (with IT), security audit when permitted; **approve/reject authority delegations** |

Menus are role-scoped. If you do not see **Settings**, ask for a superuser account or elevated role. All staff see **Delegations** in the hub nav.

---

## 2. Sign in and security

### 2.1 Sign in

1. Open `/hub/login/`.
2. Enter your **username** and **password**.
3. If MFA is enabled for your account (or required by policy), open your authenticator app and enter the one-time code at `/hub/mfa/verify/`.

> **Screenshot (H-01):** Staff login — enter username and password for AI-powered Credit Intelligence.
>
> ![H-01 — Staff hub login](screenshots/H-01_hub_login.png)
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

Staff and Digital Apply applicants use **separate** lockout / auth-event stores. Disabling MFA (if allowed): `/hub/mfa/disable/`. Sessions may use idle timeout with keepalive (`/hub/session/keepalive/`).

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
> ![H-19 — Digital Apply settings](screenshots/H-19_digital_apply_settings.png)
>
> **Screenshot (H-20):** Document pack — required and optional docs for one loan category (capture on your site if not yet filed).

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

Digital Apply and staff document screens both use the pack for the selected product. If a category has **no pack**, the system falls back to the global document catalog (filtered by appraisal mode). After changing packs, test one online draft and one staff loan.

Staff can also **Request document** on a loan (type from the pack) so the branch manager is notified to upload a missing file.

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
| Processing fee (ETB) | Amount charged before submit; **0 ETB** auto-waives payment |
| Password rules | Length and character requirements for applicant passwords |
| Max failed logins / lockout minutes | Applicant account lockout |
| Register rate limit (per IP / hour) | Limits new registrations from one IP |
| Idle session minutes | Applicant session timeout |
| Require terms acceptance | Checkbox at registration (terms wording is fixed in the UI) |
| Require CBS customer lookup | Validates customer number against core banking when enabled |
| Chapa status | Live vs mock/demo payment mode (environment-driven; shown for operators) |

After go-live, use **Online loan intake** to confirm applications appear for branch staff.

### 3.8 Authority delegation (approve as admin)

Staff can request a colleague to cover selected powers (**Delegations** in the hub nav → `/hub/delegations/`).

1. A staff user creates a request (principal, delegate, scopes, date window, reason).  
2. Status stays **Pending** until an **admin / superadmin** **Approves** or **Rejects**.  
3. While approved and inside the window, the delegate may act; actions are audited as *acted by delegate for principal*.  
4. Principal or admin can **Revoke** early.

Scopes that can be delegated (only powers the principal already holds):

- Committee voting  
- Cooperative intake approval  
- Loan officer appraisal / documents  
- Finance disbursement approval  
- Assign loan officer  

Admins see a banner when requests await approval.

> **Screenshot (H-23):** Delegations — pending approval list and Approve / Reject actions.
>
> ![H-23 — Delegations](screenshots/H-23_delegations.png)

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

**Settings → Online loan intake** (`/hub/online_loan_intake/` — nav under Settings for superuser)

- Lists **submitted** Digital Apply loans and **open drafts**.  
- Search by Queue ID, name, phone, or customer number.  
- Non-HO roles are branch-scoped when they open the page.  
- Submitted apps mint a `LoanRequest` with **source channel = online**.  
- On submit, the system may **auto-assign** the first active loan officer at the branch (else the branch manager).  
- Branch staff also receive **Notifications** (`online_intake`) when a customer submits.

Coordinate with branch managers if intake is stuck.

### 4.7 Approve or reject a delegation

1. Open **Delegations** (or use the pending-approval banner).  
2. Review principal, proposed delegate, scopes, and window.  
3. **Approve** or **Reject**.  
4. Confirm the delegate sees “Acting by delegation” after approval.

### 4.8 Post-approval closing pack (awareness)

Closing requirements are set **per loan** on the post-approval workspace (not a global Settings switch):

- Government **Collateral Restriction**, optional **Power of Attorney**, title / mortgage / notary papers  
- **Digital loan agreement** signatures (borrower + officer; optional guarantor / BM)  

These gate finance readiness. Train branch staff using the [Staff manual §4.7](02_staff.md). Prefer hub post-approval UIs over raw Django Admin edits for legal documents and agreements.

---

## 5. Django Admin (`/admin/`)

Use Django Admin for advanced data maintenance (models, flags, one-off corrections). Prefer hub **Settings** UIs for routine configuration so audits and validation stay consistent.

Common admin areas:

- Loan requests, categories, document requirements  
- Committees and votes  
- Post-approval legal papers / agreements (prefer hub closing pack UI)  
- Applicant portal settings, accounts, online applications, applicant notices  
- Market actors, observations, price bands (Seqela Market)  
- Staff delegations (if registered)  
- Security / auth-related records as registered  

Treat Admin changes as privileged: log why you changed a record.

---

## 6. Environment and payment notes (for IT admins)

These are usually set in deployment (`.env`), not only in the UI:

| Topic | Notes |
|-------|--------|
| MFA / lockout / idle | Staff auth hardening (see IT manual and deployment settings) |
| Email (SMTP) | Required for staff password reset |
| Chapa keys | Live vs mock Digital Apply payments (`CHAPA_*`, `CHAPA_FORCE_MOCK`) |
| Applicant SMS | OTP / status SMS gateway (`APPLICANT_SMS_*`) |
| Market bands | Periodic `recompute_market_bands` for price bands |

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
| Delegations | Hub → Delegations |
| Collateral rules | Settings → Collateral policy / Estimation config |
| Audit | `/hub/security/audit/` |
| Unlock user | Edit user → unlock |
| In-app Help / PDF | `/hub/help/` |
| Low-level data | `/admin/` |

---

## 8. Related manuals

- [Staff user manual](02_staff.md)  
- [Customer user manual](03_customers.md)  
- [Market partners](04_market_partners.md)
- [Manual index](README.md) · [Printable HTML pack](DECSI_Loan_Hub_User_Manuals.html)
- In-app: `/hub/help/`

