frappe.listview_settings['Packed Carton'] = {
	onload(listview) {
		listview.page.set_primary_action(__('Add Packed Carton'), () => {
			frappe.set_route('packing_station', 'new');
		}, 'add');
	},
};
