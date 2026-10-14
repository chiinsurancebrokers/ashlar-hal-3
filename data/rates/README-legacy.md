# Legacy carriers — withdrawal and restoration

**Policy change:** on 13 October 2026, APRIL International and IMG Global
were withdrawn from HAL's online quoting because neither carrier has sent
Ashlar a 2026 rate workbook (IMG stated it will not; it offers only a
quote-link redirect, which Ashlar declined). HAL quotes Morgan Price
Europe 2026 only, from the official workbook. The broker can still price
every withdrawn carrier by hand on request.

Nothing on disk was deleted. This note explains **where the legacy
material lives and how to put it back** when a 2026 workbook from either
carrier arrives — or when either carrier is being replaced with a new
rate source. Do not rebuild it from scratch; use what is parked.

## Where the legacy material lives

- `data/rates/legacy_april_img_2025.csv` — the full APRIL and IMG 2025
  Greek-resident rate table, kept in place (same columns and dialect as
  `morgan_price_2026_official.csv`). The loader does NOT read it.
- `data/ui/plan_cards.legacy.json.disabled` — card metadata for every
  APRIL and IMG tier (badge, coverage blurb, annual limit, deductible,
  evacuation note, "why"). The suffix `.disabled` guarantees
  `load_card_meta()` never picks it up. The file carries a `_note`
  explaining the context inside it, and the richer wording previously
  shown on the public site is in Git history (branch `main`, HEAD~1 as
  of 13 Oct 2026).
- `data/evidence/plan_capabilities.json`, `eligibility_rules.json`,
  `carrier_profile.json` — these still reference APRIL and IMG tiers so
  the matching engine remembers them. Nothing to migrate.

## How restoration works

Carry out every step in one PR so the registry, the UI data, the
frontend copy and the tests stay in sync.

1. **Add the new carrier's official workbook** as its own CSV in
   `data/rates/` named `<carrier>_<year>_official.csv` with the same
   columns as the Morgan Price file. Do **not** reactivate
   `legacy_april_img_2025.csv` — those were 2025 figures, kept only for
   reference; nothing in production reads a 2025 rate again.
2. **Extend `backend/app/rates/registry.py`**: inside `load_rates()`,
   add a loader block alongside the existing Morgan Price block
   that opens the new CSV, mirrors the `records.append(...)` call, and
   sets `official=True` and the correct `source`. The dated comment
   above `OFFICIAL_FILE` is the place to retire the "13 Oct 2026
   withdrawal" wording when both carriers are back.
3. **Re-enable the card metadata**: rename
   `data/ui/plan_cards.legacy.json.disabled` to
   `data/ui/plan_cards.img_april.json`, pick out only the keys you are
   actually re-enabling, and merge them into
   `data/ui/plan_cards.json` next to `morgan_price`. Replace the
   placeholder blurbs with the live-site copy from Git history.
4. **Decide the residence gate** per carrier. The old implementation
   (removed on 13 Oct 2026) only priced APRIL and IMG for Greek
   residents, enforced by `_carrier_allowed_for_residence` in
   `quote_engine.py`. If the new workbook keeps that scope,
   reintroduce the gate (one small function, keyed on carrier). If
   it extends to EU residents, write the gate that matches the new
   workbook — do not copy the old one blindly.
5. **Update `frontend/index.html`** footer disclaimer (EN + EL) so it
   stops saying "online quotations use Morgan Price official 2026 rate
   workbook" alone — mention each carrier whose workbook is now
   loaded.
6. **Update `backend/app/rates/quote_engine.py`**: the
   `quote_current()` guard that forces `morgan_price` for area 2/3/4
   should be removed only if the new carrier has verified evidence for
   those areas; otherwise leave it and the new carrier can quote
   area 1.
7. **Tests**: remove the `_IMG_UNAVAILABLE` skip marker from
   `tests/test_quote_engine.py` (and the "only Morgan Price is quoted
   online" regression test — it exists as the opposite guard). Add
   per-carrier assertions in its place: at least one checklist test
   covering the new carrier's benefits, and a residence-gate test
   covering the new scope.

## What NOT to do

- **Do not** reload `legacy_april_img_2025.csv` into production. It is
  a 2025 Greek-residents-only snapshot kept for reference, nothing more.
- **Do not** combine the Morgan Price workbook and the restored
  carrier's workbook into one CSV. Keep each insurer in its own file
  for auditability.
- **Do not** quote any carrier online without a verified 2026+ workbook
  on disk. HAL fairness rule 1: prices never invented. The 13 Oct 2026
  withdrawal was a direct consequence of that rule.
- **Do not** touch the `hal-the-brain` repo as part of this restoration.
  That repo is being upgraded separately; it is not the HAL quoting
  service.

## Git anchor

The commit that performed the withdrawal is the last commit touching
`backend/app/rates/registry.py`, `backend/app/rates/quote_engine.py`,
`backend/app/rates/residence.py`, `data/ui/plan_cards.json`,
`frontend/index.html` and `tests/test_quote_engine.py` together on
13 Oct 2026. Diff against `HEAD` on that commit to see every line that
was in production before withdrawal, including the exact
`_carrier_allowed_for_residence` function body and the richer
plan_cards wording.
