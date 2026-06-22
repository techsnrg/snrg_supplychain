import json

import frappe
from frappe.model.document import Document
from frappe.utils import flt, today


WEIGHT_UOM_TO_KG = {
	"KG": 1,
	"KILOGRAM": 1,
	"KILOGRAMS": 1,
	"G": 0.001,
	"GM": 0.001,
	"GRAM": 0.001,
	"GRAMS": 0.001,
	"MG": 0.000001,
	"MILLIGRAM": 0.000001,
	"MILLIGRAMS": 0.000001,
}


def convert_weight_to_kg(weight, weight_uom):
	weight = flt(weight)
	if not weight:
		return 0

	uom_key = (weight_uom or "kg").strip().upper()
	factor = WEIGHT_UOM_TO_KG.get(uom_key)
	if factor is None:
		frappe.throw(
			f"Unsupported Weight UOM <b>{weight_uom}</b>. "
			"Please use Kg, Gram, or Milligram on the Item master."
		)

	return weight * factor


class PackedCarton(Document):
	def before_save(self):
		self.set_box_type_details()
		self.set_item_details()
		self.calculate_weights()

		if not self.status:
			self.status = "Available"

	def set_box_type_details(self):
		if self.box_type:
			box_doc = frappe.get_cached_doc("Carton Type", self.box_type)
			self.dimensions = f"{box_doc.length_in} × {box_doc.width_in} × {box_doc.height_in} in"
			self.empty_weight_g = flt(box_doc.empty_weight_g)

	def set_item_details(self):
		for row in (self.items or []):
			if row.item_code:
				item_doc = frappe.get_cached_doc("Item", row.item_code)
				row.item_name = item_doc.item_name
				if not row.uom:
					row.uom = item_doc.stock_uom
				if not row.item_weight_kg:
					row.item_weight_kg = convert_weight_to_kg(
						getattr(item_doc, "weight_per_unit", 0),
						getattr(item_doc, "weight_uom", None),
					)

				if not flt(row.item_weight_kg):
					frappe.throw(
						f"Weight per unit is missing for Item <b>{row.item_code}</b>. "
						"Please update the Item master before packing."
					)

	def calculate_weights(self):
		net = 0.0
		for row in (self.items or []):
			net += flt(row.qty) * flt(row.item_weight_kg)

		self.net_weight_kg = net
		self.gross_weight_kg = round(net + flt(self.empty_weight_g) / 1000, 3)


def _serialize_touch_carton(doc):
	return {
		"name": doc.name,
		"box_type": doc.box_type,
		"packed_date": doc.packed_date,
		"warehouse": doc.warehouse,
		"packed_by": doc.packed_by,
		"status": doc.status,
		"dimensions": doc.dimensions,
		"empty_weight_g": flt(doc.empty_weight_g),
		"net_weight_kg": flt(doc.net_weight_kg),
		"gross_weight_kg": flt(doc.gross_weight_kg),
		"items": [
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"qty": flt(row.qty),
				"uom": row.uom,
				"item_weight_kg": flt(row.item_weight_kg),
			}
			for row in (doc.items or [])
		],
	}


@frappe.whitelist()
def get_touch_item(item_code):
	item_doc = frappe.get_cached_doc("Item", item_code)
	item_weight_kg = convert_weight_to_kg(
		getattr(item_doc, "weight_per_unit", 0),
		getattr(item_doc, "weight_uom", None),
	)
	return {
		"item_code": item_doc.name,
		"item_name": item_doc.item_name,
		"uom": item_doc.stock_uom,
		"item_weight_kg": item_weight_kg,
	}


@frappe.whitelist()
def get_touch_carton(name=None):
	if name:
		doc = frappe.get_doc("Packed Carton", name)
		return _serialize_touch_carton(doc)

	default_warehouse = frappe.defaults.get_user_default("Warehouse") or ""
	return {
		"name": "",
		"box_type": "",
		"packed_date": today(),
		"warehouse": default_warehouse,
		"packed_by": "",
		"status": "Available",
		"dimensions": "",
		"empty_weight_g": 0,
		"net_weight_kg": 0,
		"gross_weight_kg": 0,
		"items": [],
	}


@frappe.whitelist()
def list_touch_cartons(search_text=None, limit=12):
	filters = {}
	if search_text:
		filters["name"] = ["like", f"%{search_text}%"]

	cartons = frappe.get_list(
		"Packed Carton",
		filters=filters,
		fields=["name", "box_type", "packed_date", "warehouse", "status", "gross_weight_kg", "modified"],
		order_by="modified desc",
		limit_page_length=max(int(limit or 12), 1),
	)

	return cartons


@frappe.whitelist()
def save_touch_carton(payload):
	if isinstance(payload, str):
		payload = json.loads(payload)

	name = payload.get("name")
	if name:
		doc = frappe.get_doc("Packed Carton", name)
	else:
		doc = frappe.new_doc("Packed Carton")

	doc.box_type = payload.get("box_type")
	doc.packed_date = payload.get("packed_date")
	doc.warehouse = payload.get("warehouse")
	doc.packed_by = payload.get("packed_by")
	doc.items = []

	for item in payload.get("items") or []:
		doc.append("items", {
			"item_code": item.get("item_code"),
			"item_name": item.get("item_name"),
			"qty": flt(item.get("qty")),
			"uom": item.get("uom"),
			"item_weight_kg": flt(item.get("item_weight_kg")),
		})

	doc.save()
	return _serialize_touch_carton(doc)
