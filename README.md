# Ashlar HAL — Insurance Adviser (v1 rebuild)

A premium AI insurance adviser built on a **two-brains architecture**:

```
User
  ↓
Discovery flow + Adviser layer (Claude)       — understands natural language,
  ↓                                            extracts facts, explains results
Deterministic quote engine                    — eligibility, premiums,
  ↓                                            MUST-HAVE filters, evidence
Verified shortlist / natural advice
```

The deterministic engine is the single source of truth for **facts** (is this
plan eligible, what does it cost). Claude is only ever allowed to
**explain** those facts in natural language — it cannot invent benefits,
override eligibility, or state a price other than the one the engine computed.

**Three providers, three distinct jobs — not interchangeable:**
- **Claude (Anthropic API)** powers chat, intake understanding, plan
  explanations and the comparison conclusion — HAL's "first analysis" layer.
- **ElevenLabs** is the primary voice provider: Scribe for speech-to-text
  and its standard API for text-to-speech.
- **OpenAI** is reserved for the *planned* deep policy-wording comparison
  feature, and doubles as an automatic transcription fallback if ElevenLabs
  Scribe is unavailable or a request to it fails.

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
- **Travel insurance (Europesure) uses legacy, not-currently-verified
  data.** The three tiers (Silver/Gold/Platinum) and their limits come from
  a legacy HAL export explicitly marked `legacy_unverified_current` — every
  recommendation links to the real Europesure quote portal for current
  price/terms rather than displaying a number HAL invented. See
  `data/travel/europesure/SOURCE-NOTE.md`.

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

## Voice

**Speech-to-text**: ElevenLabs Scribe is the primary provider
(`ELEVENLABS_API_KEY`, `ELEVENLABS_TRANSCRIBE_MODEL`, default `scribe_v2`).
If it isn't configured, or a request to it fails for any reason (outage,
rate limit, network error), transcription automatically falls back to
OpenAI Whisper (`OPENAI_API_KEY`, `OPENAI_TRANSCRIBE_MODEL`, default
`whisper-1`) — provided that key is configured. Only if *neither* provider
is available, or both fail, does the request return an error. The
conversation's current language is pinned explicitly on every request to
either provider — language auto-detection on short utterances proved
unreliable (a single word could come back transcribed in the wrong language
entirely).

**Text-to-speech**: ElevenLabs only (`ELEVENLABS_VOICE_ID`, with optional
`ELEVENLABS_VOICE_ID_EL`/`ELEVENLABS_VOICE_ID_EN` for per-language voices).

Voice is fully optional — if nothing is configured, the mic button and
speaker toggle simply report "unavailable" (503) rather than breaking the
rest of HAL.
Recorded audio is always shown back to the applicant as editable text before
sending, never auto-submitted.

## Deploying

See `railway.json`. Root directory must stay `/` on Railway (Nixpacks reads
the root `requirements.txt`). Health check path is `/health`.
