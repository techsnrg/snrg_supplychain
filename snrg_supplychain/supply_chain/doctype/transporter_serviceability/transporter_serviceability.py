import frappe
import csv
import io
from frappe.model.document import Document
from frappe.utils import today, getdate


class TransporterServiceability(Document):

	def before_save(self):
		self.update_status()
		self.total_pin_codes = len(self.pin_codes)

	def on_submit(self):
		self.update_status()

	def update_status(self):
		t = getdate(today())
		valid_to = getdate(self.valid_to) if self.valid_to else None
		if valid_to and t > valid_to:
			self.status = "Expired"
		else:
			self.status = "Active"

	def validate(self):
		if self.valid_to and self.valid_from:
			if getdate(self.valid_to) < getdate(self.valid_from):
				frappe.throw("Valid To cannot be before Valid From.")


@frappe.whitelist()
def process_csv_upload(doc_name, file_url):
	"""
	Parse a CSV file and populate the pin_codes child table.
	Expected CSV columns (header row, case-insensitive):
	  PIN CODE, ZONE, STATE, ODA/SERVICEABILITY, ODA CATEGORY
	Returns dict: { loaded: int, errors: list }
	"""
	doc = frappe.get_doc("Transporter Serviceability", doc_name)

	# Fetch file content
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	file_path = frappe.get_site_path(file_doc.file_url.lstrip("/"))

	with open(file_path, "r", encoding="utf-8-sig") as f:
		content = f.read()

	reader = csv.DictReader(io.StringIO(content))

	# Normalise header keys
	def norm(k):
		return k.strip().upper().replace(" ", "_").replace("/", "_")

	loaded = 0
	errors = []

	# Clear existing rows
	doc.pin_codes = []

	SERVICEABILITY_MAP = {
		"SERVICEABLE": "SERVICEABLE",
		"ODA": "ODA",
		"NSZ": "NSZ",
	}
	ODA_CATEGORY_MAP = {"S", "A", "B", "C", "D", "E"}

	for i, row in enumerate(reader, start=2):  # start=2 because row 1 is header
		normed = {norm(k): (v or "").strip() for k, v in row.items()}

		pin_code = normed.get("PIN_CODE", "")
		zone = normed.get("ZONE", "")
		state = normed.get("STATE", "")
		serviceability_raw = normed.get("ODA_SERVICEABILITY", normed.get("SERVICEABILITY", "")).upper()
		oda_cat_raw = normed.get("ODA_CATEGORY", "").upper()

		if not pin_code:
			errors.append(f"Row {i}: Missing PIN CODE — skipped")
			continue

		serviceability = SERVICEABILITY_MAP.get(serviceability_raw)
		if not serviceability:
			errors.append(f"Row {i} (pin {pin_code}): Unknown serviceability '{serviceability_raw}' — defaulted to SERVICEABLE")
			serviceability = "SERVICEABLE"

		oda_category = oda_cat_raw if oda_cat_raw in ODA_CATEGORY_MAP else ""

		doc.append("pin_codes", {
			"pin_code": pin_code,
			"zone": zone,
			"state": state,
			"serviceability": serviceability,
			"oda_category": oda_category,
		})
		loaded += 1

	doc.total_pin_codes = loaded
	doc.save()

	return {"loaded": loaded, "errors": errors[:20]}  # Return max 20 errors to avoid huge response
