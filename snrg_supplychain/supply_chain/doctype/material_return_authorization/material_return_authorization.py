from frappe.model.document import Document
from snrg_supplychain.returns.native_service import validate_mra


class MaterialReturnAuthorization(Document):
    def validate(self):
        validate_mra(self)
