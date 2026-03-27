import frappe
from frappe.model.document import Document
from frappe.utils import flt

class DispatchLog(Document):
	def before_save(self):
		self.populate_so_items()
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

	def populate_so_items(self):
		"""Populate the SO items table from the selected Sales Order."""
		try:
			self.so_items = []
			if self.sales_order:
				so = frappe.get_doc("Sales Order", self.sales_order)
				for item in so.items:
					self.append("so_items", {
						"item_code": item.item_code,
						"item_name": item.item_name,
						"ordered_qty": item.qty,
						"uom": item.uom,
						"so_detail": item.name  # SO Item row name for DN linking
					})
		except AttributeError:
			pass

	def get_aggregated_items(self):
		"""Aggregate items from all cartons into a dict keyed by item_code."""
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
		return item_map

	def populate_items_summary(self):
		"""Populate the dispatch_items child table if it exists (post-migration)."""
		try:
			self.dispatch_items = []
			item_map = self.get_aggregated_items()
			for item in item_map.values():
				self.append("dispatch_items", {
					"item_code": item["item_code"],
					"item_name": item["item_name"],
					"total_qty": item["total_qty"],
					"uom": item["uom"],
					"from_cartons": ", ".join(item["cartons"])
				})
		except AttributeError:
			pass

	def validate_items_against_sales_order(self):
		"""
		Block submission if dispatched items are not in the Sales Order
		or if dispatched quantity exceeds the ordered quantity.
		Partial dispatches (qty < SO qty) are allowed.
		"""
		if not self.sales_order:
			return

		so = frappe.get_doc("Sales Order", self.sales_order)
		so_items = {}
		for item in so.items:
			key = item.item_code
			so_items[key] = so_items.get(key, 0) + flt(item.qty)

		item_map = self.get_aggregated_items()

		errors = []
		for key, item in item_map.items():
			if key not in so_items:
				errors.append(
					f"Item <b>{key}</b> is not part of Sales Order <b>{self.sales_order}</b>."
				)
			elif flt(item["total_qty"]) > so_items[key]:
				errors.append(
					f"Item <b>{key}</b>: dispatching <b>{item['total_qty']}</b> "
					f"but Sales Order has only <b>{so_items[key]}</b>."
				)

		if errors:
			frappe.throw(
				"Cannot submit — quantities do not match the Sales Order:<br><br>"
				+ "<br>".join(f"• {e}" for e in errors),
				title="Sales Order Mismatch"
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

	def get_so_item_map(self):
		"""Build a map of item_code -> SO Item row name for linking DN to SO."""
		so_item_map = {}
		# Try from so_items child table first (has so_detail stored)
		try:
			for row in (self.so_items or []):
				if row.item_code and row.so_detail:
					if row.item_code not in so_item_map:
						so_item_map[row.item_code] = row.so_detail
		except AttributeError:
			pass

		# Fallback: fetch directly from SO
		if not so_item_map and self.sales_order:
			so = frappe.get_doc("Sales Order", self.sales_order)
			for item in so.items:
				if item.item_code not in so_item_map:
					so_item_map[item.item_code] = item.name

		return so_item_map

	def make_delivery_note(self):
		dn = frappe.new_doc("Delivery Note")
		dn.customer = self.customer
		dn.posting_date = self.dispatch_date
		dn.set_posting_time = 1
		dn.company = frappe.db.get_value("Sales Order", self.sales_order, "company")

		so_item_map = self.get_so_item_map()

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
				# Link to Sales Order Item for fulfillment tracking
				if item.item_code in so_item_map:
					dn_item["against_sales_order"] = self.sales_order
					dn_item["so_detail"] = so_item_map[item.item_code]

				dn.append("items", dn_item)

		dn.flags.ignore_permissions = True
		dn.insert(ignore_permissions=True)
		# Leave DN in Draft state — user can review and submit manually
		self.db_set("delivery_note", dn.name)
		frappe.msgprint(
			f"Delivery Note <a href='/app/delivery-note/{dn.name}'><b>{dn.name}</b></a> created in Draft.",
			indicator="green",
			alert=True
		)

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
