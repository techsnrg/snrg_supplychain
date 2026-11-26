# SNRG Returns — implementation and pilot specification

Implemented inside `snrg_supplychain`, module `Supply Chain`, release based on current `main`. Return transport is independent of all beta Freight
Quotation, freight-rate and outward-shipment calculation code.

## Main release scope

This source release is based on current main and includes the returns module,
its native adapters and portable native form layouts. Separate workspace-only
warehouse/invoicing, reorder and manufacture-request features are excluded.
Published production/disassembly and carton controllers remain unchanged.
The wider workspace browser evidence below includes pages outside this release;
it is not a claim that those separate pages are included here.

## Agreed business policy

- Categories belong to item lines: suspected manufacturing defect, SNRG supply
  error, customer-requested commercial return. Mixed vouchers are supported.
  Preserve claimed reason separately from QC findings; split quantities in QC.
- Commercial returns have no purchase-age limit and no annual cap. Approval is
  case by case. Show customer purchase and return history to the approver.
- Normally consider unused, current, undamaged goods with complete accessories
  and saleable original packaging. Packaging problems, discontinued/custom goods
  need explicit approval; used, incomplete and unsellable goods normally fail.
- Normal return authorization and acceptance exceptions: Managing Director.
  Settlement approval: Accounts Manager by default, configurable to Finance.
  Charge reductions/waivers: configured MD user only, with reason and timestamp.
- Known original invoice first. Optional Find latest sale suggests a line for
  confirmation, with earlier-sales selection. Rates use original invoice net_rate;
  history is filtered by company/customer/currency/item/UOM. No lowest/average or
  latest-price fallback is silently treated as the actual lot's invoice.
- Standard restocking is 25% of accepted fresh/saleable net goods value.
  Separate monetary freight/handling waivers from normal policy allocations.
- SNRG normally arranges and pays the transporter directly. Actual payer is
  separate from ultimate commercial responsibility. Give freight estimate before
  dispatch; reconcile actual bills and customer recovery afterwards.
- Verified manufacturing defects: reasonable pre-approved inward freight borne
  by SNRG. Verified supply errors: SNRG bears reasonable corrective freight.
  Commercial returns and rejected/unauthorized goods: customer responsibility.
  Mixed shipments need a recorded allocation. No beta rate engine is imported.
- Rejection notice: 15 calendar days to dispute, 30 to collect. After dispute
  resolution, collection is the later of original deadline or resolution + 15.
  Disposal requires written customer instructions and internal approval.
- Working-day SLAs: request 3, receipt/QC 7, settlement approval 3, accounting
  document 5. Holiday List includes weekly offs. Record owner/reason/revised date.
- Accepted returns normally settle through credit note. Alternative: customer
  issues sales invoice, SNRG records Purchase Invoice using that customer's
  linked Supplier. No Common Party Accounting dependency. Payment/offset is
  separate and requires an explicit submitted reference before closure.
- Supplier fields: custom_is_customer and custom_linked_customer. Reuse existing
  enabled Supplier; explicitly select when there are multiple linked records.
- No incentives/commissions, portal, automated customer messaging, automatic
  stock/accounting posting, or additional claim reservation system in phase 1.

## Records and flow — stock-first, version 3

New cases use native receiving documents. Physical arrival is inventory acceptance
into a separate Returns — Pending QC warehouse; commercial credit approval follows QC.
There is no custom Return Receipt in the new flow.

1. Custom MRA owns authorization, commercial categories, settlement and closure.
   Native Workflow retains MD authorization/exception approvals, designated-MD
   concessions and Finance final settlement approval.
2. Finance selects a company-specific, non-group Warehouse flagged
   `custom_returns_quarantine`. Route, Supplier and receiving warehouse freeze
   once stock has arrived. Ordinary dispatch/consumption from quarantine is blocked.
3. Native arrival posts **all physically received quantities before QC**:
   - Original Delivery Note exists: native Delivery Note marked Is Return,
     linked to the exact original delivery row, into the Returns warehouse.
   - Original sale was a stock-updating Sales Invoice without a Delivery Note:
     native Stock Entry / Material Receipt at the original outgoing SLE cost.
     Its expense account follows the original sale’s expense account where available.
     No zero-value or selling-price fallback is allowed for this stock cost.
   - Customer issues an invoice: native Purchase Receipt against the linked Supplier,
     at the confirmed acquisition rate. This is a purchase valuation basis, not an
     assumption that the old outgoing sales cost equals the new acquisition price.
