import frappe
from frappe.model.document import Document
from frappe.utils import today, getdate, flt


class FreightQuotation(Document):

	def validate(self):
		# Ensure only one row is marked selected
		selected = [r for r in self.freight_options if r.is_selected]
		if len(selected) > 1:
			frappe.throw("Please select only one transporter from the comparison table.")

	def before_submit(self):
		selected = [r for r in self.freight_options if r.is_selected]
		if not selected:
			frappe.throw("Please select a transporter before submitting the Freight Quotation.")
		row = selected[0]
		if row.pin_status in ("NSZ", "Not Listed"):
			frappe.throw(f"Cannot select {row.transporter} — pin code is {row.pin_status}.")


# ---------------------------------------------------------------------------
# Whitelisted API methods
# ---------------------------------------------------------------------------

@frappe.whitelist()
def create_from_dispatch(dispatch_log):
	"""
	Create a new Freight Quotation from a submitted Dispatch Log.
	Returns the name of the created Freight Quotation.
	"""
	# Check if one already exists
	existing = frappe.db.get_value("Freight Quotation", {"dispatch_log": dispatch_log, "docstatus": ["<", 2]}, "name")
	if existing:
		return existing

	dl = frappe.get_doc("Dispatch Log", dispatch_log)

	fq = frappe.new_doc("Freight Quotation")
	fq.dispatch_log = dispatch_log
	fq.customer = dl.customer
	fq.total_weight_kg = flt(dl.total_gross_weight)
	fq.status = "Draft"

	# Get invoice value from linked Sales Order
	if dl.sales_order:
		so_total = frappe.db.get_value("Sales Order", dl.sales_order, "grand_total")
		fq.invoice_value = flt(so_total)

	# Calculate total volume from cartons
	fq.total_volume_cm3 = _get_total_volume(dl)

	fq.insert()
	frappe.db.commit()

	# Link back to Dispatch Log
	frappe.db.set_value("Dispatch Log", dispatch_log, "freight_quotation", fq.name)

	return fq.name


@frappe.whitelist()
def calculate_freight(name):
	"""
	Calculate freight for all active transporters for the given Freight Quotation.
	Populates the freight_options child table and saves.
	"""
	doc = frappe.get_doc("Freight Quotation", name)
	doc.freight_options = []
	today_date = today()

	# 1. Resolve freight zone from delivery address
	if not doc.delivery_address:
		frappe.throw("Please select a Delivery Address before calculating freight.")

	addr = frappe.db.get_value(
		"Address", doc.delivery_address,
		["pincode", "city", "state"], as_dict=True
	)
	doc.pin_code = (addr.pincode or "").strip()
	doc.matched_city = (addr.city or "").strip()
	doc.matched_freight_zone = _resolve_freight_zone(addr.city, addr.state)

	# 2. Recalculate volume (in case cartons were updated)
	dl = frappe.get_doc("Dispatch Log", doc.dispatch_log)
	doc.total_weight_kg = flt(dl.total_gross_weight)
	doc.total_volume_cm3 = _get_total_volume(dl)

	# 3. Loop all suppliers marked as transporter
	transporters = frappe.get_all("Supplier", filters={"is_transporter": 1, "disabled": 0}, fields=["name"])
	for t in transporters:
		_append_transporter_row(doc, t.name, today_date)

	# Sort: Serviceable first, then ODA, then NSZ / Not Listed — by total_freight ascending
	STATUS_ORDER = {"Serviceable": 0, "ODA": 1, "NSZ": 2, "Not Listed": 3}
	doc.freight_options.sort(
		key=lambda r: (STATUS_ORDER.get(r.pin_status, 9), flt(r.total_freight))
	)

	doc.save()
	return doc.name


