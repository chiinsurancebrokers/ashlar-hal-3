# Adviser OS boundary — 21 September 2026

The CHI Insurance Portal (`chiinsurancebrokers/portal`) is the system of record
for permanent client documents and the post-sale lifecycle. It already uses
Postgres and contains policy, document, claim and renewal/expiry models and UI.

Adviser OS owns steps 1–14: discovery, interview, AshlarCase, quotes, shortlist,
carrier quotation analysis, evidence conflicts, verified comparison, HAL
explanation, Ashlar Assessment, PDF/PPTX, final plan selection and application
preparation. After the external carrier submission is recorded, the broker can
download the reviewed application handoff pack and continue in the authenticated
CHI Portal.

No document is automatically transmitted between the two systems. The current
Portal exposes authenticated agent/client form uploads but has no service-to-service
upload endpoint. The Adviser OS link therefore opens the Portal login and avoids
putting client identifiers or access tokens in the URL. A future automatic bridge
would require a narrow Portal ingestion API, service authentication, idempotency,
client matching and an audit record; it is outside the current scope.

The encrypted SQLite adapter and post-sale workflow code remain dormant for
compatibility and tests. The default `POST_SALE_SYSTEM_OF_RECORD=chi_portal`
blocks local issuance, post-sale documents, Policy Wallet, claims, pre-authorisation
and renewal endpoints with an explicit Portal handoff. We will not provision an
Adviser OS persistent volume for this scope. Temporary Adviser OS case/evidence
storage supports the active advice session and handoff pack only.

Asklepios remains the external owner of health navigation.
