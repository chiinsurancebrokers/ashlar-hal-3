# Adviser OS lifecycle implementation — 20 September 2026

The existing stages 1–13 remain on the same AshlarCase. This change extends the
application and post-sale workflow without impersonating a carrier API.

## Implemented in this branch

- Encrypted SQLite adapters for cases, original documents, extracted evidence,
  PDF and PPTX artifacts. Case writes have optimistic concurrency checks in
  durable mode. SQLite transactions serialize independent workers on one volume.
- Separate broker authentication for quotation upload **and analysis**, broker
  application sections, external submission recording, issuance, reconciliation,
  carrier decisions, payments and broker handoff ZIP exports.
- Application sections record explicit information and linked evidence. Signature
  sections require an uploaded document. This is not an electronic signature
  service and does not certify carrier-specific forms.
- Issued policies require an uploaded schedule. Wallet and post-sale coverage
  checks use only broker-reconciled facts from issued schedules/applicable wording.
  Brochure and quote facts do not automatically become issued cover.
- Claims and pre-authorisations have validated transitions, carrier references,
  evidence attachments and event histories. Paid claims require amount/currency.
  Carrier decisions require an uploaded carrier-response document.
- Lifecycle document review extracts candidate dates/amounts and source text;
  candidates never update coverage or settle claims automatically.
- Renewal preserves the issued baseline and application history, requires current
  intake confirmation for refreshed registry quotes and retains original rate
  provenance. No invented Cigna/GPMI current premiums.
- Broker conflict resolution retains a verified winner, supersedes competing
  facts and blocks stale proposal export until the comparison is rebuilt from
  the verified ledger. Existing proposal quality checks remain in force.
- Client/broker workspace, original-document downloads, private case-access file
  export/restore, policy wallet, claims/pre-authorisation forms and renewal review.
- Asklepios supports an external web handoff without sending clinical data.
  Its live staging service is Streamlit, not the assumed `/v1/navigate` API.

## Deployment prerequisites and remaining limits

Set `ASHLAR_DB_PATH=/data/ashlar.sqlite` **only after** mounting a persistent volume
at `/data`; set `ASHLAR_STORAGE_KEY` to a separately backed-up Fernet key. Losing
that key loses access to stored data. `ASHLAR_RETENTION_DAYS` defaults to 365.
Retention must be chosen deliberately for the deployment. Back up the database
and key independently, and verify restoration before using personal client data.
Do not add the key, database, client documents or quotations to Git.

No DB path means explicit temporary process-local storage. `/health` and the
workspace report the configured mode. Never claim a restart-safe deployment from
code-level tests alone. SQLite is suitable for the existing single-volume
service, not independently deployed services without a shared database.

The Railway connector reported `Agent usage limit reached` when asked to attach
staging storage. No volume or storage environment variable was provisioned in
this run. Persistent staging activation therefore remains blocked.

Carrier submissions, policy issuance, approvals and payments are **external
facts recorded by a broker**, not actions transmitted by Ashlar. Current carrier
application forms, actual integration credentials/contracts, live current
Cigna/GPMI pricing and full brochure/wording coverage are not manufactured by
this implementation. Existing catalogue unknowns remain unknown.

The UI uses case capability tokens and the existing broker password mechanism;
it is not a multi-user identity/role administration system. Reminders are visible
renewal due-day indicators, not scheduled outbound notifications. Asklepios API
integration and production readiness are not claimed.

## Verification

Run `.venv/bin/python -m pytest -q`, `node --check frontend/lifecycle.js`,
`node --check frontend/adviser-os.js`, and `git diff --check`.
`test_durable_lifecycle.py` covers encrypted restart recovery, stale writers,
wrong tokens/keys, original document and proposal recovery, application role
checks, source-backed issued terms, cross-case evidence rejection, carrier
response gates and payment transitions. Existing real PDF/PPTX tests remain.
