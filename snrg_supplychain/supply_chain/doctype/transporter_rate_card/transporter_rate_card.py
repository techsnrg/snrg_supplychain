import frappe
from frappe.model.document import Document
from frappe.utils import today, getdate


class TransporterRateCard(Document):

	def before_save(self):
		self.update_is_active()

	def on_submit(self):
		self.update_is_active()

	def update_is_active(self):
		"""Auto-compute is_active based on validity dates."""
		t = getdate(today())
		valid_from = getdate(self.valid_from) if self.valid_from else None
		valid_to = getdate(self.valid_to) if self.valid_to else None

		if valid_from and t >= valid_from:
			if valid_to is None or t <= valid_to:
				self.is_active = 1
				return
		self.is_active = 0

	def validate(self):
		if self.valid_to and self.valid_from:
			if getdate(self.valid_to) < getdate(self.valid_from):
				frappe.throw("Valid To cannot be before Valid From.")
