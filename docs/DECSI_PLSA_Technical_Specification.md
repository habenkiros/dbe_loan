# DECSI PLSA — Technical Specification

| Field | Value |
|-------|--------|
| **Document** | Technical Specification (v2.0) |
| **Product** | PLSA — Prize-Linked Savings & Customer Engagement Platform |
| **Institution** | Dedebit Credit and Saving Institution (DECSI) |
| **Vendor** | Seqela Technologies |
| **Date** | 2026-07-28 |
| **Status** | Aligned to DECSI source documents |
| **Source inputs** | *PLSA For DECSI* (Seqela proposal); *PLSA Project Marketing Plan & Strategy* (June 2026) |

---

## 1. Purpose and product positioning

### 1.1 What PLSA is for DECSI

PLSA is **not only** a classic prize-linked savings account. Per DECSI’s approved marketing direction, it is DECSI’s **premier customer engagement, loyalty, and promotional platform** — a growth engine that connects customers to the full DECSI ecosystem through:

- savings incentives and prize draws  
- digital adoption (especially **AdoPay**)  
- cross-selling (loans, merchant payments, School ERP, SACCO / multipurpose)  
- financial education and community engagement  
- referral and loyalty rewards  

Classic PLSA mechanics (entries from savings activity; **principal never at risk**) remain the core of the draw model. The platform extends entries to other positive behaviours DECSI wants to grow.

### 1.2 Strategic vision

Establish PLSA as DECSI’s primary engagement and rewards platform that drives financial inclusion, savings culture, digital financial services, and long-term customer relationships.

### 1.3 Institutional context (scale assumptions)

| Factor | Value (from DECSI proposal) |
|--------|-----------------------------|
| Clients | 1,000,000+ |
| Branches | 200+ (including 4 in Addis Ababa) |
| Lending scale | > ETB 10 billion disbursement from 2024 |
| Digital channel | **AdoPay** mobile banking |
| Geography | National MFI footprint; strong Tigray / Mekelle base |

The platform must be designed for **millions of accounts** and concurrent national campaigns.

### 1.4 Source-document alignment

| Document | Role in this spec |
|----------|-------------------|
| *PLSA For DECSI* | Product model, Campaign→Phase→Draw, segments, economics, architecture, compliance, rollout |
| *PLSA Marketing Plan & Strategy* | Five marketing pillars, multi-behaviour rewards, scholarship prizes, channels, KPIs, ecosystem products |

---

## 2. Business objectives

Mapped from both source documents.

| ID | Objective | Platform implication |
|----|-----------|----------------------|
| O1 | Strengthen **voluntary** (and compulsory) savings mobilization | Ticket rules on deposits, balances, frequency |
| O2 | Expand financial inclusion (rural, women, youth, underage, PwD) | Segment campaigns, accessible channels (SMS, branch, agent) |
| O3 | Increase customer acquisition | Referral entries; campaign tagging of new accounts |
| O4 | Promote **AdoPay** and digital DFS | Bonus entries / multipliers for digital deposits & transactions |
| O5 | Increase engagement & retention | Continuous Campaign→Phase→Draw cycles |
| O6 | Increase institutional revenue & sustainability | Deposit lift → lending capacity; fee/txn revenue analytics |
| O7 | Strengthen brand & public trust | Transparent draws, public winner announcement, audit packs |
| O8 | Cross-sell DECSI products & Seqela ecosystem | Entry rules for loans, repayments, School ERP, SACCO, merchants |

---

## 3. Product model

### 3.1 Behavioural PLSA core

- Customers keep **full access** to savings (no lock-box requirement for participation).  
- Each qualifying action increases **probability of winning** (more tickets).  
- Prize funds come from **institutional marketing / incentive budget**, **not** from deducting customer deposits.  
- Interest on deposits continues under DECSI / NBE deposit rules.

### 3.2 Campaign → Phase → Draw hierarchy

This is the **canonical structure** for DECSI PLSA.

```
Campaign          National or segment initiative (may run in parallel)
  └── Phase       Time-boxed stage (e.g. monthly prizes → regional → grand)
        └── Draw  Weekly / monthly / quarterly / annual execution event
```

**Example campaigns**

- National Savings Campaign  
- Women Financial Empowerment Campaign  
- Youth Digital Savings Campaign  
- Harvest / Farmer Seasonal Campaign  
- Educational Scholarship Campaign (“Save Today, Educate Tomorrow”)

