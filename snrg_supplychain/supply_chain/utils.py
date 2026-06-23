import base64
import html
import io

import frappe
from frappe.exceptions import DoesNotExistError
from frappe.utils import cint, flt, formatdate, nowdate


def _get_default_company():
	default_company = frappe.defaults.get_global_default("company")
	if not default_company:
		return None

	try:
		return frappe.get_cached_doc("Company", default_company)
	except DoesNotExistError:
		frappe.log_error(
			title="Missing Default Company",
			message=f"Default company '{default_company}' was not found while resolving print branding.",
		)
		return None


@frappe.whitelist()
def get_print_branding():
	"""Return reusable branding values for print formats."""
	app_publishers = frappe.get_hooks("app_publisher")
	branding = {
		"company_name": app_publishers[0] if app_publishers else "",
		"logo": "",
	}

	company = _get_default_company()
	if not company:
		return branding

	branding["company_name"] = getattr(company, "company_name", None) or company.name
	branding["logo"] = (
		getattr(company, "company_logo", None)
		or getattr(company, "company_logo_for_print", None)
		or ""
	)
	return branding


@frappe.whitelist()
def get_code128_barcode(text):
	"""Generate a Code 128 barcode as a base64-encoded PNG data URI.
	This can be called from Jinja templates in print formats."""
	try:
		import barcode
		from barcode.writer import ImageWriter
		
		code128 = barcode.get_barcode_class('code128')
		buffer = io.BytesIO()
		writer = ImageWriter()
		writer.set_options({
			'module_height': 6,
			'module_width': 0.25,
			'quiet_zone': 2,
			'font_size': 0,
			'text_distance': 0,
			'write_text': False
		})
		bc = code128(str(text), writer=writer)
		bc.write(buffer)
		buffer.seek(0)
		img_base64 = base64.b64encode(buffer.read()).decode()
		return f"data:image/png;base64,{img_base64}"
	except ImportError:
		# python-barcode not installed, generate a simple SVG barcode
		return _generate_svg_barcode(text)
	except Exception:
		frappe.log_error(
			title="Barcode Generation Failed",
			message=frappe.get_traceback(),
		)
		return ""


def _escape(value):
	return html.escape(str(value or ""), quote=True)


def _get_item_barcode(item_doc):
	for row in getattr(item_doc, "barcodes", None) or []:
		barcode = getattr(row, "barcode", None)
		if barcode:
			return barcode

	return getattr(item_doc, "barcode", None) or item_doc.name


def get_product_box_sticker_context(item_code, box_qty=1):
	"""Return Item-master values needed for a product box sticker."""
	item_doc = frappe.get_cached_doc("Item", item_code)
	if hasattr(item_doc, "check_permission"):
		item_doc.check_permission("read")

	box_qty = flt(box_qty) or 1
	barcode_text = _get_item_barcode(item_doc)

	return {
		"item_code": item_doc.name,
		"item_name": getattr(item_doc, "item_name", None) or item_doc.name,
		"item_group": getattr(item_doc, "item_group", None) or "",
		"stock_uom": getattr(item_doc, "stock_uom", None) or "",
		"box_qty": box_qty,
		"weight_per_unit": flt(getattr(item_doc, "weight_per_unit", 0)),
		"weight_uom": getattr(item_doc, "weight_uom", None) or "",
		"barcode_text": barcode_text,
		"barcode_uri": get_code128_barcode(barcode_text),
		"branding": get_print_branding(),
		"print_date": formatdate(nowdate(), "dd-MM-yyyy"),
	}


