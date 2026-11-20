import math
import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate, today


class DailyProduction(Document):
    def validate(self):
        previous = self.get_doc_before_save()
        if not frappe.flags.get('in_daily_production_service'):
            if previous and previous.status != 'Draft':
                frappe.throw('Posted or queued sheets cannot be edited. Create a new sheet for more production.')
            station = frappe.get_doc('Production Station', self.station)
            station.check_permission('read')
            self.company = station.company
            self.source_warehouse = self.source_warehouse or station.source_warehouse
            self.target_warehouse = self.target_warehouse or station.target_warehouse
            from snrg_supplychain.supply_chain.daily_production import settings
            settings(self)
            self.status = 'Draft'
            self.settings_snapshot = None
        if getdate(self.posting_date) > getdate(today()):
            frappe.throw('Production cannot be dated in the future.')
        if not self.items or len(self.items) > 100:
            frappe.throw('Enter between 1 and 100 production rows.')
        for row in self.items:
            if not math.isfinite(flt(row.qty)) or flt(row.qty) <= 0:
                frappe.throw(f'Row {row.idx}: quantity must be greater than zero.')
            if not frappe.flags.get('in_daily_production_service'):
                row.status, row.stock_entry, row.error = 'Pending', None, None
                row.bom_no = None
                item = frappe.get_doc('Item', row.item_code)
                item.check_permission('read')
                row.item_name, row.uom = item.item_name, item.stock_uom

    def on_trash(self):
        if self.status != 'Draft':
            frappe.throw('Only unposted drafts can be deleted.')
