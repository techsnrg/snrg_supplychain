frappe.listview_settings['Daily Production'] = {
  onload(listview) { listview.page.set_title(__('Bulk Production')); },
  refresh(listview) { listview.page.set_title(__('Bulk Production')); },
  primary_action() {
    frappe.route_options = {new_sheet: 1};
    frappe.set_route('daily-production-entry');
  },
  get_form_link(doc) {
    return '/desk/daily-production-entry?sheet=' + encodeURIComponent(doc.name);
  }
};
