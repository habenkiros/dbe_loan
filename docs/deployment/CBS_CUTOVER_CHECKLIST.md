# DECSI CBS / Temenos cutover checklist

Use this with DECSI IT before turning off mock ledgers and mock customer data. The Loan Hub already calls these paths when `DECSI_BASE_URL` is set; IT must confirm each endpoint exists and returns the fields we expect.

## Env switches (go-live)

| Setting | Pilot / demo | Live |
|---------|--------------|------|
| `DECSI_BASE_URL` | empty | Base URL of Temenos / party API |
| `DECSI_CBS_API_KEY` | empty | API key from DECSI IT |
| `DECSI_CUSTOMER_FORCE_MOCK` | `True` / unused | `False` |
| `DECSI_CUSTOMER_FALLBACK_MOCK` | `True` | `False` (fail closed if party is down) |
| `DECSI_CBS_USE_MOCK_LEDGER` | `True` | `False` |
| `DECSI_CBS_FORCE_MOCK` | optional | `False` |
| `DECSI_CBS_BOOK_ON_DISBURSE` | `True` | `True` once disburse path is proven |

See `.env.example` for path defaults.

## Endpoints to confirm with IT

### 1. Party / customer details (`custdets`) — **known**

- **Purpose:** Sheet 1 + Digital Apply customer lookup (name, phone, customer number).
- **Default path:** `DECSI_CUSTOMER_DETAIL_PATH`  
  `/getCusByCusNo/api/v1.0.0/party/custid/{cid}/custdets`
- **Status:** Documented against DECSI sample; confirm auth header and sample customer ID on the bank network.
- **Owner sign-off:** _________________ date _______

### 2. Transactions — **required for fraud / AML v1**

- **Purpose:** Banking anomaly scoring and Fraud/AML case engine (transaction monitoring).
- **Default path:** `DECSI_TRANSACTIONS_PATH`  
  `/getCusByCusNo/api/v1.0.0/party/custid/{cid}/transactions`
- **Status:** Assumed path — **DECSI IT must confirm or provide the real URI and payload shape.**
- Without this, anomaly scoring stays on mock / incomplete data.
- **Owner sign-off:** _________________ date _______

### 3. Outstanding balance

- **Purpose:** Credit Intelligence / portfolio outstanding snapshot; pre-disburse checks.
- **Default path:** `DECSI_OUTSTANDING_PATH`  
  `/getCusByCusNo/api/v1.0.0/party/custid/{cid}/outstanding`
- **Status:** Assumed path — confirm field names for outstanding principal / NPL flags.
- **Owner sign-off:** _________________ date _______

### 4. Disbursement booking

- **Purpose:** Book approved draw to CBS when Finance marks disbursed.
- **Default path:** `DECSI_DISBURSE_PATH`  
  `/loanDisburse/api/v1.0.0/loans/disburse`
- **Status:** Assumed path — confirm request body (customer no., amount, loan ref, branch) and success codes.
- Test first with `DECSI_CBS_BOOK_ON_DISBURSE=True` on a non-production or carefully chosen pilot account.
- **Owner sign-off:** _________________ date _______

## Suggested cutover order

1. Party (`custdets`) on a known test customer → Digital Apply + Sheet 1 show **Live core banking**.
2. Transactions → open Fraud/AML desk on a known account; confirm cases open from live rows.
3. Outstanding → CI / ledger views show live figures.
4. Disburse → one controlled Finance disbursement with IT watching CBS.
5. Set `DECSI_CUSTOMER_FALLBACK_MOCK=False` and `DECSI_CBS_USE_MOCK_LEDGER=False`.

## Contacts

- DECSI IT (queue system reference): Tsige Bayray, Vice Chief of IT · +251 914 701 978  
- Seqela implementation: as named on the on-prem install pack

## Related docs

- `docs/deployment/DEDEBIT_ON_PREM_INSTALLATION.md`
- `docs/user_manual/06_installation_it.md`
- `.env.example` (CBS + Chapa + SMS go-live checklist)
