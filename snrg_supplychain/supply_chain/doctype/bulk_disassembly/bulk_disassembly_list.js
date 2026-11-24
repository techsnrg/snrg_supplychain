frappe.listview_settings['Bulk Disassembly'] = {
  onload(listview) { listview.page.set_title(__('Bulk Disassembly')); },
  refresh(listview) { listview.page.set_title(__('Bulk Disassembly')); },
  primary_action() {
    frappe.route_options = {new_sheet: 1};
    frappe.set_route('bulk-disassembly-entry');
  },
  get_form_link(doc) {
    return '/desk/bulk-disassembly-entry?sheet=' + encodeURIComponent(doc.name);
  }
};
