"""Read-only purchasing tools. Parent queries always use Frappe's permission filters."""
import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


def normalized_rate(base_net_rate, conversion_factor):
    factor = flt(conversion_factor)
    return flt(base_net_rate) / factor if factor > 0 else None


def variance_percent(current, previous):
    return (current - previous) / previous * 100 if previous and previous > 0 else None


@frappe.whitelist()
def compare_purchase_rates(document):
    doc = frappe._dict(frappe.parse_json(document))
    if doc.get('doctype') != 'Purchase Order':
        frappe.throw(_('Expected a Purchase Order'))
    if doc.get('name') and frappe.db.exists('Purchase Order', doc.name):
        frappe.get_doc('Purchase Order', doc.name).check_permission('read')
    elif not frappe.has_permission('Purchase Order', 'create'):
        frappe.throw(_('Not permitted'), frappe.PermissionError)
    items = doc.get('items') or []
    if len(items) > 200:
        frappe.throw(_('Compare at most 200 item rows at a time'))
    if not doc.get('company') or not doc.get('supplier') or not doc.get('transaction_date'):
        return []
    cutoff = min(getdate(doc.transaction_date), getdate(nowdate()))
    output, cache = [], {}
    for item in items:
        item = frappe._dict(item)
        key = (item.get('item_code'), item.get('stock_uom'))
        if not all(key):
            continue
        if key not in cache:
            filters = [
                ['Purchase Order', 'company', '=', doc.company],
                ['Purchase Order', 'supplier', '=', doc.supplier],
                ['Purchase Order', 'docstatus', '=', 1],
                ['Purchase Order', 'transaction_date', '<=', cutoff],
                ['Purchase Order Item', 'item_code', '=', key[0]],
                ['Purchase Order Item', 'stock_uom', '=', key[1]],
            ]
            if doc.get('name'):
                filters.append(['Purchase Order', 'name', '!=', doc.name])
            # For saved/backdated orders do not use orders created later on the same date.
            if doc.get('creation'):
                filters.append(['Purchase Order', 'creation', '<', doc.creation])
            candidates = frappe.get_list('Purchase Order', filters=filters,
                fields=['name', 'transaction_date'],
                order_by='transaction_date desc, creation desc, name desc', page_length=1)
            previous = None
            if candidates:
                source = frappe.get_doc('Purchase Order', candidates[0].name)
                source.check_permission('read')
                rows = [r for r in source.items if r.item_code == key[0]
                        and r.stock_uom == key[1] and flt(r.stock_qty) > 0
                        and flt(r.conversion_factor) > 0]
                qty = sum(flt(r.stock_qty) for r in rows)
                if qty:
                    previous = dict(purchase_order=source.name, date=source.transaction_date,
                        rate=sum(flt(r.base_net_amount) for r in rows) / qty)
            cache[key] = previous
        previous = cache[key]
        current = normalized_rate(item.get('base_net_rate'), item.get('conversion_factor'))
        output.append(dict(idx=item.get('idx'), item_code=key[0], stock_uom=key[1],
            current_rate=current, previous_rate=previous['rate'] if previous else None,
            previous_po=previous['purchase_order'] if previous else None,
            previous_date=previous['date'] if previous else None,
            variance=variance_percent(current, previous['rate']) if previous and current is not None else None))
    return output


def pending_delivery(qty, received_qty, net_rate):
    pending = max(flt(qty) - flt(received_qty), 0)
    return pending, pending * flt(net_rate)


def overdue_deliveries(filters):
    filters = frappe._dict(filters or {})
    if not filters.get('company'):
        frappe.throw(_('Select a company'))
    if not frappe.has_permission('Purchase Order', 'read'):
        frappe.throw(_('Not permitted'), frappe.PermissionError)
    today = getdate(nowdate())
    conditions = {'company': filters.company, 'docstatus': 1,
                  'status': ['not in', ['Closed', 'Cancelled', 'Completed', 'Delivered']]}
    for name in ['supplier', 'owner']:
        if filters.get(name):
            conditions[name] = filters[name]
    parents = frappe.get_list('Purchase Order', filters=conditions, fields=['name'], page_length=0)
    data = []
    minimum = max(int(filters.get('minimum_days') or 1), 1)
    for parent in parents:
        po = frappe.get_doc('Purchase Order', parent.name)
        po.check_permission('read')
        for row in po.items:
            if row.delivered_by_supplier or (filters.get('item_code') and row.item_code != filters.item_code):
                continue
            due = row.schedule_date or po.schedule_date
            if not due:
                continue
            days = (today - getdate(due)).days
            pending, value = pending_delivery(row.qty, row.received_qty, row.base_net_rate)
            if days < minimum or pending <= 0:
                continue
            data.append(dict(purchase_order=po.name, supplier=po.supplier, supplier_name=po.supplier_name,
                item_code=row.item_code, item_name=row.item_name, required_by=due,
                ordered_qty=row.qty, received_qty=row.received_qty, pending_qty=pending,
                uom=row.uom, days_overdue=days, pending_value=value,
                currency=frappe.get_cached_value('Company', po.company, 'default_currency'),
                created_by=po.owner))
    return sorted(data, key=lambda r: (-r['days_overdue'], r['purchase_order'], r['item_code']))
