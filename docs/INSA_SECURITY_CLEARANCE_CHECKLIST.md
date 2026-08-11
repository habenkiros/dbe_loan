# INSA Security Clearance — Evidence Checklist

**Product:** DECSI Loan Hub (staff loan origination / credit operations)  
**Deployment model:** One independent instance per bank or MFI (not multi-tenant SaaS)  
**Purpose:** Map INSA-style security expectations to this codebase and hosting controls so a bank can prepare clearance evidence.

> This checklist does **not** grant clearance. INSA / bank security teams decide after review, VAPT, and hosting assessment.

---

## 1. Application identity & scope

| Item | Evidence in this repo / ops |
|------|-----------------------------|
| System purpose | `README.md` — loan hub for secured MSME/corporate credit ops |
| In-scope users | Authenticated `CustomUser` staff (branch / HO roles) |
| Out of scope (today) | Live CBS (mock allowed until bank credentials); digital-lending score API |
| Data classes | Loan applications, KYC docs, collateral photos/GPS, appraisals, committee votes, security audit events |

---

## 2. Authentication & access control

| Control | Status | Code / config |
|---------|--------|---------------|
| Unique staff accounts + roles | Done | `loans.models.CustomUser.role` + view `@user_passes_test` |
| Strong passwords | Done | `PASSWORD_MIN_LENGTH` (default 10) + Django validators |
| MFA (TOTP) | Done | `loans/auth_views.py`, `MFA_REQUIRED` (default on when `DEBUG=False`) |
| Login lockout (user + IP) | Done | `loans/security.py`, `LOGIN_MAX_*` |
| Password reset (email token) | Done | `/password-reset/`, audited |
| Password change (logged-in) | Done | `/security/password/change/` |
| Idle session timeout + UI warning | Done | `IdleSessionMiddleware`, `static/js/session_idle.js` |
| Session cookie hardening | Done | HttpOnly, SameSite, optional Secure |
| Django admin | Present | Protect via network ACL + MFA-enrolled superusers |

**Bank action:** Set `MFA_REQUIRED=True`, configure real SMTP for reset mail, enroll all staff MFA before go-live.

---

## 3. Audit & accountability

| Control | Status | Code / config |
|---------|--------|---------------|
| Security event log | Done | `SecurityAuditLog` — login, lockout, MFA, password, logout, idle timeout, user admin, audit export |
| Auditor UI + filters | Done | `/security/audit/` |
| Export CSV / Excel | Done | `/security/audit/export/` (export itself is logged) |
| Collateral field audit | Done | `CollateralFieldAuditLog` |
| Agent tool-run audit | Done | `AgentRun` |

**Bank action:** Retain audit exports per policy (e.g. 1–7 years); restrict export to auditor / risk / VP IT roles.

---

## 4. Data protection in transit & at rest

| Control | Status | Where |
|---------|--------|-------|
| TLS termination | Ops | `docker-compose.https.yml` + `deploy/https/nginx.conf` (use public CA in prod) |
| HSTS / secure cookies | Done when HTTPS | `USE_HTTPS_PROXY=1`, `HTTPS_SECURE_COOKIES=1` |
| MFA secrets encrypted | Done | Fernet derived from `SECRET_KEY` (`loans/security.py`) |
| Media (KYC/collateral) not public | Done | Login-required `/media/` when `DEBUG=False` |
| DB encryption at rest | **Hosting** | Enable PostgreSQL volume encryption / disk encryption |
| Backups encrypted | **Hosting** | Bank backup policy |

---

## 5. Secure configuration & deployment

| Control | Status | Where |
|---------|--------|-------|
| No DEBUG in production | Done | `DEBUG=False` required; inverted bug fixed |
| Strong `SECRET_KEY` / `DB_PASSWORD` | Done | Refused if weak when `DEBUG=False` |
| `ALLOWED_HOSTS` required | Done | settings |
| Production server | Done | gunicorn (not `runserver`) |
| Non-root container user | Done | Dockerfile `appuser` |
| Static via WhiteNoise | Done | settings |
| Env template | Done | `.env.example` |
| CI tests + image build | Done | `.github/workflows/docker-image.yml` |

**Bank action:** Secrets in vault/HSM or sealed env; never commit `.env`.

---

## 6. Logging & monitoring

| Control | Status | Where |
|---------|--------|-------|
| App security logs to stdout | Done | `LOGGING` → `django.security` |
| Access logs | Ops | gunicorn / nginx |
| SIEM integration | **Hosting** | Ship container logs to bank SIEM |

---

## 7. Vulnerability & change management

| Control | Status | Notes |
|---------|--------|-------|
| Dependency list | Done | `requirements.txt` |
| Automated tests | Partial | Security tests under `loans/tests/test_security_*.py` |
| External VAPT | **Required for INSA** | Commission before clearance |
| Secure SDLC / change tickets | **Bank process** | Map releases to change records |

---

## 8. Recommended production `.env` (security-related)

```bash
DEBUG=False
SECRET_KEY=<unique-long-random>
ALLOWED_HOSTS=loan.bank.et
SITE_URL=https://loan.bank.et
USE_HTTPS_PROXY=1
HTTPS_SECURE_COOKIES=1
SECURE_SSL_REDIRECT=True
MFA_REQUIRED=True
MFA_TOTP_ISSUER=<Bank> Loan Hub
LOGIN_MAX_FAILED_ATTEMPTS=5
LOGIN_LOCKOUT_MINUTES=15
SESSION_IDLE_TIMEOUT=1800
SESSION_IDLE_WARNING_SECONDS=120
SESSION_COOKIE_AGE=28800
PASSWORD_MIN_LENGTH=12
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=...
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
DEFAULT_FROM_EMAIL=noreply@bank.et
```

CBS may remain mock until live access: `DECSI_CBS_USE_MOCK_LEDGER=True`.

---

## 9. Evidence pack to assemble for INSA / bank InfoSec

1. Architecture diagram (staff browser → nginx TLS → gunicorn → PostgreSQL)  
2. This checklist (filled with bank hosting answers)  
3. Role matrix (who can approve loans, unlock users, export audit)  
4. MFA enrollment procedure + screenshot  
5. Sample security audit CSV export  
6. VAPT report + remediation tracker  
7. Backup / restore test record  
8. Incident response contact list  
9. Data classification table (loan PII, collateral images, etc.)  
10. Network diagram (VLAN, firewall rules to CBS when connected)

---

## 10. Remaining gaps (honest)

| Gap | Owner |
|-----|-------|
| Live CBS / bureau integration security review | Bank + vendor when credentials exist |
| External penetration test | Bank / INSA-approved lab |
| Formal ISMS policies (AUP, IRP, BCP) | Bank |
| Privileged access management for servers | Bank infra |
| Optional: SSO / LDAP / Active Directory | Future enhancement |

---

## 11. Key file index

| Area | Path |
|------|------|
| Settings / hardening | `decsi_loan/settings.py` |
| Auth / MFA / reset / audit export | `loans/auth_views.py` |
| Lockout + crypto helpers | `loans/security.py` |
| Idle / MFA middleware | `loans/middleware.py` |
| Audit export builders | `loans/security_export.py` |
| Models | `loans/models.py` (`SecurityAuditLog`, MFA fields) |
| Idle UI | `static/js/session_idle.js` |
| HTTPS nginx | `deploy/https/nginx.conf` |
