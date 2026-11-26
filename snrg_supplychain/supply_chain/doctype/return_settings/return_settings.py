import frappe
from frappe.model.document import Document


class ReturnSettings(Document):
    def validate(self):
        if self.enabled:
            if not self.holiday_list or not self.waiver_approver or not self.policy_terms:
                frappe.throw('Holiday List, designated MD user and policy terms are required.')
            if 'Managing Director' not in frappe.get_roles(self.waiver_approver):
                frappe.throw('Designated waiver approver must have Managing Director role.')
        if self.settlement_approver_role == 'Managing Director':
            frappe.throw('Final settlement approval must remain with Finance.')
        if float(self.restocking_percent or 0) != 25:
            frappe.throw('The agreed restocking charge is 25 percent.')
        for key in ('authorization_days', 'inspection_days', 'settlement_days', 'document_days'):
            if not 0 < int(self.get(key) or 0) <= 365:
                frappe.throw('Working-day targets must be between 1 and 365.')

    def on_update(self):
        old = self.get_doc_before_save()
        if old and old.settlement_approver_role != self.settlement_approver_role and frappe.db.exists('Workflow', 'SNRG Return Case Workflow'):
            from snrg_supplychain.returns.native_setup import configure
            configure()
