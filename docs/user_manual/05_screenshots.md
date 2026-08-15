# Screenshots

Real UI captures from DECSI Loan Hub used in this manual pack. Files live in `docs/user_manual/screenshots/`.

## Digital Apply (customers / virtual loan requests)

![C-01 — Digital Apply landing](screenshots/C-01_landing.png)

![C-02 — Create account / register](screenshots/C-02_register.png)

![C-03 — Customer sign-in](screenshots/C-03_login.png)

![C-04 — My applications (Notices + Queue ID)](screenshots/C-04_home_applications.png)

![C-05 — Apply · Details](screenshots/C-05_apply_details.png)

![C-06 — Apply · Documents](screenshots/C-06_apply_documents.png)

![C-07 — Apply · Processing fee](screenshots/C-07_apply_payment.png)

![C-08 — Apply · Review & submit](screenshots/C-08_apply_submit.png)

![C-09 — Status / loan processing](screenshots/C-09_apply_status.png)

![C-11 — Digital Apply Help](screenshots/C-11_help.png)

![C-13 — Repayment schedule](screenshots/C-13_apply_schedule.png)

## Staff hub

![H-01 — Staff hub login](screenshots/H-01_hub_login.png)

![H-04 — Hub home](screenshots/H-04_hub_home.png)

![H-06 — Staff Help](screenshots/H-06_help.png)

![H-07 — Loan requests](screenshots/H-07_loan_requests.png)

![H-08 — Register / create loan request](screenshots/H-08_create_loan.png)

![H-09 — Loan request detail (online)](screenshots/H-09_loan_detail.png)

![H-15 — Approval queue](screenshots/H-15_approval_queue.png)

![H-18 — Online / Digital Apply intake](screenshots/H-18_online_intake.png)

![H-19 — Digital Apply settings](screenshots/H-19_digital_apply_settings.png)

![H-23 — Delegations](screenshots/H-23_delegations.png)

## Seqela Market

![M-01 — Market portal (share a local price)](screenshots/M-01_market.png)

## How to refresh captures

With the app running on port 8000 and Google Chrome installed:

```bash
# Full pack (admin + applicant):
node docs/user_manual/capture_manual_shots.js

# Staff create/detail + wizard fixups (branch manager + applicant):
node docs/user_manual/capture_manual_shots_fixup.js

docker compose exec web python docs/user_manual/build_pdf.py
```

| ID | URL / note | File |
|----|------------|------|
| C-01 | `/` | `C-01_landing.png` |
| C-02 | `/register/` | `C-02_register.png` |
| C-03 | `/login/` | `C-03_login.png` |
| C-04 | `/home/` (signed in) | `C-04_home_applications.png` |
| C-05…C-08 | Apply wizard steps | `C-05_apply_details.png` … `C-08_apply_submit.png` |
| C-09 | Status after submit | `C-09_apply_status.png` |
| C-11 | `/help/` | `C-11_help.png` |
| C-13 | `/apply/<id>/schedule/` | `C-13_apply_schedule.png` |
| H-01 | `/hub/login/` | `H-01_hub_login.png` |
| H-04 | `/hub/` | `H-04_hub_home.png` |
| H-07 | `/hub/view_loan_requests/` | `H-07_loan_requests.png` |
| H-08 | `/hub/create_loan_request/` (BM / credit) | `H-08_create_loan.png` |
| H-09 | `/hub/loan_request_detail/<id>/` | `H-09_loan_detail.png` |
| H-18 | `/hub/online_loan_intake/` | `H-18_online_intake.png` |
| H-23 | `/hub/delegations/` | `H-23_delegations.png` |
| M-01 | `/market-portal/` | `M-01_market.png` |
