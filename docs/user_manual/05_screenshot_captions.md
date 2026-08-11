# Screenshot captions catalog

Use this catalog when capturing UI screenshots for training decks, PDFs, or LMS content.  
Each entry gives a **shot ID**, **where to capture**, and a **caption** to place under the image.

Inline callouts in the manuals use the same wording after `> **Screenshot:**`.

---

## A. Staff hub

| ID | Screen / URL | Caption |
|----|--------------|---------|
| H-01 | `/hub/login/` | Staff login — enter username and password for AI-powered Credit Intelligence. |
| H-02 | `/hub/mfa/verify/` | MFA verify — enter the one-time code from your authenticator app. |
| H-03 | `/hub/mfa/setup/` | MFA setup — scan the QR code, then confirm with a code from the app. |
| H-04 | Hub home / Credit Intelligence | Hub home — role-scoped KPIs and shortcuts after sign-in. |
| H-05 | Header user menu | Header — Notifications, Help, and Logout sit beside your name and role. |
| H-06 | `/hub/help/` | Help index — open any manual chapter or the printable HTML pack. |
| H-07 | Loan requests list | Loan requests — open a Queue ID to continue documents, appraisal, or collateral. |
| H-08 | Create loan request | Create loan request — capture customer number, product, amount, and branch. |
| H-09 | Assign loan officer | Assign loan officer — branch/district managers route the file to an officer. |
| H-10 | Cooperative queue | Cooperative queue — approve branch intake before officer work continues. |
| H-11 | Document upload | Documents — upload each required type from the product document pack. |
| H-12 | Appraisal steps | Appraisal — complete steps 1–7 (MSME or corporate mode). |
| H-13 | Collateral dashboard | Collateral — buildings, land, or other items with field evidence. |
| H-14 | Engineering QA | Engineering QA — approve or return submitted valuations. |
| H-15 | Approval queue | Approval queue — committee members cast votes on pending loans. |
| H-16 | Post-approval detail | Post-approval — clear conditions, confirm schedule, mark ready. |
| H-17 | Disbursement queue | Disbursement queue — finance releases funds when the loan is ready. |
| H-18 | Online loan intake | Online loan intake — Digital Apply submissions waiting for branch processing. |
| H-19 | Settings → Digital apply | Digital Apply settings — open/close portal, fee, and security controls. |
| H-20 | Settings → Document pack | Document pack — required and optional docs for one loan category. |
| H-21 | Security audit | Security audit — review login, MFA, and unlock events. |
| H-22 | Agentic Assist widget | Agentic Assist — asks questions and drafts; cannot approve or disburse. |

---

## B. Digital Apply (customers)

| ID | Screen / URL | Caption |
|----|--------------|---------|
| C-01 | `/` landing | Digital Apply landing — Create account or sign in to apply online. |
| C-02 | `/register/` | Register — DECSI customer number, name, mobile, and password. |
| C-03 | `/login/` | Customer sign-in — use mobile number or customer number. |
| C-04 | `/home/` | My applications — drafts and submitted loans with status chips. |
| C-05 | Apply step 1 Details | Step 1 · Details — choose product, branch, amount, and purpose. |
| C-06 | Apply step 2 Documents | Step 2 · Documents — upload every required file for the product. |
| C-07 | Apply step 3 Fee | Step 3 · Fee — pay the processing fee (ETB) before submit. |
| C-08 | Apply step 4 Submit | Step 4 · Submit — review and submit to receive a Queue ID. |
| C-09 | Status / Queue ID | Status — keep your Queue ID for branch follow-up. |
| C-10 | Pipeline tracker | Pipeline — Submitted → intake → processing → decision → disbursement. |
| C-11 | `/help/` | Help — English and Amharic customer manuals inside Digital Apply. |
| C-12 | Password forgot / OTP | Password reset — request an OTP on your registered phone. |

---

## C. Seqela Market

| ID | Screen / URL | Caption |
|----|--------------|---------|
| M-01 | `/market-portal/` guest step 1 | Share a local price — Step 1 Area (who you are + Region/Zone/City). |
| M-02 | Guest step 2 product | Step 2 Product — enter item and price (ETB) for that area. |
| M-03 | Register | Create free account — actor type, product focus, and trading area. |
| M-04 | Login | Market sign-in — portal username and password (not staff hub). |
| M-05 | Recent quotes | Recent quotes — confirm your last submissions on the home/area screen. |
| M-06 | `/market-portal/help/` | Market Help — open the Seqela Market user manual. |

---

## Capture tips

1. Use a demo account; blur real customer names and phone numbers.  
2. Prefer desktop width ~1280px for hub screenshots; also capture mobile for Digital Apply.  
3. Show a realistic **Queue ID** format (`HK-#########`) on status shots.  
4. Store files as `docs/user_manual/screenshots/<ID>.png` when assets are ready.  
5. Rebuild the printable HTML after adding inline callouts: `python3 docs/user_manual/build_html.py`.