@frappe.whitelist()
def finalize_selection(name):
	"""
	Finalize the selected transporter.
	Copies selection to Freight Quotation header and back-updates Dispatch Log.
	"""
	doc = frappe.get_doc("Freight Quotation", name)

	selected = [r for r in doc.freight_options if r.is_selected]
	if not selected:
		frappe.throw("Please tick the 'Select' checkbox on your preferred transporter row first.")
	if len(selected) > 1:
		frappe.throw("More than one transporter is selected — please select only one.")

	row = selected[0]
	if row.pin_status in ("NSZ", "Not Listed"):
		frappe.throw(f"Cannot select {row.transporter} — pin code is marked as '{row.pin_status}'.")

	doc.selected_transporter = row.transporter
	doc.selected_freight_amount = row.total_freight
	doc.status = "Finalized"
	doc.save()

	# Update Dispatch Log
	frappe.db.set_value("Dispatch Log", doc.dispatch_log, {
		"selected_transporter": row.transporter,
		"freight_amount": row.total_freight
	})

	frappe.db.commit()
	return {"transporter": row.transporter, "amount": row.total_freight}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _append_transporter_row(doc, transporter_name, today_date):
	"""Calculate freight for one transporter and append to doc.freight_options."""

	# Get active rate card
	rate_card_name = _get_active_rate_card(transporter_name, today_date)
	if not rate_card_name:
		return  # No active rate card for this transporter — skip silently

	rc = frappe.get_doc("Transporter Rate Card", rate_card_name)

	# Dimensional weight (use transporter's own divisor)
	divisor = flt(rc.volumetric_divisor) or 1728
	dim_weight = flt(doc.total_volume_cm3) / divisor
	doc.dimensional_weight_kg = round(dim_weight, 3)
	billable_weight = max(flt(doc.total_weight_kg), dim_weight)

	# Get pin serviceability for this transporter
	pin_info = _get_pin_serviceability(transporter_name, doc.pin_code, today_date)
	pin_status = (pin_info.serviceability or "Not Listed") if pin_info else "Not Listed"
	oda_category_raw = (pin_info.oda_category or "") if pin_info else ""

	# Map pin_status display value
	if pin_status == "SERVICEABLE":
		pin_status_display = "Serviceable"
	elif pin_status == "ODA":
		pin_status_display = "ODA"
	elif pin_status == "NSZ":
		pin_status_display = "NSZ"
	else:
		pin_status_display = "Not Listed"

	# NSZ — show row but no freight calculation
	if pin_status_display == "NSZ":
		doc.append("freight_options", {
			"transporter": transporter_name,
			"rate_card": rate_card_name,
			"pin_status": "NSZ",
			"oda_category": "",
			"total_freight": 0,
			"remarks": "Non-Serviceable Zone for this transporter"
		})
		return

	# Basic freight (zone-based)
	basic_freight, zone_remark = _calc_basic_freight(rc, doc.matched_freight_zone, billable_weight)

	# ODA charge
	oda_charge = 0
	extra_tat = 0
	oda_label = ""
	if pin_status_display == "ODA" and oda_category_raw and oda_category_raw != "S":
		oda_charge, extra_tat = _calc_oda_charge(rc, oda_category_raw, billable_weight)
		oda_label = f"{oda_category_raw} ({_get_oda_label(oda_category_raw)})"

	# Other charges
	fov = flt(doc.invoice_value) * flt(rc.fov_percentage) / 100
	fuel = basic_freight * flt(rc.fuel_surcharge_percentage) / 100
	docket = flt(rc.docket_charge)
	total = basic_freight + oda_charge + fov + docket + fuel
	total = max(total, flt(rc.minimum_freight))

	# Determine remarks
	remarks = zone_remark
	if billable_weight > flt(doc.total_weight_kg) and flt(doc.total_weight_kg) > 0:
		remarks = (remarks + " | " if remarks else "") + "Billed on volumetric weight"

	doc.append("freight_options", {
		"transporter": transporter_name,
		"rate_card": rate_card_name,
		"pin_status": pin_status_display,
		"oda_category": oda_label,
		"extra_tat_days": extra_tat,
		"matched_zone": doc.matched_freight_zone,
		"billable_weight_kg": round(billable_weight, 3),
		"basic_freight": round(basic_freight, 2),
		"oda_charge": round(oda_charge, 2),
		"fov_charge": round(fov, 2),
		"docket_charge": round(docket, 2),
		"fuel_surcharge": round(fuel, 2),
		"total_freight": round(total, 2),
		"remarks": remarks
	})


def _resolve_freight_zone(city, state):
	"""Two-step zone lookup: metro city first, then rest-of-state fallback."""
	if city:
		# Case-insensitive city match
		metro = frappe.db.sql(
			"""SELECT name FROM `tabFreight Zone`
			   WHERE LOWER(city) = LOWER(%s) AND zone_type = 'Metro City' AND is_active = 1
			   LIMIT 1""",
			(city,), as_dict=True
		)
		if metro:
			return metro[0].name

	if state:
		fallback = frappe.db.sql(
			"""SELECT name FROM `tabFreight Zone`
			   WHERE LOWER(state) = LOWER(%s) AND is_fallback = 1 AND is_active = 1
			   LIMIT 1""",
			(state,), as_dict=True
		)
		if fallback:
			return fallback[0].name

	return None


