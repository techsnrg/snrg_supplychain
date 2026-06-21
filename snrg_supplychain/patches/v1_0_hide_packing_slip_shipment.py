import frappe


def execute():
	"""Frappe v15 removed the 'hidden' column from tabDocType — this patch
	is intentionally a no-op. Packing Slip, Shipment, and Shipment Parcel
	Template are excluded from the Supply Chain workspace via workspace
	configuration instead of DB-level hiding."""
	pass
