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
| 13 | Client selects plan | Human decision recorded by AshlarOrchestrator | Next |
| 14 | Application preparation | workflow service + `hal_adviser` for guided collection | Foundation in AshlarCase |
| 15 | Policy issued | policy workflow under AshlarOrchestrator | Foundation in AshlarCase |
| 16 | Policy Wallet | deterministic policy service | Next |
| 17 | Asklepios health navigation | `health_navigator` → Asklepios service | Adapter ready |
| 18 | Pre-authorisation | `health_navigator` + Policy Engine + workflow service | Future integration |
| 19 | Claims | AshlarOrchestrator + document/policy specialists as needed | Foundation in AshlarCase |
| 20 | Renewal comparison | AshlarOrchestrator → Quote Engine + document analysis + HAL | Foundation in AshlarCase |

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
