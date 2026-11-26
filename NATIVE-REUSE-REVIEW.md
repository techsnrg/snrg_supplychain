# Returns native-feature reuse review

19 November 2026. Read-only inspection of live SNRG metadata, current settings,
active workflows, QC templates and installed versions. Controller behavior was
checked against the matching Docker core: Frappe 16.56.0 / ERPNext 16.55.0.
No production configuration or business records were changed. The mapped refactor is now implemented and tested on Docker staging only.
The November 26 stock-first revision replaces new custom custody receipts with
native receiving into Returns — Pending QC. See RETURNS.md and
staging/results-returns-stock-first.json for current implementation evidence.

## Recommended shape

Use ERPNext Stock, Buying, Accounts and Quality Inspection; use Frappe Workflow,
Assignment Rule, Notification, ToDo, Print Format, Letter Head and audit history.
Retain two custom operational parent records:

1. Material Return Authorization: commercial case, authorization, approved lines,
   settlement review, concessions, dispute/disposition and closure.
2. Return Receipt: a thin non-posting custody receipt for actual cartons/items,
   unauthorized arrivals and multiple shipments. Label clearly as custody only.

Keep a small Return Settings singleton for return-specific policy/calendar/user
settings that are not already represented by Workflow or Terms and Conditions.
Keep necessary child tables and small integration code. Fewer parent records do
not mean that commercial allocations or validations can be discarded.

Replace the standalone custom Return Inspection parent with native Quality
Inspection plus a return-specific extension. Merge the standalone Return
Settlement into the MRA's settlement/reconciliation sections and linked child
rows. Retain a separate settlement parent only if independently approved partial
settlements become an explicit requirement; it is not necessary for the currently
agreed per-case commercial approvals. All posted stock and accounting entries
remain standard ERPNext documents.

## Complete feature map

