# Sheet 2 – Complete dropdown content (from Excel)  
# Sheet 3 – Cashflow / loan analysis – recommendations (before coding)

Source: `Cashflow based MSME loan appraisal.xlsx`, worksheet **(2)Bus. and Character Assess.** (`sheet3.xml` in the workbook) and **(3)Cashflow Analysis** (structure + print area `A1:O148`).

---

## Part A – Sheet 2: What was missing vs the Excel

The Excel does **not** use one global rating scale (Poor / Basic / Professional) for all 10 factors. Each factor has its **own** 3-option list (or 4 for “years of operation”). Our app currently uses a single `Poor / Basic / Professional` dropdown for every factor — that is **incomplete** relative to the tool.

### A.1 Credit history – **Status** (column linked to `R9:R14`)

| Option |
|--------|
| Regular |
| Settled on time |
| Settled late |
| Irregular |
| Defaulted |
| **None** |

**Gap:** Add **None** to the Django `STATUS_CHOICES` if we want parity with Excel.

### A.2 NBE Credit Report

Excel uses **Yes / No** (not only a checkbox). We can keep checkbox + optional “not obtained” or map to Yes/No explicitly for reporting.

### A.3 Ten qualitative factors – **per-factor rating options**

Map factor key → options (exact strings from Excel; typos kept for traceability; you can normalize in the UI later).

| # | Factor (app `factor_key`) | Dropdown options (3 unless noted) |
|---|---------------------------|-------------------------------------|
| 1 | `years_operation` | Startup (< 6months); 6-12 months; 12-24 months; > 24 months *(4 options)* |
| 2 | `management_competence` | Competent/ well performing; Average/Adequate business skills; Below average |
| 3 | `supplier_quality` | Very reliable supply chain; Satisfactory/ Adequate supply chain; Often face challenge |
| 4 | `sales_prospects` | Very good/ High demand projection; Adequate demand projection; Unrelaible demand projection |
| 5 | `project_plan` | Well planned; Some gaps; unclear |
| 6 | `savings_record` | Regular pattern/ verified saving habit; Some savings habit; No savings habit |
| 7 | `character` | Cooperative/shared all relevant info/doc ; Average-Provided some but not all; Not willing to share any documents |
| 8 | `asset_management` | *(same row set as record keeping in Excel – see next row)* |
| 9 | `record_keeping` | Financial record all in order; Basic record keeping; inconsistent record of daily sales/ expenses |
|10 | `third_party_opinion` | Positive, Respected; Moderate; No feedback received |

**Implementation note:** Store either:

- **Option A (recommended):** `rating` as `CharField` + in the form, pass **different `choices` per `factor_key`** in `AppraisalQualitativeFactorForm.__init__` when `instance` is set; or  
- **Option B:** Add `rating_code` (e.g. 1/2/3) + display labels in Python only; or  
- **Option C:** JSON field listing `{factor_key: [options]}` for admin-editable lists.

### A.4 Credit history – already aligned (from earlier work)

- **Purpose:** Working capital; Fixed Asset  
- **Repayment:** Regular; Irregular; On time; Delayed  
- **Letter from lender:** Yes; No  

---

## Part B – Sheet 3: Cashflow / loan analysis – how it should work (recommendations **before** coding)

### B.1 Purpose of Sheet 3 in the Excel

Sheet **(3) Cashflow Analysis** is broader than “one net cashflow number.” It typically includes:

- Sales / purchases (cash vs credit %, inventory where relevant)  
- **Income statement** (historical & projected): sales, COGS, expense lines (salaries, rent, utilities, transport, etc.), profit, taxes  
- **Balance sheet** hints (current assets/liabilities, long-term debt, equity) and simple ratios  
- **Monthly (or periodic) cashflow** projection: inflows, outflows, net cashflow, ending cash  
- **Repayment capacity:** annual cash inflow vs annual debt service, **DSCR**, optional “max loan capacity”  
- **Seasonality** (links to peak/low months from Sheet 1)

The current Django step only captures a **short summary** (monthly income/expenses, installment, net cashflow, DSCR). That is **Phase 0**; full parity is a larger build.

### B.2 Recommended phased approach

| Phase | Scope | User value |
|-------|--------|------------|
| **0 – Now** | Keep high-level monthly figures + proposed installment + auto **net cashflow** and **DSCR** | Fast screening, matches a simplified appraisal |
| **1 – Structured P&amp;L** | Add optional lines: Sales, COGS, Salaries, Rent, Utilities, Transport, Other expenses, Taxes → roll up to “monthly business expenses” (or split operating vs other) | Closer to Excel, still one period (e.g. average month) |
| **2 – Repayment capacity block** | Annualize inflows, annual loan payment from Sheet 1 (amount, rate, term, frequency), show DSCR + warning thresholds | Clear credit narrative |
| **3 – Monthly grid** | 12 rows (or 12+ grace): inflow, outflow, net, cumulative — **or** import from CSV later | Full Excel parity; heavy UI |
| **4 – Balance sheet / ratios** | Acid test, debt/equity, etc. “before / after loan” | Committee / policy scoring (ties to Summary sheet later) |

**Recommendation:** Agree with the business **which phase is mandatory** for go-live. Most MSME tools still approve **Phase 0–2** first, then add monthly grid if regulators or internal policy require it.

### B.3 Data flow (avoid double entry)

- **Pull from Sheet 1 / `LoanRequest`:** loan amount, term, repayment frequency, interest rate, grace period, instalments/year → use for **annual debt service** and consistency checks on Sheet 3.  
- **Pull from Sheet 2:** qualitative pass flag (already “must pass to proceed”) — Sheet 3 should remain editable even if Sheet 2 failed, but you can show a warning.  
- **Proposed monthly installment:** either user-entered or **suggested** from loan terms (formula), with override.

### B.4 UX recommendations

1. **Section cards** (same pattern as Sheet 1 / 2): e.g. “Operating cashflow (monthly average)”, “Debt service”, “Ratios”, “Notes”.  
2. **Show formulas read-only:** e.g. “Net monthly cashflow = (business + other income) − (business + other expenses)”; DSCR = net / installment.  
3. **Thresholds:** configurable minimum DSCR (e.g. 1.2x) → soft warning, not hard block unless policy says so.  
4. **Currency &amp; decimals:** one standard (e.g. 2 decimal places) across steps.  
5. **Audit:** store `updated_at` on `LoanAppraisal` (already) and optionally log who changed Sheet 3.

### B.5 Technical notes

- **Monthly vs annual:** pick one primary input (e.g. monthly) and annualize for DSCR vs annual debt service, or input annual and divide — **be consistent** in labels.  
- **Interest-only / grace:** if Sheet 1 has grace months, debt service in early months may be interest-only; Phase 2+ can model that; Phase 0 can use average installment.  
- **Validation:** non-negative where appropriate; installment &gt; 0 before DSCR.

---

## Next steps (when you are ready to code)

1. **Sheet 2:** Add **None** to loan status; replace single qualitative rating list with **per-factor choices** (table above). *(Implemented in app.)*  
2. **Sheet 3:** Phases **0–2** are implemented in Django: Phase 1 P&amp;L breakdown fields, Phase 2 annual net / annual debt service / annual DSCR from Sheet 1 repayment frequency; monthly grid (Phase 3) still optional.

This document remains the reference for further Sheet 3 enhancements (e.g. 12-month grid).
