from frappe import _
from snrg_supplychain.supply_chain.purchasing import overdue_deliveries


def execute(filters=None):
    specs = [
        ('purchase_order', 'Purchase Order', 'Link', 'Purchase Order', 170),
        ('supplier', 'Supplier', 'Link', 'Supplier', 140),
        ('supplier_name', 'Supplier Name', 'Data', None, 180),
        ('item_code', 'Item', 'Link', 'Item', 110),
        ('item_name', 'Item Name', 'Data', None, 220),
        ('required_by', 'Required By', 'Date', None, 110),
        ('days_overdue', 'Days Overdue', 'Int', None, 110),
        ('ordered_qty', 'Ordered Qty', 'Float', None, 110),
        ('received_qty', 'Received Qty', 'Float', None, 110),
        ('pending_qty', 'Pending Qty', 'Float', None, 110),
        ('uom', 'UOM', 'Link', 'UOM', 80),
        ('pending_value', 'Pending Value (Before Tax)', 'Currency', 'currency', 180),
        ('currency', 'Currency', 'Link', 'Currency', 90),
        ('created_by', 'Created By', 'Link', 'User', 180),
    ]
    columns = [dict(fieldname=n, label=_(label), fieldtype=t, options=o, width=w)
               for n, label, t, o, w in specs]
    data = overdue_deliveries(filters)
    summary = [dict(label=_('Pending Value (Before Tax)'), value=sum(r['pending_value'] for r in data),
                    datatype='Currency', currency=data[0]['currency'])] if data else []
    return columns, data, _('Direct-to-customer deliveries are excluded. Quantities use the PO UOM and ERPNext net received quantity.'), None, summary
