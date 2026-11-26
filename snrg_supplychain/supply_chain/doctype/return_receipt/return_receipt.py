from frappe.model.document import Document
from snrg_supplychain.returns.native_service import validate_receipt


class ReturnReceipt(Document):
    def validate(self):
        validate_receipt(self)
