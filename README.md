# Ashlar HAL — Insurance Adviser (v1 rebuild)

A premium AI insurance adviser built on a **two-brains architecture**:

```
User
  ↓
Discovery flow + Adviser layer (OpenAI)      — understands natural language,
  ↓                                            extracts facts, explains results
Deterministic quote engine                    — eligibility, premiums,
  ↓                                            MUST-HAVE filters, evidence
Verified shortlist / natural advice
```

The deterministic engine is the single source of truth for **facts** (is this
plan eligible, what does it cost). The LLM layer is only ever allowed to
**explain** those facts in natural language — it cannot invent benefits,
override eligibility, or state a price other than the one the engine computed.

## Why this exists

This is a from-scratch rebuild following a full audit of the previous
version (`ashlar-hal-2`). Real business data (Morgan Price 2026 rates,
verified Table of Benefits) is reused as-is; all the code around it — rate
loading, matching, discovery, API, frontend — is new, with these fixes baked
in from day one instead of retrofitted:

- **Hard MUST-HAVE filtering.** A plan that fails a verified mandatory
  requirement (e.g. routine maternity) is fully excluded from the shortlist,
  never shown with a low score. See `tests/test_regressions.py` — this is a
  permanent regression test, not just a design note.
- **Deductible question actually affects price**, if/when you enable it
  (`DEDUCTIBLE_MODEL_ENABLED`). Off by default because no carrier has
  confirmed real deductible-tiered rates yet — see
  `backend/app/rates/deductible_model.py`.
- **Family pricing.** Every dependent is priced against the real rate table
  for their own age; a product is only offered if every family member
  qualifies for it.
- **Chronic conditions asked early**, in the guided flow itself, not buried
  in an edit panel — see `backend/app/discovery/flow.py`.
- **Every optional discovery question has a Skip**, with a sensible default,
  so the flow can never get stuck.
- **Server-side re-verification before any comparison email.** The browser
  sends `plan_keys` + applicant facts, never a premium. The server always
  recomputes the real price before sending. See
  `backend/app/services/leads.py` and `tests/test_leads_security.py`.
- **Rate limiting, explicit CORS, fail-closed security defaults** — all
  absent in the previous version.
- **Curated knowledge layer** (`data/knowledge/`) with verified OECD/Eurostat
  figures for Greece healthcare argumentation, explicit fairness rules
  (never disparage public healthcare, never claim blanket IPMI superiority),
  and HNWI signal detection — separate from the pricing engine, easy to
  update without touching code.

## Known gaps (being honest about scope)

- **Travel insurance** is routed and isolated correctly but not yet priced —
  `orchestrator.py` returns a clear "being built" message and a lead-capture
  CTA rather than pretending to quote it.
- **Voice input/output** is not wired in this rebuild yet.
- **Deductible model discount percentages are illustrative**, pending
  carrier confirmation — do not enable in production before that
  conversation happens.
- **Additional carriers (Now Health, IMG Global Prima, etc.) are added only
  once verified.** Policy confirmed 2026-09: a carrier is onboarded to the
  detailed comparison matrix (`backend/app/evidence/compare_matrix.py`)
  only once you have BOTH a real, structured Table of Benefits AND a real
  current price list for it — never partial or assumed data. Until then,
  `/quotes/compare` includes such plans in the price comparison but reports
  them honestly via `unsupported_note` rather than fabricating benefit rows.

## Running locally

```bash
pip install -r requirements-dev.txt
cp .env.example .env   # fill in what you have; everything has a safe default
python -m pytest tests/ -v
uvicorn backend.app.main:app --reload
```

Then open http://127.0.0.1:8000/.

## Project layout

```
backend/app/
  core/            settings, rate limiting
  schemas/         Applicant, Dependent, QuoteResult (pydantic)
  rates/           CSV loading, deductible model, family pricing, quote engine
  matching/        hard MUST-HAVE filter (the core decision logic)
  evidence/        verified-claim loading + the generation gate
  discovery/       guided question flow
  knowledge/       curated Greece stats, fairness rules, international-vs-local, HNWI
  services/        OpenAI client, adviser prompts, orchestrator, leads/Gmail
  api/             FastAPI routers
data/
  rates/           real Morgan Price 2026 + legacy CSVs
  evidence/        real verified Table of Benefits / claims / documents
  knowledge/       curated JSON content (editable without a code change)
frontend/
  index.html       single-file vanilla frontend, no build step
tests/             102... (run `pytest -v` for the current count)
```

## Deploying

See `railway.json`. Root directory must stay `/` on Railway (Nixpacks reads
the root `requirements.txt`). Health check path is `/health`.