def _render_product_box_sticker(context, copies=1):
	copies = max(min(cint(copies or 1), 100), 1)
	branding = context.get("branding") or {}
	logo = _escape(branding.get("logo"))
	company_name = _escape(branding.get("company_name") or "SNRG Supply Chain")
	weight = ""
	if context.get("weight_per_unit"):
		weight = f'{context.get("weight_per_unit"):g} {_escape(context.get("weight_uom"))}'.strip()

	logo_html = ""
	if logo:
		logo_html = f'<img class="logo" src="{logo}" alt="" onerror="this.style.display=\'none\'">'

	barcode_html = ""
	if context.get("barcode_uri"):
		barcode_html = (
			f'<img src="{_escape(context.get("barcode_uri"))}" '
			f'alt="{_escape(context.get("barcode_text"))}">'
		)

	sticker = f"""
		<div class="sticker-container">
			<div class="sticker-header">
				{logo_html}
				<span>{company_name}</span>
			</div>
			<div class="sticker-type">PRODUCT BOX</div>
			<div class="item-code">{_escape(context.get("item_code"))}</div>
			<div class="barcode-section">{barcode_html}</div>
			<div class="barcode-text">{_escape(context.get("barcode_text"))}</div>
			<div class="item-name">{_escape(context.get("item_name"))}</div>
			<div class="info-grid">
				<div class="info-cell">
					<div class="info-label">Box Qty</div>
					<div class="info-value qty-value">{context.get("box_qty"):g} {_escape(context.get("stock_uom"))}</div>
				</div>
				<div class="info-cell">
					<div class="info-label">Item Group</div>
					<div class="info-value">{_escape(context.get("item_group"))}</div>
				</div>
			</div>
			<div class="bottom-grid">
				<div class="bottom-cell">
					<span class="bl">Unit Wt. </span><span class="bv">{weight or "-"}</span>
				</div>
				<div class="bottom-cell">
					<span class="bl">Printed </span><span class="bv">{_escape(context.get("print_date"))}</span>
				</div>
			</div>
		</div>
	"""

	return f"""
<!doctype html>
<html>
<head>
	<meta charset="utf-8">
	<title>Product Box Sticker - {_escape(context.get("item_code"))}</title>
	<style>
		@page {{
			size: 4in 3in;
			margin: 0;
		}}

		html, body {{
			margin: 0;
			padding: 0;
			background: #fff;
			color: #1a1a2e;
			font-family: Arial, Helvetica, sans-serif;
		}}

		.sticker-container {{
			width: 384px;
			height: 288px;
			padding: 3px 5px;
			box-sizing: border-box;
			border: 1.5px solid #1a1a2e;
			overflow: hidden;
			page-break-after: always;
		}}

		.sticker-container:last-child {{
			page-break-after: auto;
		}}

		.sticker-header {{
			background: #1a1a2e;
			color: #fff;
			text-align: center;
			padding: 2px 6px;
			margin: -3px -5px 3px -5px;
			font-size: 8pt;
			font-weight: 800;
			letter-spacing: 0.6px;
			display: flex;
			align-items: center;
			justify-content: center;
			gap: 5px;
		}}

		.sticker-header img.logo {{
			height: 16px;
			width: auto;
		}}

		.sticker-type {{
			text-align: center;
			font-size: 6pt;
			font-weight: 800;
			letter-spacing: 1px;
			color: #555;
		}}

		.item-code {{
			text-align: center;
			font-size: 26pt;
			font-weight: 900;
			letter-spacing: 1.2px;
			line-height: 1.05;
			margin-top: 1px;
			overflow-wrap: anywhere;
		}}

		.barcode-section {{
			text-align: center;
			margin: 2px 0 0;
			height: 30px;
		}}

		.barcode-section img {{
			height: 28px;
			width: auto;
			max-width: 84%;
		}}

		.barcode-text {{
			text-align: center;
			font-size: 6.5pt;
			font-weight: 700;
			color: #444;
			line-height: 1.1;
		}}

		.item-name {{
			border: 1.5px solid #1a1a2e;
			margin: 3px 0;
			padding: 2px 4px;
			text-align: center;
			font-size: 10pt;
			font-weight: 800;
			line-height: 1.15;
			min-height: 24px;
			overflow-wrap: anywhere;
		}}

		.info-grid, .bottom-grid {{
			display: table;
			width: 100%;
			border-collapse: collapse;
		}}

		.info-cell, .bottom-cell {{
			display: table-cell;
			border: 1px solid #1a1a2e;
			padding: 2px 3px;
			vertical-align: middle;
			width: 50%;
		}}

		.info-label, .bl {{
			font-weight: 700;
			font-size: 5.5pt;
			color: #555;
			text-transform: uppercase;
		}}

		.info-value, .bv {{
			font-weight: 800;
			font-size: 7.5pt;
			line-height: 1.1;
		}}

		.qty-value {{
			font-size: 14pt;
			line-height: 1;
		}}

		.bottom-grid {{
			margin-top: 3px;
		}}

		@media print {{
			.sticker-container {{
				border: none;
			}}
		}}
	</style>
</head>
<body>
	{sticker * copies}
</body>
</html>
"""


@frappe.whitelist()
def get_product_box_sticker_html(item_code, box_qty=1, copies=1):
	"""Render browser-native HTML for printing Product Box stickers from Item."""
	context = get_product_box_sticker_context(item_code, box_qty)
	return _render_product_box_sticker(context, copies)


