// SNRG Supply Chain — Supplier list customisation
// Hide the "+ Add Supplier" button for non-System-Manager users
// so junior staff viewing Transporters cannot accidentally create suppliers.

frappe.listview_settings["Supplier"] = {
	onload(listview) {
		if (!frappe.user.has_role("System Manager")) {
			listview.page.btn_primary.hide();
		}
	},
};