| Function | Classification | Proposed implementation / customization |
|---|---|---|
| Customer, contact and address | Native | Existing Customer, Contact and Address. No parallel masters. |
| Items, UOM, serial/batch identity | Native | Reuse Item, UOM and standard batch/serial tracking where actually used. Do not introduce serial tracking just for returns. |
| Return request / permission to dispatch | Custom necessary | MRA + item lines; claimed category/quantity, approved quantity/value, invoice references and frozen customer terms. |
| Original sale valuation | Native + small integration | Native submitted Sales Invoice item net_rate and standard return mapper. Custom optional latest-sale suggestion/confirmation on MRA; no invented untraceable-lot fallback. |
| Commercial and MD concession approvals | Native Frappe + configuration | Workflow states, transitions, roles and Workflow Actions on MRA. Exact designated-MD condition for concessions and server validation of amounts/identity. Do not rewrite workflow engine. |
| Customer PDF and acceptance evidence | Native framework + custom layout | Letter Head, Terms and Conditions, Print Format and attachments. Keep MRA layout and policy snapshot. |
| Pickup and transport tracking | Native + small customization, optional | Shipment supports Customer pickup and Company delivery, parcels, tracking/AWB and carrier. Add MRA/custody reference and Supplier transporter link if used. Existing native LR fields suffice for simple cases. |
| Freight commercial allocation | Custom policy on native records | Estimated vs actual amount, arranged/paid by versus cost borne by, customer share and waiver. Store on Shipment/case/custody as appropriate; actual vendor liability remains Purchase Invoice. No beta freight engine. |
| Physical receipt before commercial acceptance | Thin custom necessary | Non-posting Return Receipt records custody. Native stock receipt submission can change stock/GL and is not an ownership-neutral gate pass. |
| QC measurements, templates and evidence | Native + moderate scoped extension | Quality Inspection, Quality Inspection Template, readings, inspector, sample size, batch/serial and submission. Add return/custody link and controlled adapter for pre-stock references. |
| QC quantity classification and commercial disposition | Custom extension necessary | Return-specific quantity breakdown and findings/acceptance alongside native QI; totals reconcile to custody receipt. Failed product quality and accepted warranty return are distinct outcomes. |
| Accepted stock: credit-note route | Native + reference links | Appropriate return Delivery Note or stock-updating credit note according to original sale. Add MRA/custody/allocation links; never receive the same stock twice. |
| Accepted stock: customer-invoice route | Native + reference links | Purchase Receipt followed by Purchase Invoice without Update Stock, or one Purchase Invoice with Update Stock. Only quantities admitted under the agreed accounting treatment. |
| Quarantine, transfer and scrap of company-owned stock | Native configuration | Warehouse, Material Transfer and appropriate standard stock document. A quarantine warehouse still belongs to the stock ledger. |
| Credit note | Native | Sales Invoice marked Is Return, linked to original invoice wherever identifiable. Native rate/tax/accounting logic retained. |
| Customer-issued bill | Native + small mapping | Purchase Invoice and Supplier; add custom_is_customer checkbox and custom_linked_customer Customer link. No Common Party Accounting dependency. |
| Restocking / handling / customer freight recovery | Native posting + custom eligibility | Standard non-stock service/charge billing or Finance-approved charge document, with native tax/account configuration. Custom 25% eligibility calculation and MD concession validation. |
| Transporter bill and payment | Native | Supplier (Is Transporter), Purchase Invoice, Payment Entry and accounting references; no custom payable ledger. |
| Customer–supplier offset | Native | Journal Entry with Customer/Supplier party and invoice references, or actual payment. Supplier mapping alone does not offset balances. |
| Final settlement review / closure | Custom coordination + native Workflow | MRA settlement section aggregates submitted native documents, allocations and concessions; Finance approval, reconciliation and closure remain case rules. No separate accounting engine. |
| Rejection notice, dispute and collection | Custom case fields + native tools | MRA/custody dates and disposition; attachments/Communication, Notification and ToDo. 15/30 calendar-day policy and resolution extension need small return-specific date logic. |
| Customer complaint / dispute ticket | Native optional | Link an Issue when an actual support conversation needs ownership; not a mandatory extra ticket for every return. |
| Systemic defect follow-up | Native optional | Quality Action / Review for corrective/preventive action; not the return authorization or QC receipt. |
| Owners and reminders | Native + small date calculation | Assignment Rule, ToDo, Notification, Holiday List. Keep multi-stage 3/7/3/5 working-day prerequisite logic; do not treat an Issue response/resolution SLA as a drop-in four-stage clock. |
| History and pending work | Native + small custom report | Standard customer/supplier ledgers, stock ledger and document links; one cross-document return reconciliation/action report for case-specific information. |
| Audit and role access | Native + focused validation | Roles/User Permissions, Version, Workflow Action, comments and submitted-document lifecycle; small guards only for frozen approval data and return-specific invariants. |

## Native records needing additions

- Quality Inspection: MRA/custody/receipt-line reference and return quantity
  disposition table. A scoped adapter is needed, not merely a Link field:
  native reference_type currently allows Purchase Receipt/Invoice,
  Subcontracting Receipt, Delivery Note, Sales Invoice, Stock Entry and Job Card;
  native code writes references back to item rows. Preserve those paths. Test
  item selection, row identity, batch/serial, submit/cancel and posted-document
  protection when introducing the custody reference. Avoid enabling global Item
  inspection-before-purchase/delivery flags merely to make return selection work.
- Supplier: the two explicit Customer-link fields requested by the user. The
  existing customer_numbers table is customer-specific supplier reference text;
  it is not a substitute for an ERP Customer link. These return mapping fields
  are absent from live Supplier metadata and currently exist only in staging.
- Shipment (if used): MRA/custody Link, transporter Supplier Link, estimated cost,
  actual bill reference and cost responsibility/customer allocation. Standard
  Shipment already provides pickup/delivery parties, dates, carrier, AWB,
  tracking, parcels, weight and shipment amount. It requires addresses, pickup
  time window, parcel weights and goods value; do not invent data just to force
  a simple LR into Shipment.
- Delivery Note / Sales Invoice / Purchase Receipt / Purchase Invoice: MRA Link
  and receipt/line mapping as needed for traceability. Prefer existing native
  source invoice/receipt row references; do not duplicate them. Customer-issued
  Purchase Invoice can also expose the linked Customer for return cases.
- Journal Entry / Payment Entry: optional MRA Link. Existing native party and
  invoice-reference fields continue to drive ledger settlement.
- Issue: optional MRA Link if tickets are used. Do not add a separate custom
  support/dispute engine.