4. Native Quality Inspection references the exact submitted native arrival row.
   Templates/readings and product Accepted/Rejected status remain native. Commercial
   Accept/Reject quantity allocations remain separate; failed warranty goods may be
   commercially accepted. A scoped adapter permits post-arrival QC only for tagged
   return arrivals; ordinary purchase/delivery QC settings stay unchanged.
5. Native Material Transfers release commercially accepted allocations to selected
   saleable, repair or scrap warehouses after required MD exception approval.
   Commercially refused goods remain quarantined until collection/return/disposal.
   Native Material Issue records their exit on the sales-return route; native
   Purchase Return reverses refused quantities against the arrival PR on the buying
   route. Evidence and written-instruction/MD disposal controls still apply.
6. Finance prepares accepted allocations directly on MRA. The credit note or
   Purchase Invoice **must not Update Stock**. Supplier invoices link exact PR rows
   and bill accepted quantities only. Restocking/freight/handling recoveries and
   separate native payment/offset references remain unchanged.
7. Global original-source quantity limits, exact QC allocation checks and posted
   disposition limits prevent excess stock receipts and duplicate movements/billing.
   Settlement reconciles native arrival references and accepted invoice allocations.
   Closure additionally requires every QC quantity to leave Pending QC and all
   rejection/dispute/freight conditions to be complete.
8. Optional native Shipment drafts record return pickup directly from MRA.
   Native Assignment Rules/ToDos, system Notifications and the Return Action Queue
   follow the native arrival documents. Native forms provide arrival, inspection,
   disposition and settlement draft buttons; they never auto-submit ledger vouchers.

Stock cost and customer settlement price are distinct. Source-linked sales returns
preserve native outgoing cost; stock-invoice fallback explicitly checks original
posted SLE cost. Native purchases use acquisition valuation. Unresolved stock
sources/costs are blocked for Finance review instead of inventing zero valuation.
Native controllers own all stock and GL posting.

## Historical cases

Versions 1/2, existing custody receipts, inspections, settlement references and
posted stock/accounting records are retained without retroactive receipt posting.
Existing version-2 cases keep their original completion path; their confirmed
custody is not turned into a second stock receipt. Legacy custom Return Inspection
and Return Settlement parents remain read-only. New version-3 cases cannot create
custom Return Receipts, and the old receipt shortcut is removed from active navigation.

## Deployment and configuration

Source built locally and installed on isolated Docker staging; not deployed or enabled on production.

1. Verify deployed app commit against this checkout and inspect current metadata
   again before deployment. Concurrent daily-production work exists in this same
   checkout; do not accidentally bundle it into a returns release.
2. Install/update on an ERPNext v16 staging site first. Normal asset build and
   `bench --site <staging-site> migrate` synchronize schemas/print/workspace and
   create compatible native extensions, Workflow, assignments and system notifications. Repeat migrate to test
   idempotence. No customer, supplier, stock or accounting transactions are seeded.
3. Configure Return Settings: Holiday List, designated MD user, Finance approval
   role, reviewed policy wording and targets. Enable only after configuration.
   The app requires SNRG's existing Managing Director role.
4. Confirm role/user permissions for MRA, Customer, Supplier, original invoices,
   QC and accounting records. Set the designated waiver approver to the MD's own
   account; ordinary MD-role assignment alone must not grant concession approval.
5. Stock must be physically segregated. Flag the Returns — Pending QC warehouse.
   Finance chooses the route and warehouse before native stock arrival. Settlement
   invoices never post a second receipt.
6. For customer-issued invoices, enter customer bill details and attachment,
   correct linked Supplier and the submitted Purchase Invoice. Record any
   gross-value difference and explain it. Link submitted offset/payment and stock
   documents. Finance explicitly reconciles charges and both ledgers.

No GST/account mapping has been invented. Original invoice net_rate incorporates
invoice discounts; post-invoice cash-discount/scheme credits may need separate
Finance reconciliation rather than being silently applied a second time.

## Open policy/configuration items

- No dispatch-expiry default was agreed; there is no invented 30-day expiry.
- No monetary fallback was agreed for genuinely untraceable invoices/lots.
- Confirm exact Finance role, designated MD account, Holiday List and final terms.
- Confirm quarantine posting procedure, charge documents/taxes and the existing
  customer/supplier offset procedure during the accounting pilot.
- Five-day document SLA is applied to the new Purchase Invoice route as well;
  confirm this operational default during pilot.

## Verification

Run from workspace root:

```sh
PYTHONPATH=snrg-supplychain-app .venv/bin/python -m unittest \
  snrg_supplychain.returns.test_policy snrg_supplychain.returns.test_service -v
node --check snrg-supplychain-app/snrg_supplychain/public/js/returns.js
```

