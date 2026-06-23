from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from snrg_supplychain.supply_chain.utils import (
	_get_item_barcode,
	_render_product_box_sticker,
	get_product_box_sticker_context,
)


class ProductBoxStickerTests(TestCase):
	def test_get_item_barcode_prefers_item_barcode_child_row(self):
		item = SimpleNamespace(
			name="ITEM-001",
			barcode="ITEM-FALLBACK",
			barcodes=[SimpleNamespace(barcode="8900000000012")],
		)

		self.assertEqual(_get_item_barcode(item), "8900000000012")

	def test_get_item_barcode_falls_back_to_item_code(self):
		item = SimpleNamespace(name="ITEM-001", barcode="", barcodes=[])

		self.assertEqual(_get_item_barcode(item), "ITEM-001")

	def test_product_box_sticker_context_uses_item_master_values(self):
		item = SimpleNamespace(
			name="ITEM-001",
			item_name="Switch",
			item_group="Electricals",
			stock_uom="Nos",
			weight_per_unit=250,
			weight_uom="Gram",
			barcode="",
			barcodes=[],
		)

		with patch("snrg_supplychain.supply_chain.utils.frappe.get_cached_doc", return_value=item), \
			patch("snrg_supplychain.supply_chain.utils.get_code128_barcode", return_value="data:image/svg+xml;base64,abc"), \
			patch("snrg_supplychain.supply_chain.utils.get_print_branding", return_value={"company_name": "SNRG", "logo": "/files/logo.png"}), \
			patch("snrg_supplychain.supply_chain.utils.nowdate", return_value="2026-06-23"), \
			patch("snrg_supplychain.supply_chain.utils.formatdate", return_value="23-06-2026"):
			context = get_product_box_sticker_context("ITEM-001", 12)

		self.assertEqual(context["item_code"], "ITEM-001")
		self.assertEqual(context["box_qty"], 12)
		self.assertEqual(context["barcode_text"], "ITEM-001")
		self.assertEqual(context["branding"]["company_name"], "SNRG")

	def test_render_product_box_sticker_escapes_values_and_honors_copies(self):
		html = _render_product_box_sticker({
			"item_code": "ITEM<001>",
			"item_name": "Switch & Socket",
			"item_group": "Electricals",
			"stock_uom": "Nos",
			"box_qty": 2,
			"weight_per_unit": 0,
			"weight_uom": "",
			"barcode_text": "ITEM<001>",
			"barcode_uri": "",
			"branding": {"company_name": "SNRG", "logo": ""},
			"print_date": "23-06-2026",
		}, copies=2)

		self.assertEqual(html.count('class="sticker-container"'), 2)
		self.assertIn("ITEM&lt;001&gt;", html)
		self.assertIn("Switch &amp; Socket", html)
