import frappe


def execute():
	"""Frappe v15 removed the 'hidden' column from tabDocType — this patch
	is intentionally a no-op. Shipment Parcel Template is excluded from the
	Supply Chain workspace via workspace configuration instead."""
	pass
