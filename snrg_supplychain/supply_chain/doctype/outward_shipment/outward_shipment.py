import frappe
from frappe.model.document import Document
from frappe.desk.search import validate_and_sanitize_search_inputs
from frappe.utils import flt


class OutwardShipment(Document):
	def validate(self):
		self.validate_duplicate_cartons()
		self.validate_carton_status()
		self.populate_so_items()
		self.populate_items_summary()
		self.calculate_totals()

		if self.sales_order and self.cartons:
			self.validate_items_against_sales_order()

	def before_save(self):
		pass

	def on_submit(self):
		if self.create_delivery_note:
			self.make_delivery_note()

		self.update_packed_cartons()
		self.db_set('status', 'Submitted')

	def get_selected_carton_ids(self):
		return [row.carton_id for row in (self.cartons or []) if row.carton_id]

	def validate_duplicate_cartons(self):
		seen = set()
		duplicates = []

		for carton_id in self.get_selected_carton_ids():
			if carton_id in seen:
				duplicates.append(carton_id)
			seen.add(carton_id)

		if duplicates:
			duplicate_list = ", ".join(sorted(set(duplicates)))
			frappe.throw(
				f"Duplicate cartons are not allowed in one shipment. Please remove: <b>{duplicate_list}</b>."
			)

	def get_reserved_cartons_in_other_drafts(self):
		carton_ids = self.get_selected_carton_ids()
		if not carton_ids:
			return {}

		placeholders = ", ".join(["%s"] * len(carton_ids))
		params = [self.name or ""] + carton_ids
		rows = frappe.db.sql(
			f"""
			SELECT c.carton_id, p.name AS outward_shipment
			FROM `tabOutward Shipment Carton` c
			INNER JOIN `tabOutward Shipment` p ON p.name = c.parent
			WHERE p.docstatus = 0
				AND p.name != %s
				AND c.carton_id IN ({placeholders})
			""",
			params,
			as_dict=True,
		)
		return {row.carton_id: row.outward_shipment for row in rows}

	def validate_carton_status(self):
		reserved_cartons = self.get_reserved_cartons_in_other_drafts()

		for row in (self.cartons or []):
			if not row.carton_id:
				continue

			if row.carton_id in reserved_cartons:
				frappe.throw(
					f"Carton <b>{row.carton_id}</b> is already reserved in draft shipment "
					f"<b>{reserved_cartons[row.carton_id]}</b>."
				)

			status = frappe.db.get_value("Packed Carton", row.carton_id, "status")
			if status != "Available":
				frappe.throw(f"Carton {row.carton_id} is already dispatched or not available.")

			carton = frappe.get_doc("Packed Carton", row.carton_id)
			if not carton.items:
				frappe.throw(f"Carton <b>{row.carton_id}</b> has no items and cannot be added to a shipment.")

	def populate_so_items(self):
		"""Populate the SO items table from the selected Sales Order."""
		if not self.meta.get_field("so_items"):
			return

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

	def get_aggregated_items(self):
		"""Aggregate items from all cartons into a dict keyed by item_code."""
		item_map = {}
		for row in (self.cartons or []):
			if not row.carton_id:
				continue
			cbl = frappe.get_doc("Packed Carton", row.carton_id)
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
		if not self.meta.get_field("dispatch_items"):
			return

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
			cbl = frappe.get_doc("Packed Carton", row.carton_id)
			total_gross_weight += flt(cbl.gross_weight_kg)
			for item in (cbl.items or []):
				total_pieces += flt(item.qty)

		self.total_cartons = total_cartons
		self.total_pieces = total_pieces
		self.total_gross_weight = total_gross_weight

	def get_so_item_map(self):
		"""Build a map of item_code -> SO Item row name for linking DN to SO."""
		so_item_map = {}
		# Try from so_items child table first (has so_detail stored)
		if self.meta.get_field("so_items"):
			for row in (self.so_items or []):
				if row.item_code and row.so_detail and row.item_code not in so_item_map:
					so_item_map[row.item_code] = row.so_detail

		# Fallback: fetch directly from SO
		if not so_item_map and self.sales_order:
			so = frappe.get_doc("Sales Order", self.sales_order)
			for item in so.items:
				if item.item_code not in so_item_map:
					so_item_map[item.item_code] = item.name

		return so_item_map

	def make_delivery_note(self):
		if not frappe.has_permission("Delivery Note", "create"):
			frappe.throw(
				"You do not have permission to create a Delivery Note. "
				"Either disable 'Create Delivery Note' or ask an administrator to grant access."
			)

		dn = frappe.new_doc("Delivery Note")
		dn.customer = self.customer
		dn.posting_date = self.dispatch_date
		dn.set_posting_time = 1
		dn.company = frappe.db.get_value("Sales Order", self.sales_order, "company")

		so_item_map = self.get_so_item_map()

		for row in self.cartons:
			cbl = frappe.get_doc("Packed Carton", row.carton_id)
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

		dn.insert()
		# Leave DN in Draft state — user can review and submit manually
		self.db_set("delivery_note", dn.name)
		frappe.msgprint(
			f"Delivery Note <a href='/app/delivery-note/{dn.name}'><b>{dn.name}</b></a> created in Draft.",
			indicator="green",
			alert=True
		)

	def update_packed_cartons(self):
		dn_name = frappe.db.get_value("Outward Shipment", self.name, "delivery_note") or ""

		for row in self.cartons:
			frappe.db.set_value("Packed Carton", row.carton_id, {
				"status": "Dispatched",
				"outward_shipment": self.name,
				"delivery_note": dn_name,
				"customer": self.customer,
				"dispatched_date": self.dispatch_date
			})

	def on_cancel(self):
		for row in self.cartons:
			frappe.db.set_value("Packed Carton", row.carton_id, {
				"status": "Available",
				"outward_shipment": "",
				"delivery_note": "",
				"customer": "",
				"dispatched_date": None
			})
		self.db_set('status', 'Cancelled')


