# Cashflow based MSME loan appraisal.xlsx – Structure

Summary extracted from the Excel file in `presentation/Cashflow based MSME loan appraisal.xlsx`.

## Sheet order and purpose

| # | Sheet name | Purpose |
|---|------------|--------|
| 1 | **Intro** | Instructions; steps 1–7; cell colors (encode in yellow, protected areas) |
| 2 | **(1) Basic Info and loan request** | Client, business, loan request, purpose of loan (working capital / investment) |
| 3 | **(2) Bus. and Character Assess.** | Qualitative assessment; credit history; 10 factors scored; pass >75% to proceed |
| 4 | **(3) Cashflow Analysis** | Sales/purchases, income statement, balance sheet, growth rate, **monthly cashflow**, repayment capacity, DSCR |
| 5 | **(4) E&S Assessment** | Environmental & social checklist; E&S risk category; eligibility (PASS / REJECT) |
| 6 | **(5) Collateral Worksheet** | Immovable (land/buildings), moveable/fixed deposits; total collateral value; collateral coverage |
| 7 | **(6) Summary and Decision Sheet** | Key indicators, qualitative + financial + E&S + collateral summary; **Decision: APPROVE / DECLINE**; committee comments |
| 8 | **(7) Repayment Schedule** | Repayment schedule / amortization parameters |
| 9 | **Loan Amortization Schedule** | Detailed amortization (payment #, date, principal, interest, balance) |

## Key fields (from shared strings and structure)

### (1) Basic Info and loan request
- **Client:** Applicant Name, TIN, Gender, Age, Marital Status, Spouse, Education, Home Address, Phone, Father's Name, G.Father's Name
- **Business:** Business Name, Business Description, Business Address, Date Started, Form of ownership, Economic Sector, Subsector, Employees (Full time, Part-time, Seasonal, FT Equivalent, Family), Peak/Lowest Sales Months
- **Loan request:** Loan amount, Term (months), Repayment frequency (Monthly/Quarterly/etc.), Interest rate, Interest basis (Declining/Flat), Grace period, Interest-only months, Instalments/yr., Loan purpose (Working capital, Investment), Purpose breakdown (Quantity, unit price, Value), Cash contribution

### (2) Bus. and Character Assess.
- **Credit history:** NBE Credit Report (Y/N), loans (Lender, Amount, Balance, Maturity, Status, Repayment, Score), Max score
- **10 factors (each rated + justified):** Years of business operation, Management competence, Supplier quality, Sales prospects, Project plan, Savings record, Character, Asset management, Record keeping, 3rd party opinion
- **Business and Character Maximum score** (out of 100); **Applicant passed qualitative assessment: Proceed to Cashflow Analysis** or **Borrower failed: DO NOT PROCEED**

### (3) Cashflow Analysis
- Sales and purchases summary (cash % / credit %), ending inventory
- Income statement (historical & projected): Sales, COGS, expenses (Salaries, Rent, Utilities, Transport, etc.), Profit, taxes
- Balance sheet: Current assets/liabilities, Long-term, Owner's equity, Key ratios (Acid test, Debt to equity, etc.)
- **Cash flow projection by month:** Inflows, outflows, **Net Cash Flow from All Monthly Activities**, Ending cash
- **REPAYMENT CAPACITY ANALYSIS:** Total cash inflow (annual), Annual loan payment, **Debt Service Ratio**, **Max loan capacity**
- Seasonality (peak / low months %)

### (4) E&S Assessment
- Environmental/social checklist (questions with Yes/No, description, mitigations)
- **App implementation:** `AppraisalESChecklistItem` (21 rows) seeded per appraisal from `ES_CHECKLIST_STRUCTURE` in `loans/models.py` — sections: *Exposure & compliance*, *Enterprise & sub-project*, *Environmental aspects*, *Occupational health & safety*, *Health & sanitation*. Each row: **Yes/No/N/A**, **description**, **mitigation**; plus on `LoanAppraisal`: **E&S Risk Category**, **eligibility**, **screened/checked/approved by**, **date**, **notes** (signatures via user pickers).
- **E&S Risk Category**; **Decision on eligibility:** PASS / PASS WITH ACTION POINTS / REJECT
- Screened by, Checked by, Approved by, Date, Signature

### (5) Collateral Worksheet
- **1. Immovable (Land/Buildings)** – Value, Max portion
- **2. Moveable / Fixed deposits**
- **3. Intangible / securities / contracts**
- **4. Guarantors**
- **Total Collateral Value**, **Collateral coverage**

### (6) Summary and Decision Sheet
- Customer, Business name, Credit Officer, Date, Branch
- **Summary of Request:** Requested amount, Term, Installment, Annual repayment, Total due, etc.
- **Key financial indicators (Before / After loan):** Acid test, DSCR, Net operating cashflow/debt, Months negative cashflow, Net profit margin; each with Rating/Weight/Earned score (Low/Medium/High)
- **Summary of Decision Factors:** 1) Qualitative (Business & character), 2) Financial (Cashflow & ratios), 3) Environmental, 4) Collateral; Max, Actual, Norm, Remark
- **Proposed Credit Decision**
- **RECOMMENDATIONS AND CREDIT DECISION:** Strengths, Weaknesses, **Decision: APPROVE / DECLINE**
- Credit Committee comments, Amount/term/rate approved, Signatures

---

This document is used to align the Django loan appraisal feature (models, forms, steps) with the Excel tool.
