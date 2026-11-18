# Purchasing Docker verification

Environment verified: local Compose project `snrg-production-staging`, container
`snrg-production-staging-app-current-1`, site `production-staging.localhost`.
Frappe 16.56.0 / ERPNext 16.55.0. Internal Docker network, localhost proxy on
18081, emails muted and scheduler disabled. No production calls or writes.

`test_purchasing_docker.py` runs real database/controller/permission checks and
rolls back all fixtures, even on failure. Run after installing the feature files
and migrating this local site:

```
docker cp staging/test_purchasing_docker.py snrg-production-staging-app-current-1:/tmp/test_purchasing_docker.py
docker exec snrg-production-staging-app-current-1 env/bin/python /tmp/test_purchasing_docker.py
```

`docker-results.json` contains 21 passed assertions plus an observation of
ERPNext receipt/return quantities. Coverage includes actual submitted POs,
cancellations, backdating, FX, alternate UOM, duplicate discounted lines,
Purchase Receipts and returns, partial/full receipts, due-today, closed and
supplier-delivered lines, and actual restricted-user/company permissions.

`test_purchasing_http.py` verified login and both real HTTP endpoints as a
short-lived Purchase User. It keeps its random password in memory, removes
the test user in `finally`, and never accesses production. It expects the
browser fixtures below. Both endpoints passed: the comparison returned 100
versus 110; the report returned 14 columns and one overdue row with 10 pending.

`create_purchasing_ui_fixtures.py` creates clearly marked disposable records
for a browser check. These remain in local staging for review: supplier `PURCHASING UI TEST ONLY`, item
`PURCHASING-UI-TEST-ONLY`, history PO `PUR-ORD-2026-00001`, draft PO
`PUR-ORD-2026-00002`. Avoid rerunning the creator without cleaning up first.

After signing into localhost as Administrator:

1. Open `/desk/purchase-order/PUR-ORD-2026-00002`.
2. Click Compare Purchase Rates; expect previous 100, current 110, +10%.
3. Change draft rate to 120; reopen comparison and expect +20% without saving.
4. Click Overdue Supplier Deliveries, select SNRG Production Staging and
   the test supplier; expect the history PO with 10 pending, INR 1,000 pre-tax.
5. Check source PO link, smaller browser width and coexistence with other buttons.

Browser verification completed on 2026-11-19 in the local in-app browser:
- An authenticated direct PO URL reached Desk; the login screen had remained
  visible despite a valid session. No further password reset was needed.
- Restored the PO script hook in the shared staging container (the PR already
  includes it), cleared cache, and restarted only the local web process.
- Current 110 versus previous 100 displayed +10%. An unsaved draft rate of
  120 displayed +20%, then was restored to 110 without saving.
- Overdue report navigation preserved company and displayed one PO, pending
  quantity 10, and INR 1,000 before tax. Minimum days 99 plus Refresh showed
  Nothing to show; restoring 1 plus Refresh restored the result.
- Desktop controls and narrow-width overflow menu both exposed the tools.
- Replaced the comparison's legacy /app/ source URL with Frappe's standard
  get_form_link helper for version-correct Desk URLs.
- Staging lacks socket.io, so realtime connection warnings remain unrelated
  to the successful comparison/report requests.

To remove the marked browser examples after review, copy and run
`cleanup_purchasing_ui_fixtures.py` in the same container. It refuses to run
outside this muted staging site and checks each PO's disposable marker.

Assets built successfully with `bench build --app snrg_supplychain`; migrate
registered the report. The stopped staging web server was restarted locally.
No existing containers/volumes or unrelated staging apps were replaced.