@frappe.whitelist()
@validate_and_sanitize_search_inputs
def sales_order_query(doctype, txt, searchfield, start, page_len, filters):
	search_text = f"%{txt}%"

	return frappe.db.sql(
		"""
		SELECT
			name,
			customer_name,
			transaction_date,
			status
		FROM `tabSales Order`
		WHERE docstatus != 2
			AND status NOT IN ('Closed', 'Completed')
			AND (
				name LIKE %(txt)s
				OR customer_name LIKE %(txt)s
			)
		ORDER BY transaction_date DESC, modified DESC, name DESC
		LIMIT %(start)s, %(page_len)s
		""",
		{
			"txt": search_text,
			"start": start,
			"page_len": page_len,
		},
	)


@frappe.whitelist()
@validate_and_sanitize_search_inputs
def available_carton_query(doctype, txt, searchfield, start, page_len, filters):
	filters = filters or {}
	current_shipment = filters.get("outward_shipment") or ""
	search_text = f"%{txt}%"

	return frappe.db.sql(
		"""
		SELECT
			p.name,
			p.box_type,
			p.packed_date,
			p.warehouse
		FROM `tabPacked Carton` p
		WHERE p.status = 'Available'
			AND (
				p.name LIKE %(txt)s
				OR COALESCE(p.box_type, '') LIKE %(txt)s
				OR COALESCE(p.warehouse, '') LIKE %(txt)s
			)
			AND NOT EXISTS (
				SELECT 1
				FROM `tabOutward Shipment Carton` c
				INNER JOIN `tabOutward Shipment` s ON s.name = c.parent
				WHERE c.carton_id = p.name
					AND s.docstatus = 0
					AND s.name != %(current_shipment)s
			)
		ORDER BY p.packed_date DESC, p.modified DESC, p.name DESC
		LIMIT %(start)s, %(page_len)s
		""",
		{
			"txt": search_text,
			"current_shipment": current_shipment,
			"start": start,
			"page_len": page_len,
		},
	)
