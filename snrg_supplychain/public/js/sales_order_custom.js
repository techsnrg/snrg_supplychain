// SNRG Supply Chain — Sales Order customisation
// • Removes ERPNext's "Pick List" from the Create dropdown
// • Adds "Outward Shipment" to the Create dropdown

frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;

		// ── Remove Pick List ────────────────────────────────────────────
		frm.remove_custom_button(__("Pick List"), __("Create"));

		// ── Add Outward Shipment ─────────────────────────────────────────
		frm.add_custom_button(
			__("Outward Shipment"),
			function () {
				frappe.route_options = {
					sales_order: frm.doc.name,
					customer: frm.doc.customer,
				};
				frappe.new_doc("Outward Shipment");
			},
			__("Create")
		);
	},
});
