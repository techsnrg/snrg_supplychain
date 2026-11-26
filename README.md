# SNRG Supply Chain

Supply Chain & Carton Management Module for SNRG Electricals India Pvt. Ltd.

## License

MIT

## Returns and layouts

Returns use a custom MRA, native arrival into a Returns quarantine warehouse,
native post-arrival Quality Inspection, controlled disposition, and non-stock
settlement invoices. See [RETURNS.md](RETURNS.md). Requires the tested ERPNext /
Frappe v16 environment for scoped DocType mixins.

Custom forms use native grouped columns and task-based tabs. Main's existing
production/disassembly and packing pages share scoped responsive layout styles.
This release preserves main's production draft-deletion updates and existing
carton/shipment data fields. Separate workspace warehouse/invoicing, manufacture
request and reorder features are intentionally excluded.

Staging evidence from the integrated workspace: 80 stock-first integration
assertions, 39 layout browser checks, 82 layout preservation checks and 15 focused
returns unit tests. The published subset additionally passes main's existing
production/disassembly tests. This is a source release only, not a production
deployment.