def _generate_svg_barcode(text):
	"""Fallback: generate Code 128 barcode as inline SVG data URI."""
	# Code 128B encoding
	PATTERNS = [
		"11011001100", "11001101100", "11001100110", "10010011000", "10010001100",
		"10001001100", "10011001000", "10011000100", "10001100100", "11001001000",
		"11001000100", "11000100100", "10110011100", "10011011100", "10011001110",
		"10111001100", "10011101100", "10011100110", "11001110010", "11001011100",
		"11001001110", "11011100100", "11001110100", "11101101110", "11101001100",
		"11100101100", "11100100110", "11101100100", "11100110100", "11100110010",
		"11011011000", "11011000110", "11000110110", "10100011000", "10001011000",
		"10001000110", "10110001000", "10001101000", "10001100010", "11010001000",
		"11000101000", "11000100010", "10110111000", "10110001110", "10001101110",
		"10111011000", "10111000110", "10001110110", "11101110110", "11010001110",
		"11000101110", "11011101000", "11011100010", "11011101110", "11101011000",
		"11101000110", "11100010110", "11101101000", "11101100010", "11100011010",
		"11101111010", "11001000010", "11110001010", "10100110000", "10100001100",
		"10010110000", "10010000110", "10000101100", "10000100110", "10110010000",
		"10110000100", "10011010000", "10011000010", "10000110100", "10000110010",
		"11000010010", "11001010000", "11110111010", "11000010100", "10001111010",
		"10100111100", "10010111100", "10010011110", "10111100100", "10011110100",
		"10011110010", "11110100100", "11110010100", "11110010010", "11011011110",
		"11011110110", "11110110110", "10101111000", "10100011110", "10001011110",
		"10111101000", "10111100010", "11110101000", "11110100010", "10111011110",
		"10111101110", "11101011110", "11110101110", "11010000100", "11010010000",
		"11010011100", "1100011101011",
	]
	
	START_B = 104
	STOP = 106
	
	codes = [START_B]
	checksum = START_B
	for i, ch in enumerate(str(text)):
		val = ord(ch) - 32
		codes.append(val)
		checksum += val * (i + 1)
	codes.append(checksum % 103)
	codes.append(STOP)
	
	# Build bar pattern
	bars = ""
	for c in codes:
		bars += PATTERNS[c]
	
	# Generate SVG
	bar_width = 1.5
	height = 25
	width = len(bars) * bar_width + 20
	
	svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
	svg += f'<rect width="{width}" height="{height}" fill="white"/>'
	x = 10
	for bit in bars:
		if bit == '1':
			svg += f'<rect x="{x}" y="0" width="{bar_width}" height="{height}" fill="black"/>'
		x += bar_width
	svg += '</svg>'
	
	svg_b64 = base64.b64encode(svg.encode()).decode()
	return f"data:image/svg+xml;base64,{svg_b64}"


@frappe.whitelist()
def get_packing_list_data(dispatch_log_name):
	"""Return carton-wise details and aggregated item summary for an Outward Shipment.
	Called from the packing list Jinja template to avoid sandbox restrictions."""
	from frappe.utils import flt

	dl = frappe.get_doc("Outward Shipment", dispatch_log_name)
	cartons = []
	item_summary = {}
	grand_pieces = 0
	grand_net = 0.0
	grand_gross = 0.0

	for row in (dl.cartons or []):
		cbl = frappe.get_doc("Packed Carton", row.carton_id)
		carton_pieces = 0
		carton_items = []

		for item in (cbl.items or []):
			qty = flt(item.qty)
			carton_pieces += qty
			carton_items.append({
				"item_code": item.item_code,
				"item_name": item.item_name or "",
				"qty": qty,
				"uom": item.uom or ""
			})
			# Aggregate
			if item.item_code in item_summary:
				item_summary[item.item_code]["qty"] += qty
			else:
				item_summary[item.item_code] = {
					"item_code": item.item_code,
					"item_name": item.item_name or "",
					"qty": qty,
					"uom": item.uom or ""
				}

		cartons.append({
			"name": cbl.name,
			"box_type": cbl.box_type,
			"dimensions": cbl.dimensions or "",
			"contents": carton_items,
			"net_weight_kg": flt(cbl.net_weight_kg),
			"gross_weight_kg": flt(cbl.gross_weight_kg),
			"packed_date": str(cbl.packed_date) if cbl.packed_date else "",
			"pieces": int(carton_pieces)
		})
		grand_pieces += carton_pieces
		grand_net += flt(cbl.net_weight_kg)
		grand_gross += flt(cbl.gross_weight_kg)

	return {
		"cartons": cartons,
		"item_summary": list(item_summary.values()),
		"grand_pieces": int(grand_pieces),
		"grand_net": round(grand_net, 2),
		"grand_gross": round(grand_gross, 2)
	}