Unit/service tests use an explicit Frappe adapter stub and do not constitute a
live ERP integration test. Live metadata inspection succeeded using frappectl
outside the sandbox (OS keyring access). Inspection snapshots are gitignored.
The initial development bench lacked ERPNext. A separate Docker site,
`production-staging.localhost`, now provides Frappe 16.56.0 / ERPNext 16.55.0
with a scoped dataset. Native integration, PDF rendering and real browser tests
have been run there; see the staging verification section below.

Pilot 5–10 cases: known invoice with historical price changes; manual/latest
lookup; mixed categories and multiple shipments; excess/unexpected goods; QC
splits; fresh acceptance and MD-only concession; customer invoice with supplier
mapping and offset; rejected goods/disputes/disposal; user/company restrictions;
credit and Purchase Invoice stock/ledger reconciliation; cancellation of linked
ERP documents; migration twice. Verify the printed customer PDF in the site's
actual letterhead before enabling production.

## Docker staging verification — 26 November 2026 (version 3)

- Database and returns source backed up before installation. Only Docker
  `production-staging.localhost` was changed; production was not deployed.
- Installation checks preserve pre-existing case versions, approval signatures,
  goods values, GL/SLE counts and all historical custom receipts.
- 80 integration assertions pass across native Material Receipt fallback, Delivery
  Note return and Purchase Receipt arrival. Each posts all four units before QC,
  accepts three for settlement, and disposes/returns one refused unit natively.
- Tests verify original outgoing cost separately from selling price, acquisition
  valuation for PR, balanced arrival GL and zero residual quarantine quantity/value.
- Negative tests cover ordinary quarantine consumption, releasing refused stock,
  duplicate disposition, stock-updating settlement invoices, cancellation with
  active QC, cross-MRA source entitlement, MD/Finance separation and closure with
  stock still pending disposition. Ordinary untagged purchase QC remains enforced.
- Repeated installation preserves case signatures, native QC and both ledgers.
  Fifteen existing focused unit tests also pass.
- Nine desktop/mobile browser checks pass without JavaScript errors or missing
  assets, including direct native arrival creation from authorized MRA.
- Current evidence: `staging/results-returns-stock-first.json` and
  `staging/results-returns-stock-first-browser.json`; repeat checks are logged in
  `staging/returns-stock-first-repeat.log`.
- A malformed pre-existing patch-list header blocked full migration. Adding its
  missing `[pre_model_sync]` section preserves the existing patch sequence and
  restores normal migration. Newer shared warehouse hooks were preserved on staging.
- The scoped dataset does not reproduce every production app/configuration;
  production role, warehouse, tax/account and source-document compatibility remain
  release checks before a future authorized deployment.

## Historical verification — 19 November 2026 (version 2)

- Target: `production-staging.localhost`, Frappe 16.56 / ERPNext 16.55, loopback
  `http://127.0.0.1:18081`. Production was not deployed or modified.
- Backup retained before migration. Eleven initial migration checks passed:
  six legacy inspections and five settlements preserved; no GL/SLE posting.
- 87 native integration assertions pass across three closed cases: credit note,
  Purchase Receipt → Purchase Invoice, and direct Purchase Invoice with excess
  goods across multiple shipments. Tests exercise native role separation,
  failed product QC with warranty acceptance, actual transporter bills,
  concessions, charge recovery, offsets, stock reconciliation and cancellation.
- Repeated setup/migration preserves case signatures, QC and legacy counts,
  and both ledgers. Fifteen focused policy/guard unit tests pass.
- Ordinary required purchase inspection still blocks uninspected purchases;
  return reviewers cannot see unrelated QIs. Global QC settings are unchanged.
- Native MRA PDF renders and was visually checked. The PDF test temporarily uses
  container-local port 8000; browser access remains the host proxy on 18081.
- Nine desktop/mobile browser checks pass with no JavaScript errors or missing
  assets, including native Workflow confirmations and custody-to-QI drafts.
- Current browser evidence is in `staging/results-returns-browser.json`; native
  integration evidence is `staging/results-returns-native.json`. Older Nov 17
  custom-flow results are historical and do not validate this refactor.
- Fixtures create clearly labeled synthetic records only on the guarded staging
  site. Existing volumes/data and unrelated app source are preserved.
- The scoped Docker dataset does not reproduce every production customization;
  production compatibility and final role/calendar/account configuration remain
  release checks before any future deployment.

Repeat native acceptance:

```sh
.venv/bin/python snrg-supplychain-app/staging/run_returns.py
```

Stock-first browser script: `tests/staging_returns_stock_first_ui.cjs`. Supply the staging Administrator
password through stdin from OS keyring, never arguments or files.