**Example phases within a campaign**

1. Phase 1 — Monthly prizes  
2. Phase 2 — Regional prizes  
3. Phase 3 — National grand prizes  

**Draw cadence (configurable per phase)**

- Weekly, monthly, quarterly, annually  

Multiple campaigns may run **simultaneously** with independent eligibility and ticket pools.

### 3.3 How customers earn entries (tickets)

From the marketing plan **Pillar 5** and DECSI proposal eligibility model.

| Behaviour | Typical entry effect | Notes |
|-----------|----------------------|-------|
| Open / maintain savings account | Base enrolment + ongoing eligibility | Regular, voluntary, compulsory, fixed-term, group |
| Increase savings balance / deposit amount | Primary ticket generator | Probability rises with amount & frequency |
| Regular monthly deposits | Consistency bonus | Encourages habit |
| Use **AdoPay** (deposit / transfer / pay) | Digital multiplier or bonus tickets | Strategic digital push |
| Timely loan repayment | Loyalty tickets | Cross-sell / retention |
| Refer new customers | Referral tickets | Acquisition |
| Active account status | Soft eligibility gate | Dormant = ineligible |
| Use DECSI School ERP / scholarship path | Education-campaign tickets | Ecosystem |
| DECSI SACCO / multipurpose cooperative activity | Group / partner tickets | Ecosystem |
| Merchant / QR / bill payments (AdoPay) | Digital engagement tickets | Optional rule packs |

**Ticket formula (configurable per campaign/phase)**

```
tickets = f(deposit_amount, deposit_frequency, balance_basis, channel_multiplier, behaviour_bonuses)
tickets = min(tickets, max_tickets_cap)
if not eligible: tickets = 0
```

Recommended Phase-1 default for pure savings phases:

- Unit: e.g. every **ETB 500** net qualifying deposit (or ADB unit) = 1 ticket  
- Cap per customer per draw period (anti-whale)  
- **AdoPay multiplier** e.g. 1.25×–2× for digital-channel deposits  

Exact unit, caps, and multipliers are Board / Marketing parameters (see §17).

### 3.4 Prize catalogue

**Cash and in-kind (from DECSI proposal)**

| Tier | Timing | Example prizes |
|------|--------|----------------|
| Monthly | Frequent, many winners | Cash, smartphones, motorcycles, appliances, solar kits |
| Quarterly | Higher value | Agri equipment, business startup packages, livestock, shop equipment |
| Annual grand | Flagship ceremony | Houses, vehicles, tractors, large capital packages |

**Segment-tuned prizes**

| Segment | Prize examples |
|---------|----------------|
| Women | Business equipment, household assets, micro-enterprise capital |
| Youth | Smartphones, laptops, scholarships, startup grants |
| Underage / students | School supplies, tablets, education support funds |
| Rural farmers | Farming equipment, irrigation tools, livestock/inputs |
| Persons with disabilities | Mobility equipment, assistive tech, small business grants |

**Educational Scholarship Rewards (marketing plan)**

- 1–5 year scholarship packages for winners’ children  
- Coverage: KG → primary → secondary → preparatory (to Grade 12)  
- At approved high-performing schools in **Tigray Region** (extendable)  
- Fulfilment is a multi-year obligation tracked in Prize Management (not a one-time cash post)

### 3.5 Products promoted through PLSA

**Savings:** regular, voluntary, compulsory, fixed-term, group  

**Credit:** individual, agricultural, SME, women’s, youth, emergency/consumption  

**Digital:** AdoPay, digital payments, merchant / QR, transfers, bill pay  

**Additional:** financial literacy, BDS, community financing, School ERP, partner / SACCO services  

---

## 4. Target segments and campaign packs

| Segment | Strategy hooks | Channel bias |
|---------|----------------|--------------|
| Existing DECSI customers | Upsell balances, AdoPay, multi-product | Branch + SMS + AdoPay |
| Prospects / unbanked | Acquisition campaigns, community events | Field + radio + branch |
| Women | Dedicated campaigns, women’s associations | Group + literacy workshops |
| Youth / startups | Digital-first, campus, challenges | AdoPay + social |
| Underage (children/students) | Parent-linked accounts, education prizes | Branch + schools |
| Farmers | Harvest-season campaigns, cooperatives | Rural branch + radio (Tigrigna) |
| PwD | Inclusive onboarding, association outreach | Accessible branch + SMS |
| MSEs / merchants | Merchant payments, business prizes | AdoPay merchant |
| Cooperatives / groups | Collective participation recognition | Coop meetings |
| Education | School ERP + scholarship narrative | Schools / Seqela ERP |

