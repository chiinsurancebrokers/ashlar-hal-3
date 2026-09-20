# Ashlar Adviser OS — A-to-Z Architecture

## Non-negotiable architecture

From the moment an insurance case exists, **AshlarOrchestrator is the coordinating brain**.

Public product flows enter through:

```python
result = await orchestrator.handle(
    case_id=case_id,
    message=user_message,
)
```

Model-backed work is allowed only behind these four specialists:

- `hal_adviser`
- `document_analyst`
- `proposal_writer`
- `health_navigator`

Deterministic authority remains outside the language models:

- Quote Engine → eligibility and price
- FactLedger / Case Intelligence → evidence, provenance and conflicts
- Policy Engine → policy-benefit evidence decisions
- workflow services → application, policy, claim and renewal state transitions

The client or broker makes the final insurance choice. HAL explains evidence and trade-offs; it does not silently choose on the client's behalf.

## Canonical journey

| # | Journey step | Primary owner | Current state |
|---|---|---|---|
| 1 | “I need international health insurance” | `hal_adviser` via AshlarOrchestrator | Live |
| 2 | HAL interviews applicant | `hal_adviser` | Live |
| 3 | AshlarCase created | AshlarOrchestrator | Live — created when discovery completes |
| 4 | Quote Engine finds eligible plans | Quote Engine | Live |
| 5 | Client/broker chooses 2–4 | HAL UI + human decision | Live |
| 6 | Carrier quotations uploaded | `document_analyst` boundary | Live |
| 7 | Documents analysed | `document_analyst` + Proposal Studio document engine | Live |
| 8 | Conflicts against server evidence detected | FactLedger / Case Intelligence | Live |
| 9 | Evidence-grounded comparison produced | AshlarOrchestrator | Live |
| 10 | HAL explains differences | `hal_adviser` | Live |
| 11 | Ashlar Assessment produced | `proposal_writer` / Proposal Studio | Live |
| 12 | PDF/PPTX proposal produced | `proposal_writer` | Live |
| 13 | Client selects plan | Human decision recorded by AshlarOrchestrator | Live workflow + HAL UI |
| 14 | Application preparation | deterministic application workflow + HAL guidance | Live checklist foundation; carrier-specific forms next |
| 15 | Policy issued | broker-authorised policy workflow under AshlarOrchestrator | Live backend workflow |
| 16 | Policy Wallet | deterministic issued-policy + FactLedger projection | Live backend workflow |
| 17 | Asklepios health navigation | `health_navigator` → Asklepios service | Adapter live; external Asklepios endpoint still required |
| 18 | Pre-authorisation | Policy Engine + deterministic pre-authorisation workflow | Live backend foundation |
| 19 | Claims | deterministic claim workflow; document analysis added when evidence exists | Live backend foundation |
| 20 | Renewal comparison | AshlarOrchestrator → renewal workflow + Quote Engine | Live backend foundation |

## Case continuity rule

There must be **one AshlarCase** from step 3 onward.

The same `case_id` follows the client through:

```text
Discovery
  ↓
Market review
  ↓
Comparison
  ↓
Proposal
  ↓
Application
  ↓
Active policy
  ↓
Policy Wallet / Asklepios
  ↓
Pre-authorisation / Claims
  ↓
Renewal
```

A later workflow must extend that case rather than create an unrelated second case.

## Evidence rule

The architecture separates four kinds of information:

```text
Client declaration
Carrier document evidence
Deterministic engine facts
Model interpretation
```

They are not interchangeable.

- Quote Engine facts can be stored as `VERIFIED`.
- Carrier document extraction enters with source provenance and conflict checking.
- Model extraction remains candidate evidence unless deterministic verification promotes it.
- Conflicts remain explicit until resolved.
- Proposal narrative can explain the evidence but cannot overwrite it.

## Future implementation rule

Steps 13–20 should **not** create additional general-purpose AI agents.

New capabilities should be implemented as deterministic/workflow services beneath AshlarOrchestrator, while any model call continues to sit behind one of the four specialist boundaries.

Examples:

```text
Application
  AshlarOrchestrator
      ├── application workflow service
      └── hal_adviser (guided explanation / missing information)

Pre-authorisation
  AshlarOrchestrator
      ├── health_navigator → Asklepios
      ├── Policy Engine
      └── pre-authorisation workflow service

Claims
  AshlarOrchestrator
      ├── document_analyst
      ├── Policy Engine
      └── hal_adviser

Renewal
  AshlarOrchestrator
      ├── Quote Engine
      ├── document_analyst
      └── hal_adviser
```

This keeps HAL feeling like one adviser while preserving clear factual authority and auditability.


## Dedicated AshlarOrchestrator FastAPI

The orchestrator now has its own ASGI application:

```bash
uvicorn backend.app.orchestrator_main:app --host 0.0.0.0 --port 8000
```

Primary endpoints:

```text
GET  /health
POST /v1/handle

POST /v1/journey/{case_id}/select-plan
POST /v1/journey/{case_id}/application/prepare
POST /v1/journey/{case_id}/application/sections/complete
POST /v1/journey/{case_id}/application/submit
POST /v1/journey/{case_id}/policy/issue
GET  /v1/journey/{case_id}/policy/wallet
POST /v1/journey/{case_id}/preauthorisations
POST /v1/journey/{case_id}/claims
POST /v1/journey/{case_id}/renewal/start
```

Every lifecycle endpoint delegates to `AshlarOrchestrator`; no API route owns a
specialist or workflow service directly.

### Deployment constraint

The FastAPI boundary is standalone, but the current Case/Analysis registry is
still process-local. Therefore HAL and AshlarOrchestrator should **not** be run
as separate production processes until the case store is moved to shared
durable persistence (for example Postgres/Supabase).

Until that migration, the dedicated app is the clean service boundary and test
target, while the HAL application mounts the same orchestrator-owned lifecycle
routes in-process so one AshlarCase remains authoritative.

## Verified GPMI / Inspire comparison (September 2026)

The client can open **Compare plan benefits** after the needs interview, select
2–4 catalogue plans, and compare the loaded EUR benefit evidence even when no
price exists. GPMI uses `img:gpmi_<tier>` and Inspire uses
`cigna:inspire_<tier>`; these identities deliberately differ from legacy IMG
rate products. Legacy premiums never price these brochure plans. Missing
benefits remain **Not confirmed**, and unknown acceptance, deductible and area
remain unconfirmed. This is a comparison of sourced brochure details, not a
binding policy offer. The catalogue does not claim to contain every brochure row.

Comparison cells retain source page, optional selections, waiting periods and
conditions. These are carried into the case evidence and proposal inputs.
Optional/selectable benefits do not produce an unconditional covered verdict.
A catalogue plan without a carrier premium cannot pass the proposal quality
gate or be silently omitted from a priced comparison email.

**Current policy upload** remains available to the client with the active case
token and the separate `existing_policy` baseline. New quotations, brochures and
wordings require both the case token and `X-Admin-Password`; the endpoint fails
closed when `ADMIN_PASSWORD` is absent. The internal upload controls are available
at `/?workspace=broker`, which only switches the UI: the server still authenticates
every new-carrier upload. Enter the configured broker password in the upload form.
Never place that password in a URL. No source policy files or client quotations
are committed to the repository.

Validation: 249 Python tests pass; JavaScript syntax and git diff checks pass.
