import frappe
from frappe.model.document import Document

class CartonBoxLog(Document):
	def before_save(self):
		from frappe.utils import flt
		
		if self.box_type:
			box_doc = frappe.get_doc("Carton Box Type", self.box_type)
			self.dimensions = f"{box_doc.length_cm} × {box_doc.width_cm} × {box_doc.height_cm} cm"
			self.empty_weight_kg = flt(box_doc.empty_weight_kg)

		net = 0.0
		if getattr(self, "items", None):
			for row in self.items:
				if row.item_code:
					item_doc = frappe.get_doc("Item", row.item_code)
					row.item_name = item_doc.item_name
					row.uom = getattr(row, "uom", item_doc.stock_uom)
					row.item_weight_kg = flt(getattr(row, "item_weight_kg", item_doc.weight_per_unit))
				net += flt(row.qty) * flt(row.item_weight_kg)
				
		self.net_weight_kg = net
		self.gross_weight_kg = net + flt(self.empty_weight_kg)
		
		if not self.status:
			self.status = "Available"
