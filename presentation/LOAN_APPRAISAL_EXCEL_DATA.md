# Loan Appraisal Excel – Extracted Data (Dropdowns & Options)

Extracted from `Cashflow based MSME loan appraisal.xlsx` for use in the Django appraisal forms.

---

## Sheet (1) Basic Info and loan request

| Field / area | Excel dropdown or options |
|--------------|---------------------------|
| **Gender** | `Male`, `Female` |
| **Education** | `None`, `Primary`, `Secondary`, `College`, `BA and above` |
| **Marital status** | `Single`, `Married`, `Divorced`, `Widowed` |
| **Form of ownership** | `Sole Propritership`, `PLC`, `Partnership`, `Association`, `Share Compaany` *(note: typo "Propritership", "Compaany" in Excel)* |
| **Economic sector** | `Manufacturing`, `Trade`, `Service`, `Construction`, `Agriculture` |
| **Record keeping / financial docs** | `Estimation`, `Professional accountant` |
| **Business plan quality** | `Poor`, `basic`, `Professional` |
| **Repayment frequency** | `Bi-Weekly`, `Monthly`, `Quarterly`, `Semi-annual`, `Annual` |
| **Interest basis** | `Declining`, `Flat` |
| **Loan type / product** | `WEDP`, `Regular MSME loan`, `YouthFund`, `Enterprise Loan`, `Business Loan`, `Others` |

---

## Sheet (2) Bus. and Character Assess.

**Important:** The Excel uses **different dropdown lists per qualitative factor**, not one global Poor/Basic/Professional. See **`SHEET2_DROPDOWNS_AND_SHEET3_ANALYSIS_PLAN.md`** for the full per-factor lists extracted from the workbook.

| Field / area | Excel dropdown or options |
|--------------|---------------------------|
| **NBE report** | `Yes`, `No` |
| **Credit history – Lender, Amount, Balance, Maturity** | Free text / number / date |
| **Credit history – Purpose** | `Working capital`, `Fixed Asset` |
| **Credit history – Status** | `Regular`, `Settled on time`, `Settled late`, `Irregular`, `Defaulted`, **`None`** |
| **Credit history – Repayment** | `Regular`, `Irregular`, `On time`, `Delayed` |
| **Credit history – Letter from lender** | `Yes`, `No` |
| **Credit history – Score** | Numeric |
| **10 qualitative factors – Rating** | **Per-factor lists** (3 options each; years of operation has 4) — see analysis plan doc |
| **10 qualitative factors – Notes** | Observation / justification (free text) |
| **Business and Character Maximum score** | Out of 100 (numeric) |
| **Applicant passed** | ≥75% → Proceed to Cashflow; else Borrower failed – DO NOT PROCEED |
| **Business assessment / Character assessment** | Free text (summary) |

---

## Sheet (3) Cashflow Analysis

*(No dropdown lists extracted in validations; numeric and date fields.)*

---

## Sheet (4) E&S Assessment

*(Use PASS / PASS WITH ACTION POINTS / REJECT; risk Low / Medium / High – already in model.)*

---

## Sheet (5) Collateral Worksheet

*(Numeric values; no dropdowns extracted.)*

---

## Sheet (6) Summary and Decision

*(Recommendation: Approve / Decline / Escalate – already in model.)*

---

## Implementation notes

1. **Sheet 1** – Use the options above for: Gender, Education, Marital status, Form of ownership, Economic sector, Repayment frequency, Interest basis. Add Loan type/product if present on Basic Info sheet.
2. **Sheet 2** – Use **Yes/No** for NBE report; use **status** dropdown for credit history (Regular, Settled on time, Settled late, Irregular, Defaulted); use **Poor / basic / Professional** (or same scale) for qualitative factor ratings.
3. **Spelling** – Excel has "Sole Propritership" and "Share Compaany"; we can keep these for consistency or use "Sole Proprietorship" and "Share Company" in the app.

This file is the single reference for options when coding or updating the appraisal forms.
