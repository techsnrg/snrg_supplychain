import frappe
from frappe.model.document import Document
from frappe.utils import flt

class CartonBoxLog(Document):
	def before_save(self):
		self.set_box_type_details()
		self.set_item_details()
		self.calculate_weights()

		if not self.status:
			self.status = "Available"

	def set_box_type_details(self):
		if self.box_type:
			try:
				box_doc = frappe.get_cached_doc("Carton Box Type", self.box_type)
				self.dimensions = f"{box_doc.length_cm} × {box_doc.width_cm} × {box_doc.height_cm} cm"
				self.empty_weight_kg = flt(box_doc.empty_weight_kg)
			except Exception:
				pass

	def set_item_details(self):
		for row in (self.items or []):
			if row.item_code:
				try:
					item_doc = frappe.get_cached_doc("Item", row.item_code)
					row.item_name = item_doc.item_name
					if not row.uom:
						row.uom = item_doc.stock_uom
					if not row.item_weight_kg:
						row.item_weight_kg = flt(getattr(item_doc, "weight_per_unit", 0))
				except Exception:
					pass

	def calculate_weights(self):
		net = 0.0
		for row in (self.items or []):
			net += flt(row.qty) * flt(row.item_weight_kg)

		self.net_weight_kg = net
		self.gross_weight_kg = net + flt(self.empty_weight_kg)
