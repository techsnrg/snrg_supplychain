import json
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_migrate():
    create_custom_fields({'Stock Entry': [
        dict(fieldname='custom_bulk_disassembly',label='Bulk Disassembly',fieldtype='Link',options='Bulk Disassembly',insert_after='work_order',read_only=1,no_copy=1),
        dict(fieldname='custom_bulk_disassembly_row',label='Bulk Disassembly Row',fieldtype='Data',insert_after='custom_bulk_disassembly',read_only=1,hidden=1,unique=1,no_copy=1),
        dict(fieldname='custom_daily_production',label='Bulk Production',fieldtype='Link',options='Daily Production',insert_after='work_order',read_only=1,no_copy=1),
        dict(fieldname='custom_daily_production_row',label='Bulk Production Row',fieldtype='Data',insert_after='custom_daily_production',read_only=1,hidden=1,unique=1,no_copy=1),
    ]})

    # Populate the new permission-bearing link on pre-existing sheets without
    # changing their production quantities, status or posting references.
    frappe.db.sql("""update `tabDaily Production` p
        inner join `tabProduction Station` s on p.station=s.name
        set p.company=s.company where p.company is null or p.company=''""")

    # Preserve the original warehouse snapshot for previously queued/posted sheets.
    rows = frappe.get_all('Daily Production', fields=['name','station','source_warehouse','target_warehouse','settings_snapshot'])
    for row in rows:
        if row.source_warehouse and row.target_warehouse:
            continue
        snapshot = json.loads(row.settings_snapshot) if row.settings_snapshot else {}
        station = frappe.get_doc('Production Station', row.station)
        values = {field: row.get(field) or snapshot.get(field) or station.get(field)
                  for field in ('source_warehouse','target_warehouse')}
        frappe.db.set_value('Daily Production',row.name,values,update_modified=False)
