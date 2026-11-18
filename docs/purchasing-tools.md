# Purchasing tools

## Rate comparison

On a Purchase Order choose **Compare Purchase Rates** after selecting a company,
supplier and items. This is informational and never changes prices or approvals.

- Compare after-discount, pre-tax item values in company currency per stock UOM.
- Select the latest submitted PO for the same company, supplier, item and stock
  UOM, ordered by PO date, creation and name. Exclude the current PO, future PO
  dates and (for saved orders) documents created after the current order.
- Quantity-weight duplicate matching lines on the selected historical PO.
- Missing history or invalid conversion factors display no comparable rate.
  A zero historical rate displays its value but has no percentage change.
- Only history visible through the current user's PO permissions is considered.
- Maximum 200 current item rows per request. Currency conversion uses the exchange
  rates recorded on each PO; the comparison can therefore include FX effects.

## Overdue Supplier Deliveries

Open the report through the PO button or the report list. Select one company;
optionally filter supplier, item, creator and minimum overdue days.

- Submitted orders only; exclude closed, cancelled, completed and delivered POs.
- An item becomes overdue on the day after its required-by date, using site time.
- Pending quantity = max(ordered - ERPNext received quantity, 0), in the PO UOM.
  ERPNext's received quantity is authoritative; do not subtract returned quantity
  again. Receipt/return configurations should be verified in staging.
- Pending value = pending quantity × base net rate, before tax in company currency.
- Direct-to-customer deliveries are excluded because they need delivery tracking
  rather than the normal purchase-receipt calculation.
- Creator is labelled Created By, not assumed to be an assigned buyer.
- Permission-filtered parent orders and per-record checks apply. A report total
  contains only one company's currency.
- Old open orders remain visible. Review historical unfulfilled balances with
  purchasing before closing orders; the report does not automatically close them.

## Deploy and verify

No production configuration or data changes are part of this PR. After normal
app deployment run `bench --site <staging-site> migrate` and build assets using
`bench build --app snrg_supplychain`. Clear site cache and refresh the browser.
No new custom fields or scheduled emails are created.

Local checks: `python3 -m unittest discover -s snrg_supplychain/tests -p test_purchasing_tools.py -v`.
These are mocked boundary tests, not a replacement for an ERPNext integration run.

Before production rollout verify on staging:

1. Same-supplier history, no history, duplicate item lines, multiple UOMs, discounts,
   foreign currency, zero historical prices, backdated/same-day and cancelled POs.
2. Edit a draft's quantity/rate; reopen comparison and check updated net rates.
3. Two users with different company/PO access see only permitted history/report rows.
4. An item due today is absent, yesterday is present, partial receipts reduce quantity,
   full receipts/closed orders disappear, and returns agree with ERPNext's balance.
5. PO buttons coexist with the site's existing email, approval and layout scripts.
6. Compare representative rows against Procurement Tracker and source PO receipts.

Production rollout requires staging review. Existing PO email and workflow settings
are intentionally untouched by the implementation.
