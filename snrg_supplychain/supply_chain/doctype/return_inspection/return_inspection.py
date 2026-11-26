from frappe.model.document import Document
from snrg_supplychain.returns.native_service import legacy_read_only


class ReturnInspection(Document):
    def validate(self):
        legacy_read_only(self)
