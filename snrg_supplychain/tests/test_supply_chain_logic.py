from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from frappe.exceptions import ValidationError

from snrg_supplychain.supply_chain.doctype.freight_quotation import freight_quotation
from snrg_supplychain.supply_chain.doctype.outward_shipment.outward_shipment import OutwardShipment
from snrg_supplychain.supply_chain.doctype.outward_shipment import outward_shipment as outward_shipment_module
from snrg_supplychain.supply_chain.doctype.packed_carton.packed_carton import (
	PackedCarton,
	convert_weight_to_kg,
)
from snrg_supplychain.supply_chain.doctype.transporter_serviceability.transporter_serviceability import (
	TransporterServiceability,
	process_csv_upload,
)
from snrg_supplychain.supply_chain.utils import _generate_svg_barcode, get_print_branding


class SupplyChainLogicTests(TestCase):
	def test_barcode_fallback_returns_data_uri(self):
		result = _generate_svg_barcode("CTN-00001")
		self.assertTrue(result.startswith("data:image/svg+xml;base64,"))

	def test_get_print_branding_uses_default_company(self):
		company = SimpleNamespace(company_name="SNRG Electricals India Pvt. Ltd.", company_logo="/files/logo.png")
		with patch("snrg_supplychain.supply_chain.utils.frappe.defaults.get_global_default", return_value="SNRG"), \
			patch("snrg_supplychain.supply_chain.utils.frappe.get_cached_doc", return_value=company), \
			patch("snrg_supplychain.supply_chain.utils.frappe.get_hooks", return_value=["SNRG Electricals"]):
			branding = get_print_branding()

		self.assertEqual(branding["company_name"], company.company_name)
		self.assertEqual(branding["logo"], company.company_logo)

	def test_packed_carton_calculates_weights(self):
		carton = SimpleNamespace(
			items=[
				SimpleNamespace(qty=2, item_weight_kg=1.25),
				SimpleNamespace(qty=3, item_weight_kg=0.5),
			],
			empty_weight_g=250,
			net_weight_kg=0,
			gross_weight_kg=0,
		)

		PackedCarton.calculate_weights(carton)

		self.assertEqual(carton.net_weight_kg, 4.0)
		self.assertEqual(carton.gross_weight_kg, 4.25)

	def test_convert_weight_to_kg_from_grams(self):
		self.assertEqual(convert_weight_to_kg(20, "Gram"), 0.02)

	def test_packed_carton_requires_item_weight(self):
		carton = SimpleNamespace(
			items=[SimpleNamespace(item_code="ITEM-001", item_name="", uom="", item_weight_kg=0)],
		)
		item_doc = SimpleNamespace(item_name="Switch", stock_uom="Nos", weight_per_unit=0, weight_uom="Gram")

		with patch("snrg_supplychain.supply_chain.doctype.packed_carton.packed_carton.frappe.get_cached_doc", return_value=item_doc):
			with self.assertRaises(ValidationError):
				PackedCarton.set_item_details(carton)

	def test_validate_items_against_sales_order_blocks_excess_qty(self):
		shipment = SimpleNamespace(
			sales_order="SO-0001",
			get_aggregated_items=lambda: {
				"ITEM-001": {
					"item_code": "ITEM-001",
					"total_qty": 12,
				}
			},
		)
		so_doc = SimpleNamespace(items=[SimpleNamespace(item_code="ITEM-001", qty=10)])

		with patch("snrg_supplychain.supply_chain.doctype.outward_shipment.outward_shipment.frappe.get_doc", return_value=so_doc):
			with self.assertRaises(ValidationError):
				OutwardShipment.validate_items_against_sales_order(shipment)

	def test_duplicate_cartons_are_blocked(self):
		shipment = SimpleNamespace(
			get_selected_carton_ids=lambda: ["CTN-0001", "CTN-0001", "CTN-0002"]
		)

		with self.assertRaises(ValidationError):
			OutwardShipment.validate_duplicate_cartons(shipment)

	def test_reserved_cartons_in_other_drafts_are_blocked(self):
		shipment = SimpleNamespace(
			cartons=[SimpleNamespace(carton_id="CTN-0001")],
			get_reserved_cartons_in_other_drafts=lambda: {"CTN-0001": "DL-0001"},
		)

		with self.assertRaises(ValidationError):
			OutwardShipment.validate_carton_status(shipment)

	def test_make_delivery_note_requires_create_permission(self):
		shipment = SimpleNamespace(
			customer="Customer A",
			dispatch_date="2026-06-21",
			sales_order="SO-0001",
			cartons=[],
			meta=SimpleNamespace(get_field=lambda fieldname: False),
		)

		with patch("snrg_supplychain.supply_chain.doctype.outward_shipment.outward_shipment.frappe.has_permission", return_value=False):
			with self.assertRaises(ValidationError):
				OutwardShipment.make_delivery_note(shipment)

	def test_calc_basic_freight_uses_minimum_billable_weight(self):
		rate_card = SimpleNamespace(
			rate_slabs=[
				SimpleNamespace(
					freight_zone="North",
					from_weight_kg=0,
					to_weight_kg=10,
					minimum_billable_weight_kg=5,
					rate_per_kg=12,
				)
			]
		)

		amount, remark = freight_quotation._calc_basic_freight(rate_card, "North", 2)

		self.assertEqual(amount, 60)
		self.assertEqual(remark, "")

	def test_process_csv_upload_loads_rows(self):
		doc = SimpleNamespace(pin_codes=[], total_pin_codes=0, append=lambda fieldname, row: doc.pin_codes.append(row), save=MagicMock())
		file_doc = SimpleNamespace(file_url="/private/files/pins.csv")
		csv_body = "PIN CODE,ZONE,STATE,ODA/SERVICEABILITY,ODA CATEGORY\n201301,NCR,Uttar Pradesh,SERVICEABLE,S\n"

		with patch("snrg_supplychain.supply_chain.doctype.transporter_serviceability.transporter_serviceability.frappe.get_doc", side_effect=[doc, file_doc]), \
			patch("snrg_supplychain.supply_chain.doctype.transporter_serviceability.transporter_serviceability.frappe.get_site_path", return_value="/tmp/pins.csv"), \
			patch("builtins.open", new=MagicMock()) as mock_open:
			mock_open.return_value.__enter__.return_value.read.return_value = csv_body
			result = process_csv_upload("TSP-0001", "/private/files/pins.csv")

		self.assertEqual(result["loaded"], 1)
		self.assertEqual(doc.total_pin_codes, 1)
		self.assertEqual(doc.pin_codes[0]["pin_code"], "201301")

	def test_transporter_serviceability_validate_dates(self):
		doc = SimpleNamespace(valid_from="2026-06-22", valid_to="2026-06-21")
		with self.assertRaises(ValidationError):
			TransporterServiceability.validate(doc)

	def test_available_carton_query_orders_newest_first(self):
		with patch.object(outward_shipment_module.frappe.db, "sql", return_value=[]) as sql_mock:
			outward_shipment_module.available_carton_query("Packed Carton", "", "name", 0, 20, {"outward_shipment": "DL-0001"})

		self.assertIn("ORDER BY p.packed_date DESC, p.modified DESC, p.name DESC", sql_mock.call_args[0][0])
