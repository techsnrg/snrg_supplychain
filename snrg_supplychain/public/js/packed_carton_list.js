frappe.listview_settings['Packed Carton'] = {
	onload(listview) {
		listview.page.set_primary_action(__('Open Packing Station'), () => {
			frappe.set_route('packing_station', 'new');
		}, 'add');
	},
};
