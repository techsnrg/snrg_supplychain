frappe.ui.form.on('Bulk Disassembly', {
  refresh(frm) {
    if (frm.is_new()) {
      frappe.route_options = {new_sheet: 1};
      frappe.set_route('bulk-disassembly-entry');
      return;
    }
    const open = () => {
      frappe.route_options = frm.is_new() ? {new_sheet: 1} : {disassembly_sheet: frm.doc.name};
      frappe.set_route('bulk-disassembly-entry');
    };
    frm.add_custom_button(__('Open Bulk Disassembly'), open);
    if (!frm.is_new() && !frm.is_dirty()) {
      frm.page.set_primary_action(__('Open Bulk Disassembly'), open);
    }
  }
});
