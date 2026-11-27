"""Disposable local-browser examples; run only on the isolated staging site."""
import os,json
import frappe
from frappe.utils import nowdate,add_days
os.chdir('/home/frappe/frappe-bench/sites')
frappe.init(site='production-staging.localhost',sites_path='/home/frappe/frappe-bench/sites');frappe.connect()
try:
    assert frappe.conf.get('mute_emails') and frappe.local.site=='production-staging.localhost'
    frappe.set_user('Administrator')
    supplier_name='PURCHASING UI TEST ONLY'
    supplier=frappe.db.get_value('Supplier',{'supplier_name':supplier_name},'name')
    if not supplier:supplier=frappe.get_doc(dict(doctype='Supplier',supplier_name=supplier_name,supplier_group='Local',supplier_type='Company')).insert().name
    code='PURCHASING-UI-TEST-ONLY'
    if not frappe.db.exists('Item',code):
        source=frappe.db.get_value('Item',{'disabled':0,'stock_uom':'Nos'},['item_group','custom_item_type'],as_dict=True)
        frappe.get_doc(dict(doctype='Item',item_code=code,item_name='Purchasing UI Test Only',item_group=source.item_group,custom_item_type=source.custom_item_type,stock_uom='Nos',is_stock_item=0)).insert()
    names=[]
    for label,rate,when,submit in [('History',100,add_days(nowdate(),-5),True),('Draft',110,nowdate(),False)]:
        po=frappe.get_doc(dict(doctype='Purchase Order',supplier=supplier,company='SNRG Production Staging',currency='INR',conversion_rate=1,transaction_date=when,schedule_date=max(when,add_days(nowdate(),-1)),remarks='DISPOSABLE LOCAL UI TEST - '+label,items=[dict(item_code=code,qty=10,uom='Nos',rate=rate,schedule_date=max(when,add_days(nowdate(),-1)))]))
        po.insert()
        if submit:po.submit()
        names.append({'label':label,'name':po.name})
    frappe.db.commit();print(json.dumps({'supplier':supplier,'item':code,'orders':names}))
finally:frappe.destroy()
