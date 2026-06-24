frappe.pages["packed_carton_touch"].on_page_load = function () {
	redirect_to_packing_station();
};

frappe.pages["packed_carton_touch"].on_page_show = function () {
	redirect_to_packing_station();
};

function redirect_to_packing_station() {
	const route = frappe.get_route();
	const token = route && route[1];
	if (token) {
		frappe.set_route("packing_station", token);
		return;
	}
	frappe.set_route("packing_station");
}
