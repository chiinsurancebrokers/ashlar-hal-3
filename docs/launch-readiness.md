# Client launch readiness — 21 September 2026

Implemented in feature/adviser-os:
- Current official rate prices only on public shortlist, comparison and priced emails.
- GPMI/Inspire known benefit gaps excluded; optional/unknown needs kept conditional.
- Deterministic ranking by confirmed needs and uncertainty. Eligibility is explicitly pending where no structured carrier rule exists.
- Brochure evidence is not overwritten by model-extracted Provider Library content.
- Needs-led walkthrough, visible uncertainty/next step and follow-up controls.
- Server-rebuilt selected plans/needs included in the broker enquiry, with receipt reference.
- Authenticated source excerpts and explicit missing-wording indicators.
- Mobile modal isolation, bounded cards, horizontal comparison scrolling, readable inputs.
- AI/provider time budgets, browser request deadline, fail-closed durable-storage opt-in.

Release blockers / validation boundaries:
1. Staging service adviser-os currently has no persistent volume. The available direct Railway configuration tools do not expose volume creation. Configure a persistent mount, ASHLAR_DB_PATH on that mount and an independent Fernet ASHLAR_STORAGE_KEY. Set ASHLAR_RETENTION_DAYS=7 and ASHLAR_REQUIRE_DURABLE_STORAGE=true. Restart tests validate encrypted recovery locally; do not claim staging restart recovery before provisioning and a live redeploy test.
2. IMG GPMI matching full wording remains unverified. Library title search found gpmi-brochure (3).pdf only. Official IMG forms pages expose product documents but a matching full wording/version has not been retrieved. Do not substitute another IMG family or IPID.
3. Cigna reference located: Inspire Belgium Policy V2.10 SAMPLE - effective 9 Sept 2026.pdf, Library libfile_118683a0a1ec819188489d8bcc183be2. Page 1 explicitly says sample, not a contract; page 14 identifies the Inspire family. This is a reference candidate, not a client governing schedule. Do not publish private Library PDFs into the public repository or mark individual contractual terms verified from it.
4. Physical iPhone acceptance still requires device testing. Local Chromium/WebKit executables were absent and browser downloads timed out; CSS/JavaScript syntax checks passed, but visual acceptance remains outstanding.
5. Lead delivery tests intercept the mail transport. No synthetic email is sent to the broker/client in live verification.

Infrastructure remains temporary comparison storage only. CHI Portal retains ownership of permanent policy documents, policy wallet and renewal.
