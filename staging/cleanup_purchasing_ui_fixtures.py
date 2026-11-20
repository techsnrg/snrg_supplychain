"""Remove only the disposable purchasing browser fixtures from local staging."""
import os
import frappe
os.chdir('/home/frappe/frappe-bench/sites')
frappe.init(site='production-staging.localhost',sites_path='/home/frappe/frappe-bench/sites');frappe.connect()
try:
    assert frappe.local.site=='production-staging.localhost' and frappe.conf.get('mute_emails')
    frappe.set_user('Administrator')
    supplier=frappe.db.get_value('Supplier',{'supplier_name':'PURCHASING UI TEST ONLY'},'name')
    if supplier:
        orders=frappe.get_all('Purchase Order',filters={'supplier':supplier},pluck='name')
        for name in orders:
            po=frappe.get_doc('Purchase Order',name)
            assert (po.remarks or '').startswith('DISPOSABLE LOCAL UI TEST - ')
            if po.docstatus==1:po.cancel()
            frappe.delete_doc('Purchase Order',name)
        frappe.delete_doc('Supplier',supplier)
    if frappe.db.exists('Item','PURCHASING-UI-TEST-ONLY'):
        frappe.delete_doc('Item','PURCHASING-UI-TEST-ONLY')
    frappe.db.commit()
finally:frappe.destroy()