Platform must support **segment tags** on campaigns, enrolments, and analytics.

---

## 5. Prize pool economics (for system configuration)

| Model | Prize pool as % of PLSA-mobilized deposits |
|-------|--------------------------------------------|
| Conservative | 0.5% |
| **Balanced (recommended initial)** | **1%** |
| Aggressive | 2% |

**Example (moderate participation):** ETB 1.5bn annual deposits → **ETB 15m** annual prize pool at 1%.

**Deposit lift scenarios (assumptions from proposal)**

| Scenario | Participation | Participants | Monthly deposits | Annual deposits |
|----------|---------------|--------------|------------------|-----------------|
| Conservative | 10% | 100,000 | ETB 50m | ETB 600m |
| Moderate | 25% | 250,000 | ETB 125m | ETB 1.5bn |
| High growth | 40% | 400,000 | ETB 200m | ETB 2.4bn |

Assumption: average **ETB 500 / month** per participant.

**System requirement:** Campaign budget module must enforce prize inventory + cash budget ≤ approved pool; alert when remaining pool &lt; threshold.

---

## 6. High-level architecture

Aligned to *PLSA For DECSI* §11.

```
┌─────────────────────────────────────────────────────────────┐
│ Customer channels                                            │
│  Branch teller · Agent banking · AdoPay · (future USSD)     │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ DECSI Core Banking (Temenos) + digital banking infrastructure│
│  Accounts · deposits · balances · KYC · product codes        │
└────────────────────────────┬────────────────────────────────┘
                             │ secure APIs / events
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ PLSA Campaign Platform (Seqela)                              │
│  Campaign Mgmt · Eligibility Engine · Draw Engine            │
│  Prize Mgmt · Notifications · Reporting / Analytics          │
└───────────────┬─────────────────────────────┬───────────────┘
                ▼                             ▼
        SMS Gateway / AdoPay           HO & Branch dashboards
        push / in-app notices          M&E reports
```

**Principle:** PLSA is an **integrated service layer** — it does **not** replace CBS, AdoPay, teller, or agent systems.

### 6.1 System of record

| Data | SoR |
|------|-----|
| Customer, accounts, balances, deposits, interest | **Core banking** |
| Campaigns, phases, rules, tickets, draws, winners, prize inventory/fulfilment | **PLSA platform** |
| AdoPay session / payment UX | **AdoPay** |
| SMS delivery | **DECSI SMS gateway** |

### 6.2 Design principles

Interoperability · Scalability (1M+ clients) · Security · Automation · Transparency / auditability  

---

## 7. Core system components (functional spec)

### 7.1 Core Banking Integration Layer

**Functions**

- Retrieve customer / account master data  
- Monitor savings deposits (near-real-time event or frequent batch)  
- Track balances for ADB / eligibility  
- Verify account status and product eligibility  
- Post cash prize credits / GL prize expense (idempotent)  

**Triggers:** When a qualifying deposit (or other mapped txn) posts in CBS → evaluate eligibility → grant tickets.

**Channels feeding CBS (hence PLSA):** branch teller, agent banking, AdoPay.

### 7.2 Campaign Management System

Admin (HO) configures:

- Campaign name, status, duration, segment targeting  
- Phases and draw schedule  
- Eligible account / product types  
- Geographic scope (branch / district / region / national)  
- Min deposit / balance rules  
- Ticket formula, caps, channel multipliers  
- Prize categories and inventory assignment  
- T&Cs version  

**Controls:** Maker–checker before go-live; pause/close; simultaneous campaigns.

### 7.3 Eligibility Engine

Continuously (or on txn event) evaluates:

- Deposit amount thresholds  
- Deposit frequency  
- Account type / segment (youth, women, voluntary, etc.)  
- Branch geography  
- Phase membership and freeze windows  
- Behaviour bonuses (AdoPay, referral, repayment, ERP/SACCO flags)  
- AML/KYC hold, staff exclusion, dormancy  

Outputs immutable **TicketGrant** records with input hash for audit.

