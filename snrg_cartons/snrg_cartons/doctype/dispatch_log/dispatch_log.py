import frappe
from frappe.model.document import Document

class DispatchLog(Document):
	def on_submit(self):
		self.validate_carton_status()
		self.update_totals()
		self.create_delivery_note()
		self.create_sales_invoice()
		self.update_carton_box_logs()
		self.db_set('status', 'Submitted')

	def validate_carton_status(self):
		for row in self.cartons:
			status = frappe.db.get_value("Carton Box Log", row.carton_id, "status")
			if status != "Available":
				frappe.throw(f"Carton {row.carton_id} is already dispatched or not available.")
	
	def update_totals(self):
		total_cartons = len(self.cartons)
		total_pieces = 0
		total_gross_weight = 0
		
		for row in self.cartons:
			cbl = frappe.get_doc("Carton Box Log", row.carton_id)
			total_gross_weight += cbl.gross_weight_kg
			for item in cbl.items:
				total_pieces += item.qty
		
		self.db_set('total_cartons', total_cartons)
		self.db_set('total_pieces', total_pieces)
		self.db_set('total_gross_weight', total_gross_weight)
		
	def create_delivery_note(self):
		dn = frappe.new_doc("Delivery Note")
		dn.customer = self.customer
		dn.posting_date = self.dispatch_date
		
		# Adding sales order reference
		dn.append("items", {
			# Assuming items are mapped correctly, in full implementation you need to make sure to fetch missing required fields of Delivery Note Item as needed.
		})
		
		for row in self.cartons:
			cbl = frappe.get_doc("Carton Box Log", row.carton_id)
			for item in cbl.items:
				dn.append("items", {
					"item_code": item.item_code,
					"qty": item.qty,
					"uom": item.uom,
					"against_sales_order": self.sales_order,
					"custom_carton_id": row.carton_id
				})
				
		dn.insert()
		dn.submit()
		self.db_set("delivery_note", dn.name)

	def create_sales_invoice(self):
		if not self.delivery_note:
			return
		
		from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice
		si = make_sales_invoice(self.delivery_note)
		si.insert()
		si.submit()
		self.db_set("sales_invoice", si.name)
		
	def update_carton_box_logs(self):
		for row in self.cartons:
			cbl = frappe.get_doc("Carton Box Log", row.carton_id)
			cbl.status = "Dispatched"
			cbl.dispatch_log = self.name
			cbl.delivery_note = self.delivery_note
			cbl.sales_invoice = self.sales_invoice
			cbl.customer = self.customer
			cbl.dispatched_date = self.dispatch_date
			cbl.save()
			
	def on_cancel(self):
		self.db_set('status', 'Cancelled')