No ERPNext core-file edits are recommended. Use version-controlled custom fields,
workflow/configuration fixtures, print formats and narrow app hooks in
snrg_supplychain. Basic form changes and native document links are small; the
pre-acceptance QC adapter, quantity disposition and commercial reconciliation
are actual integration work and must not be described as configuration alone.

## Live-site findings affecting the design

- Frappe 16.56.0, ERPNext 16.55.0 and India Compliance 16.11.0 are installed.
- Quality Inspection and Shipment have no custom fields in the inspected live
  metadata. No Quality Inspection Templates were returned by the live listing.
- Existing active workflows cover PO and several HR records; none was listed for
  Quality Inspection, Purchase Receipt, Sales Invoice or Purchase Invoice.
  Add the return workflow to MRA rather than silently changing all invoice or
  procurement approvals. One active workflow per DocType affects all its cases.
- Stock Settings: allow_to_make_quality_inspection_after_purchase_or_delivery=0;
  action_if_quality_inspection_is_rejected=Stop; unsubmitted QI=Stop. Do not weaken
  these site-wide settings to make the new return process pass.
- Native stock controller skips its ordinary inspection validation for is_return
  documents in the inspected core. Explicit return-only QC completion and
  commercial-acceptance gating is therefore still needed.
- A rejected product-quality result does not automatically mean the customer
  return is commercially rejected. Return-specific templates/decisions must
  preserve this distinction, especially on ordinary Purchase Receipts where the
  global rejected-QI Stop control can apply. Verify both accounting routes before
  promising that adding only a QI Link is sufficient.
- Buying Settings: Purchase Order and Purchase Receipt are not globally required;
  maintain_same_rate=0; bill_for_rejected_quantity_in_purchase_invoice=1;
  set_valuation_rate_for_rejected_materials=0. Supplier-specific rules may differ.
  Return-specific checks must keep commercially refused quantities out of the
  payable/credit. Do not flip global buying settings without evaluating normal
  procurement.
- Receive from Customer/customer-provided stock is a manufacturing/customer-owned
  material feature. It is not an automatic replacement for returned stock that
  SNRG previously sold; no global Item ownership/valuation flags should be changed.
- Landed Cost Voucher allocates eligible costs into inventory valuation; it is
  not a customer-freight recovery document. Use only where Finance explicitly
  requires capitalization of the relevant cost.
- Warranty Claim is a support/warranty record, with single item/serial-oriented
  fields and no mixed-item authorization/value/allocation table. It is optional
  for suitable warranty cases, not a replacement for this MRA.

## Implemented refactor and validation sequence

1. Retain all tested records and production data; take a staging snapshot before
   schema migration. Do not delete the custom inspection/settlement history.
2. Prototype the native QI adapter in staging against unposted custody and both
   native stock routes, including failed tests with commercial warranty acceptance.
3. Move approval transitions to native Workflow on MRA. Keep only business guards
   and designated-MD concession conditions in server code.
4. Move settlement references, charge approvals and rejection/disposition fields
   onto MRA/custody. Migrate old inspection evidence and settlement references with
   a traceable mapping; keep old records read-only until reconciliation passes.
5. Replace custom reminder creation with Assignment Rule/Notification/ToDo where
   appropriate, retaining the precise return-specific deadline calculations.
6. Re-run end-to-end native stock/GL, partial/mixed receipts, failed-QI, native
   cancellation, Supplier mapping, customer-issued invoice/offset and printed
   customer-terms checks. The earlier 43 native and 8 browser checks validate the
   old architecture. The refactor now passes 87 native assertions, 9 browser
   checks, 15 focused unit tests, the legacy migration check and repeated
   migration preservation. See RETURNS.md for current evidence.

## Primary documentation reviewed

- Quality Inspection: https://docs.frappe.io/erpnext/user/manual/en/quality-inspection
- Workflows: https://docs.frappe.io/erpnext/workflows
- Shipment: https://docs.frappe.io/erpnext/shipment
- Purchase Receipt: https://docs.frappe.io/erpnext/purchase-receipt

Live metadata/settings snapshots are gitignored under inspection/native-review.

The main release excludes separate workspace warehouse/invoicing and reorder work.
Existing main data-field definitions and production/packing controllers are preserved.