### 7.4 Draw Engine

- Automated schedule + manual dual-control execute  
- Secure RNG; proportional tickets; no replacement within tier (configurable)  
- Pre-draw eligibility re-check  
- Fraud controls (duplicate identity, velocity)  
- Full audit log (census checksum, algorithm version, seed commit/reveal, winners)  
- Optional independent observer attestation  

### 7.5 Prize Management System

- Register prizes (cash amount or in-kind SKU; scholarship multi-year package)  
- Assign to campaign/phase/tier  
- Inventory tracking  
- Winner claim → verify → fulfil (cash credit / in-kind handover / scholarship enrolment)  
- Status: `PENDING_CLAIM | VERIFIED | PAID | DELIVERED | IN_PROGRESS_SCHOLARSHIP | FORFEITED | REJECTED`  

### 7.6 Notification and Communication System

Integrate **DECSI SMS gateway** and **AdoPay notifications**:

- Participation confirmation  
- Ticket / entry updates  
- Draw reminders  
- Winner announcements  
- Promotional / literacy messages  
- Deposit nudges  

**Languages:** Amharic, **Tigrigna**, English (template packs). Radio winner scripts reuse same result feed.

### 7.7 Reporting and Analytics Dashboard

Real-time / near-real-time:

- Participating customers  
- Deposit growth trends  
- Campaign performance by branch / region  
- Prize distribution stats  
- Geographic participation  
- AdoPay usage among PLSA participants  
- Cross-sell funnel metrics (loan apps, multi-product ownership)  

Report levels: branch · regional · national  

---

## 8. Domain model (logical)

```
Campaign
  phases[], segment_tags[], geo_scope, status, terms_version, budget_pool

Phase
  campaign_id, sequence, start/end, draw_cadence, ticket_rules_json

Draw
  phase_id, scheduled_at, freeze_at, status, census_checksum,
  algorithm_version, seed_commit, seed_reveal, authorized_by[]

Enrolment
  campaign_id, customer_number, account_number, branch_id,
  segment_tags[], channel, opted_in_at, status

TicketGrant
  draw_or_period_id, enrolment_id, tickets, basis_metrics,
  formula_version, input_hash, source_txn_refs[]

PrizeItem
  type (CASH|INKIND|SCHOLARSHIP), value_or_sku, years?, inventory_qty

PrizeAssignment
  phase_id, prize_item_id, tier, quantity

Winner
  draw_id, enrolment_id, prize_assignment_id, ticket_ref, status

Payout / Fulfilment
  winner_id, cbs_ref | handover_ref | scholarship_contract_ref

BehaviourEvent (optional normalized feed)
  customer_number, event_type, channel, amount, occurred_at, source_system

AuditEvent
  actor, action, entity, payload, timestamp
```

External keys: CBS `customer_number`, `account_number` (same pattern as DECSI Loan Hub integrations).

---

## 9. Integration contracts

### 9.1 Core banking (Temenos)

| Capability | Pattern |
|------------|---------|
| Customer / account lookup | Sync API |
| Deposit / txn feed | Event webhook **or** near-real-time poll / batch (≤15 min latency target) |
| Balance history | For ADB campaigns |
| Prize cash credit | Idempotent payment API |
| Prize expense GL | Journal / designated marketing GL |

**Note (roadmap source):** Phase 1 development states platform already developed/tested with DECSI Temenos core banking — integration hardening and production ops remain in scope for pilot.

### 9.2 AdoPay

| Capability | Purpose |
|------------|---------|
| Deep link / in-app PLSA section | Show tickets, campaigns, T&Cs |
| Push notifications | Engagement |
| Channel flag on deposits | Digital ticket multiplier |
| Registration drives | Attribute new AdoPay users to PLSA campaigns |

**Pilot constraint:** Phase 2 pilot is **AdoPay-only** participation path (see §14).

### 9.3 SMS gateway

OTP-free informational SMS; bulk campaign blasts; winner notices; complaint short-code optional.

### 9.4 Ecosystem (phase-gated)

| System | Entry / promotion use |
|--------|----------------------|
| DECSI Loan Hub | Timely repayment events; cross-sell loan offers to savers |
| Seqela School ERP | Education campaign participation; scholarship school roster |
| DECSI SACCO / multipurpose | Group participation flags |

