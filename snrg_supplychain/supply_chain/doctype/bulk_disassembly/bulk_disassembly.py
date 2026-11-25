import math
import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate, today


class BulkDisassembly(Document):
    def validate(self):
        previous = self.get_doc_before_save()
        if not frappe.flags.get('in_bulk_disassembly_service'):
            if previous and previous.status != 'Draft':
                frappe.throw('Posted or queued sheets cannot be edited. Create a new sheet for more disassembly.')
            station = frappe.get_doc('Production Station', self.station)
            station.check_permission('read')
            self.company = station.company
            self.source_warehouse = self.source_warehouse or station.target_warehouse
            self.target_warehouse = self.target_warehouse or station.source_warehouse
            from snrg_supplychain.supply_chain.bulk_disassembly import settings
            settings(self)
            self.status = 'Draft'
            self.settings_snapshot = None
        if getdate(self.posting_date) > getdate(today()):
            frappe.throw('Disassembly cannot be dated in the future.')
        if not self.items or len(self.items) > 100:
            frappe.throw('Enter between 1 and 100 disassembly rows.')
        for row in self.items:
            if not math.isfinite(flt(row.qty)) or flt(row.qty) <= 0:
                frappe.throw(f'Row {row.idx}: quantity must be greater than zero.')
            if not frappe.flags.get('in_bulk_disassembly_service'):
                row.status, row.stock_entry, row.error = 'Pending', None, None
                row.bom_no = None
                item = frappe.get_doc('Item', row.item_code)
                item.check_permission('read')
                row.item_name, row.uom = item.item_name, item.stock_uom

    def on_trash(self):
        # Protect native deletion as well as the custom screen against a posting race.
        frappe.db.sql('select name from `tabBulk Disassembly` where name=%s for update', (self.name,))
        status = frappe.db.get_value(self.doctype, self.name, 'status')
        if status != 'Draft':
            frappe.throw('Only unposted drafts can be deleted.')

        if frappe.db.exists('Stock Entry', {'custom_bulk_disassembly': self.name}):
            frappe.throw('This sheet has linked Stock Entries and cannot be deleted.')
