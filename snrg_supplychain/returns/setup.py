import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

TERMS = '''<p>Dispatch only approved items and quantities. Authorization is provisional and is not a promise of credit. Physical receipt is subject to QC and final acceptance.</p>
<p>Unauthorized non-defective material may be refused. If exceptionally accepted, a 25% restocking charge on the applicable pre-tax net invoice value applies, plus approved transport/handling costs. Used, incomplete, obsolete or unsellable material is normally ineligible.</p>
<p>Freight estimates are provisional; customer-payable freight uses actual transporter charges. Verified manufacturing defects and SNRG supply errors follow the agreed SNRG freight policy.</p>
<p>Disputes must be raised within 15 calendar days of the rejection notice. Rejected goods must be collected within 30 calendar days, or 15 days after dispute resolution if later. Mention the MRA number on packing lists and transport documents.</p>'''


def after_migrate():
    fields = [dict(fieldname='custom_is_customer', label='Is Also a Customer', fieldtype='Check', insert_after='supplier_name'),
        dict(fieldname='custom_linked_customer', label='Linked Customer', fieldtype='Link', options='Customer',
            insert_after='custom_is_customer', depends_on='eval:doc.custom_is_customer', mandatory_depends_on='eval:doc.custom_is_customer')]
    # Refuse to commandeer incompatible fields on customized sites.
    meta = frappe.get_meta('Supplier')
    for field in fields:
        existing = meta.get_field(field['fieldname'])
        if existing and (existing.fieldtype != field['fieldtype'] or (field.get('options') and existing.options != field['options'])):
            frappe.throw('Existing Supplier customer-link field is incompatible; review before migration.')
    create_custom_fields({'Supplier': fields}, update=False)
    config = frappe.get_single('Return Settings')
    if not config.policy_terms:
        config.policy_terms = TERMS
        config.save(ignore_permissions=True)


def validate_supplier(doc, method=None):
    if doc.get('custom_is_customer') and not doc.get('custom_linked_customer'):
        frappe.throw('Select Linked Customer when Is Also a Customer is checked.')
    if not doc.get('custom_is_customer') and doc.get('custom_linked_customer'):
        frappe.throw('Clear Linked Customer or enable Is Also a Customer.')
