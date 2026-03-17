import frappe
from frappe.model.document import Document
from frappe.utils import flt

class DispatchLog(Document):
	def on_submit(self):
		self.validate_carton_status()
		self.calculate_totals()

		if self.create_delivery_note:
			self.make_delivery_note()

		self.update_carton_box_logs()
		self.db_set('status', 'Submitted')

	def validate_carton_status(self):
		for row in self.cartons:
			status = frappe.db.get_value("Carton Box Log", row.carton_id, "status")
			if status != "Available":
				frappe.throw(f"Carton {row.carton_id} is already dispatched or not available.")

	def calculate_totals(self):
		total_cartons = len(self.cartons)
		total_pieces = 0
		total_gross_weight = 0

		for row in self.cartons:
			cbl = frappe.get_doc("Carton Box Log", row.carton_id)
			total_gross_weight += flt(cbl.gross_weight_kg)
			for item in (cbl.items or []):
				total_pieces += flt(item.qty)

		self.db_set('total_cartons', total_cartons)
		self.db_set('total_pieces', total_pieces)
		self.db_set('total_gross_weight', total_gross_weight)

	def make_delivery_note(self):
		dn = frappe.new_doc("Delivery Note")
		dn.customer = self.customer
		dn.posting_date = self.dispatch_date
		dn.set_posting_time = 1
		dn.company = frappe.db.get_value("Sales Order", self.sales_order, "company")

		for row in self.cartons:
			cbl = frappe.get_doc("Carton Box Log", row.carton_id)
			for item in (cbl.items or []):
				dn.append("items", {
					"item_code": item.item_code,
					"item_name": item.item_name,
					"qty": item.qty,
					"uom": item.uom,
					"stock_uom": item.uom,
					"conversion_factor": 1,
					"warehouse": cbl.warehouse,
				})

		dn.flags.ignore_permissions = True
		dn.insert(ignore_permissions=True)

		frappe.flags.allow_negative_stock = True
		dn.submit()
		frappe.flags.allow_negative_stock = False

		self.db_set("delivery_note", dn.name)

	def update_carton_box_logs(self):
		dn_name = frappe.db.get_value("Dispatch Log", self.name, "delivery_note") or ""

		for row in self.cartons:
			frappe.db.set_value("Carton Box Log", row.carton_id, {
				"status": "Dispatched",
				"dispatch_log": self.name,
				"delivery_note": dn_name,
				"customer": self.customer,
				"dispatched_date": self.dispatch_date
			})

	def on_cancel(self):
		for row in self.cartons:
			frappe.db.set_value("Carton Box Log", row.carton_id, {
				"status": "Available",
				"dispatch_log": "",
				"delivery_note": "",
				"customer": "",
				"dispatched_date": None
			})
		self.db_set('status', 'Cancelled')
