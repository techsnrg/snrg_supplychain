import frappe
from frappe.model.document import Document
from frappe.utils import flt

class DispatchLog(Document):
	def on_submit(self):
		self.validate_carton_status()
		self.calculate_totals()
		self.create_delivery_note()
		self.create_sales_invoice()
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

	def create_delivery_note(self):
		dn = frappe.new_doc("Delivery Note")
		dn.customer = self.customer
		dn.posting_date = self.dispatch_date
		dn.set_posting_time = 1
		dn.company = frappe.db.get_value("Sales Order", self.sales_order, "company")

		# Collect all items from all cartons
		for row in self.cartons:
			cbl = frappe.get_doc("Carton Box Log", row.carton_id)
			for item in (cbl.items or []):
				dn_item = {
					"item_code": item.item_code,
					"item_name": item.item_name,
					"qty": item.qty,
					"uom": item.uom,
					"stock_uom": item.uom,
					"conversion_factor": 1,
					"warehouse": cbl.warehouse,
				}
				dn.append("items", dn_item)

		dn.flags.ignore_permissions = True
		dn.insert(ignore_permissions=True)

		# Allow negative stock temporarily for this transaction
		frappe.flags.allow_negative_stock = True
		dn.submit()
		frappe.flags.allow_negative_stock = False
		self.db_set("delivery_note", dn.name)

	def create_sales_invoice(self):
		dn_name = frappe.db.get_value("Dispatch Log", self.name, "delivery_note")
		if not dn_name:
			return

		try:
			from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice
			si = make_sales_invoice(dn_name)
			si.flags.ignore_permissions = True
			si.insert()
			si.submit()
			self.db_set("sales_invoice", si.name)
		except Exception as e:
			frappe.log_error(f"Sales Invoice creation failed for {self.name}: {str(e)}")
			frappe.msgprint(f"Delivery Note {dn_name} was created but Sales Invoice could not be auto-created. Please create it manually.", indicator="orange", alert=True)

	def update_carton_box_logs(self):
		dn_name = frappe.db.get_value("Dispatch Log", self.name, "delivery_note")
		si_name = frappe.db.get_value("Dispatch Log", self.name, "sales_invoice")

		for row in self.cartons:
			frappe.db.set_value("Carton Box Log", row.carton_id, {
				"status": "Dispatched",
				"dispatch_log": self.name,
				"delivery_note": dn_name or "",
				"sales_invoice": si_name or "",
				"customer": self.customer,
				"dispatched_date": self.dispatch_date
			})

	def on_cancel(self):
		# Revert carton statuses
		for row in self.cartons:
			frappe.db.set_value("Carton Box Log", row.carton_id, {
				"status": "Available",
				"dispatch_log": "",
				"delivery_note": "",
				"sales_invoice": "",
				"customer": "",
				"dispatched_date": None
			})
		self.db_set('status', 'Cancelled')
