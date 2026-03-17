import frappe
from frappe.model.document import Document
from frappe.utils import flt

class DispatchLog(Document):
	def before_save(self):
		self.populate_items_summary()

	def on_submit(self):
		self.validate_carton_status()
		self.validate_items_against_sales_order()
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

	def populate_items_summary(self):
		"""Aggregate items from all cartons into the dispatch_items child table."""
		self.dispatch_items = []
		item_map = {}

		for row in (self.cartons or []):
			if not row.carton_id:
				continue
			cbl = frappe.get_doc("Carton Box Log", row.carton_id)
			for item in (cbl.items or []):
				key = item.item_code
				if key not in item_map:
					item_map[key] = {
						"item_code": item.item_code,
						"item_name": item.item_name,
						"total_qty": 0,
						"uom": item.uom,
						"cartons": []
					}
				item_map[key]["total_qty"] += flt(item.qty)
				if row.carton_id not in item_map[key]["cartons"]:
					item_map[key]["cartons"].append(row.carton_id)

		for item in item_map.values():
			self.append("dispatch_items", {
				"item_code": item["item_code"],
				"item_name": item["item_name"],
				"total_qty": item["total_qty"],
				"uom": item["uom"],
				"from_cartons": ", ".join(item["cartons"])
			})

	def validate_items_against_sales_order(self):
		"""Check that all dispatched items exist in the Sales Order."""
		if not self.sales_order:
			return

		so = frappe.get_doc("Sales Order", self.sales_order)
		so_items = {}
		for item in so.items:
			key = item.item_code
			if key not in so_items:
				so_items[key] = 0
			so_items[key] += flt(item.qty)

		warnings = []
		for row in (self.dispatch_items or []):
			if row.item_code not in so_items:
				warnings.append(f"Item <b>{row.item_code}</b> is not in Sales Order {self.sales_order}")
			elif flt(row.total_qty) > so_items[row.item_code]:
				warnings.append(
					f"Item <b>{row.item_code}</b>: dispatching {row.total_qty} but SO has only {so_items[row.item_code]}"
				)

		if warnings:
			frappe.msgprint(
				"<br>".join(warnings),
				title="Sales Order Mismatch",
				indicator="orange"
			)

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