### 9.5 Illustrative PLSA APIs

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/campaigns` | Create campaign |
| POST | `/api/v1/campaigns/{id}/phases` | Add phase |
| POST | `/api/v1/campaigns/{id}/approve` | Checker approve |
| POST | `/api/v1/enrolments` | Opt-in |
| POST | `/api/v1/events/transactions` | CBS/AdoPay txn ingest |
| GET | `/api/v1/enrolments/{id}/tickets` | Customer/staff ticket view |
| POST | `/api/v1/draws/{id}/freeze` | Freeze census |
| POST | `/api/v1/draws/{id}/execute` | Dual-control draw |
| GET | `/api/v1/draws/{id}/results` | Results feed (SMS/radio/web) |
| POST | `/api/v1/winners/{id}/verify` | Branch verify |
| POST | `/api/v1/winners/{id}/fulfil` | Cash / in-kind / scholarship |
| GET | `/api/v1/analytics/summary` | M&E dashboard API |

OpenAPI 3.0 required for all external integrations.

---

## 10. Staff roles and governance

| Role | Location | Responsibilities |
|------|----------|------------------|
| PLSA Program Management Team | HO | Campaign planning/approval, deposit monitoring, draws, marketing coordination |
| Campaign Maker / Checker | HO | Configure vs approve rules & prizes |
| Draw Committee | HO (+ auditor) | Authorize freeze/execute; witness |
| Compliance / Internal Audit | HO | Oversight, AML, draw audit |
| Branch PLSA focal person | Each branch | Promote, enrol, winner verification, local reporting |
| Finance | HO | Prize pool budget, GL, tax |
| Marketing | HO | Pillars, creative, media, community calendar |

Aligns with marketing **implementation roadmap** and M&E governance in the DECSI proposal.

---

## 11. Customer journeys (MVP+)

### 11.1 Enrol (branch or AdoPay)

1. Identify customer in CBS  
2. Select eligible savings account  
3. Accept T&Cs (versioned)  
4. Confirm via SMS / AdoPay  
5. Start earning tickets on qualifying activity  

### 11.2 Save and earn

1. Deposit via branch / agent / AdoPay  
2. Integration layer notifies PLSA  
3. Eligibility engine grants tickets  
4. Optional SMS: “You now have N entries for {draw date}”  

### 11.3 Draw and win

1. Freeze → dual-control draw → publish results  
2. Winner SMS + branch list + radio/social feed  
3. Claim window → KYC verify → fulfil  
4. Public celebration events for trust  

---

## 12. Compliance and risk controls

NBE-aligned pillars from *PLSA For DECSI* §10:

1. **Consumer protection** — published rules; no guaranteed-win marketing; complaint channel  
2. **AML / KYC** — only verified CBS customers; monitor unusual deposit/withdrawal patterns; report as required  
3. **Deposit protection** — full withdrawal rights; prize funds separated from customer deposits  
4. **Fair, transparent, auditable draws** — RNG, independent oversight, public winners, immutable logs  

**Risks & mitigations:** low participation (marketing pillars + pilot learnings); operational errors (automation + maker-checker); fraud (eligibility re-check, identity rules, audit).

---

## 13. Marketing pillars → system features

| Pillar | Marketing intent | Platform feature |
|--------|------------------|------------------|
| 1 Savings mobilization | Save Today, Secure Tomorrow | Deposit tickets, seasonal campaigns, challenges |
| 2 AdoPay adoption | “Your DECSI Account in Your Pocket” | Digital multipliers, in-app PLSA, registration attribution |
| 3 Product awareness / cross-sell | Behaviour-based offers | Rule engine + Loan Hub / product nudges |
| 4 Community & inclusion | Grassroots trust | Segment campaigns, geo targeting, SMS/radio result feeds |
| 5 Loyalty / lottery rewards | Multi-behaviour entries | Unified ticket ledger + diverse prize catalogue + scholarships |

**Channels to support operationally:** Facebook, Telegram, TikTok, YouTube, SMS, email, AdoPay, website, radio (Tigrigna), community meetings, OOH, print, branch activations, field agents, ambassadors, coop mobilizers, merchants.

---

## 14. Implementation roadmap

From DECSI proposal §13–14, refined for engineering delivery.

| Phase | Scope | Notes |
|-------|--------|-------|
| **1 — System development** | Campaign, eligibility, draw, prize, SMS, CBS integration | Source states already developed/tested with Temenos — complete UAT, harden, document APIs |
| **2 — Pilot** | **AdoPay-only** pilot cohort | Prove digital ticket path, notifications, ops playbooks |
| **3 — Regional rollout** | **Mekelle** branches (+ teller/agent if approved) | Add branch enrolment & in-kind fulfilment |
| **4 — National deployment** | All branches | Full channel set |

**Geographic rollout clusters**

1. Urban centers incl. Addis Ababa  
2. Major regional cities  
3. Rural districts  

**Marketing timeline (parallel)**

| Marketing phase | Timing | Focus |
|-----------------|--------|-------|
| Preparation | Month 1 | Materials, training, stakeholder readiness |
| Launch | Months 2–4 | Launch events, savings + AdoPay drives, referrals |
| Expansion | Months 5–12 | Continuous campaigns, rewards, merchants, cross-sell |
| Optimization | Year 2+ | Segmentation, personalization, new groups |

---

## 15. KPIs and M&E (must be in analytics)

### Savings

- Total savings growth; new accounts; average balance; voluntary participation rate  

### AdoPay

- Registrations; MAU; txn count/value; merchant enrolments; % PLSA participants using digital  

### Acquisition & engagement

- New customers; referral conversions; campaign participation; loyalty participation; retention  

### Product utilization

- Loan applications from PLSA cohort; cross-sold products; multi-product ratio  

### Ops / trust

- Draw complaint rate; payout STP %; ticket exception rate; branch league tables  

**Review cadence:** monthly performance · quarterly impact · annual strategic evaluation  

---

## 16. Non-functional requirements

| Area | Target |
|------|--------|
| Scale | ≥ 1M customers; concurrent multi-campaign; peak harvest deposit bursts |
| Ticket/eligibility latency | ≤ 15 minutes from CBS post (pilot); stretch to near-real-time |
| Availability | 99.5% inquiry; planned draw windows |
| Security | TLS, RBAC, encrypted PII, secure RNG, audit retain ≥ 7 years |
| Localization | EN / AM / TI templates |
| DR | RPO ≤ 24h, RTO ≤ 8h (pilot); tighten for national |

---

## 17. Open parameters (Board / Marketing lock)

1. Ticket unit (ETB) and max tickets per customer per draw  
2. Balance basis: net deposit vs ADB vs closing balance  
3. AdoPay multiplier value  
4. Which behaviours earn tickets in Phase-2 pilot vs national  
5. Prize mix: cash % vs in-kind % vs scholarship reserve  
6. Prize pool % (0.5 / 1 / 2) for year 1  
7. Employee / related-party exclusion rules  
8. Claim window days and unclaimed prize policy  
9. Scholarship partner school list and multi-year GL treatment  
10. Pilot success gates before Mekelle / national expansion  

---

## 18. MVP acceptance criteria

- [ ] Campaign → Phase → Draw configured with maker-checker  
- [ ] CBS deposit ingest creates auditable tickets  
- [ ] AdoPay-channel deposits receive configured multiplier  
- [ ] Freeze + dual-control draw + replayable audit pack  
- [ ] SMS notifications for enrolment, tickets, winners  
- [ ] Cash prize posting idempotent to CBS  
- [ ] Branch/HO dashboards for participation & deposit growth  
- [ ] Published T&Cs and responsible-marketing checklist signed off  
- [ ] AdoPay pilot cohort completed with KPI baseline report  

---

## 19. Technology recommendation

| Layer | Suggestion |
|-------|------------|
| PLSA services | Modular backend (Django/API or equivalent) + workers for eligibility/draws |
| DB | PostgreSQL |
| Integration | Secure APIs to Temenos, AdoPay, SMS; mocks for lower envs |
| Admin UI | HO campaign console + branch workbench |
| Customer UX | AdoPay module first; branch assisted enrolment |
| Analytics | Dashboard + exportable M&E packs |
| Deploy | Containerized; horizontal scale for national load |

---

## 20. Document control

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 2026-07-28 | Initial generic PLSA tech draft |
| **2.0** | **2026-07-28** | Rewritten from *PLSA For DECSI* + *PLSA Project Marketing Plan & Strategy (3)* |

**Next step:** Freeze §17 parameters in a DECSI workshop; produce CBS/AdoPay OpenAPI bindings and pilot SoW.