def _get_active_rate_card(transporter, today_date):
	"""Get the most recent active Transporter Rate Card for a transporter."""
	cards = frappe.get_all(
		"Transporter Rate Card",
		filters={
			"transporter": transporter,
			"valid_from": ["<=", today_date],
			"docstatus": 1
		},
		fields=["name", "valid_to"],
		order_by="valid_from desc"
	)
	for c in cards:
		if not c.valid_to or getdate(c.valid_to) >= getdate(today_date):
			return c.name
	return None


def _get_pin_serviceability(transporter, pin_code, today_date):
	"""Find pin code row in the latest valid serviceability record for this transporter."""
	if not pin_code:
		return None

	records = frappe.get_all(
		"Transporter Serviceability",
		filters={
			"transporter": transporter,
			"valid_from": ["<=", today_date],
			"docstatus": 1
		},
		fields=["name", "valid_to"],
		order_by="valid_from desc"
	)
	for rec in records:
		if rec.valid_to and getdate(rec.valid_to) < getdate(today_date):
			continue
		row = frappe.db.get_value(
			"Transporter Serviceability Pin",
			{"parent": rec.name, "pin_code": pin_code},
			["serviceability", "oda_category"],
			as_dict=True
		)
		if row:
			return row
	return None


def _calc_basic_freight(rate_card, freight_zone, weight_kg):
	"""
	Find the matching rate slab (by zone + weight) and return (amount, remark).
	"""
	if not freight_zone:
		return 0, "Freight zone not resolved — check delivery address city/state"

	slabs = [s for s in rate_card.rate_slabs if s.freight_zone == freight_zone]
	if not slabs:
		return 0, f"No rate configured for zone: {freight_zone}"

	slabs_sorted = sorted(slabs, key=lambda x: flt(x.from_weight_kg))
	for slab in slabs_sorted:
		in_range = (
			flt(weight_kg) >= flt(slab.from_weight_kg) and
			(flt(slab.to_weight_kg) == 0 or flt(weight_kg) <= flt(slab.to_weight_kg))
		)
		if in_range:
			billable = max(flt(weight_kg), flt(slab.minimum_billable_weight_kg) or 0)
			return billable * flt(slab.rate_per_kg), ""

	return 0, "Weight outside all configured rate slabs"


def _calc_oda_charge(rate_card, category, weight_kg):
	"""
	Return (oda_charge, extra_tat_days) for a given ODA category and weight.
	"""
	rates = [r for r in rate_card.oda_rates if r.oda_category == category]
	if not rates:
		return 0, 0

	min_charge = max((flt(r.minimum_charge) for r in rates), default=0)
	extra_tat = max((int(r.extra_tat_days or 0) for r in rates), default=0)

	rates_sorted = sorted(rates, key=lambda x: flt(x.from_weight_kg))
	for rate_row in rates_sorted:
		in_range = (
			flt(weight_kg) >= flt(rate_row.from_weight_kg) and
			(flt(rate_row.to_weight_kg) == 0 or flt(weight_kg) <= flt(rate_row.to_weight_kg))
		)
		if in_range:
			if rate_row.rate_type == "Flat":
				charge = flt(rate_row.rate)
			else:
				charge = flt(weight_kg) * flt(rate_row.rate)
			return max(charge, min_charge), extra_tat

	return min_charge, extra_tat


def _get_total_volume(dispatch_log_doc):
	"""Sum L×W×H (in³) for all cartons in the dispatch log."""
	total = 0.0
	for ctn_row in dispatch_log_doc.cartons:
		box_type = frappe.db.get_value("Carton Box Log", ctn_row.carton_id, "box_type")
		if box_type:
			dims = frappe.db.get_value(
				"Carton Box Type", box_type,
				["length_in", "width_in", "height_in"], as_dict=True
			)
			if dims:
				total += flt(dims.length_in) * flt(dims.width_in) * flt(dims.height_in)
	return total


def _get_oda_label(category):
	return {
		"A": "26-50 KM",
		"B": "51-100 KM",
		"C": "101-200 KM",
		"D": "Custom Range",
		"E": "Above 200 KM"
	}.get(category, "")
