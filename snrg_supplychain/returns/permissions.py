import frappe


def has_other_qi_read_role(user=None):
    roles=frappe.get_roles(user)
    if (user or frappe.session.user)=='Administrator':return True
    # Preserve any pre-existing native/custom QC reader role, not only Quality Manager.
    return any(p.role in roles and p.role!='Return Reviewer' and p.read and not p.permlevel
        for p in frappe.get_meta('Quality Inspection').permissions)


def qi_query(user=None):
    roles=frappe.get_roles(user)
    if 'Return Reviewer' in roles and not has_other_qi_read_role(user):
        return "coalesce(`tabQuality Inspection`.`custom_return_mra`, '') != ''"
    return ''


def qi_permission(doc,user=None,permission_type=None,**kwargs):
    roles=frappe.get_roles(user)
    if 'Return Reviewer' in roles and not has_other_qi_read_role(user) and not doc.get('custom_return_mra'):
        return False
    # In Frappe v16 this is a deny-only hook: True preserves base DocPerm checks.
    return True


def other_native_reader(doctype,user=None):
    if (user or frappe.session.user)=='Administrator':return True
    roles=frappe.get_roles(user)
    return any(p.role in roles and p.role!='Return Reviewer' and p.read and not p.permlevel for p in frappe.get_meta(doctype).permissions)


def arrival_permission(doc,user=None,permission_type=None,**kwargs):
    if 'Return Reviewer' in frappe.get_roles(user) and not other_native_reader(doc.doctype,user):
        return bool(doc.get('custom_return_mra') and doc.get('custom_return_purpose')=='Arrival')
    return True


def arrival_filter(doctype,user=None):
    if 'Return Reviewer' in frappe.get_roles(user) and not other_native_reader(doctype,user):
        return f"coalesce(`tab{doctype}`.`custom_return_mra`,'') != '' and `tab{doctype}`.`custom_return_purpose`='Arrival'"
    return ''


def stock_entry_query(user=None):return arrival_filter('Stock Entry',user)
def delivery_note_query(user=None):return arrival_filter('Delivery Note',user)
def purchase_receipt_query(user=None):return arrival_filter('Purchase Receipt',user)
