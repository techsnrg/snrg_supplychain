"""Test real HTTP endpoints with a temporary local buyer; never print credentials."""
import os,json,secrets
import frappe,requests
from frappe.utils.password import update_password
os.chdir('/home/frappe/frappe-bench/sites')
frappe.init(site='production-staging.localhost',sites_path='/home/frappe/frappe-bench/sites');frappe.connect()
user='purchasing-http-test@example.invalid'
try:
    assert frappe.local.site=='production-staging.localhost' and frappe.conf.get('mute_emails')
    frappe.set_user('Administrator')
    assert not frappe.db.exists('User',user)
    frappe.get_doc(dict(doctype='User',email=user,first_name='Purchasing HTTP Test',send_welcome_email=0,roles=[{'role':'Purchase User'}])).insert()
    secret=secrets.token_urlsafe(32);update_password(user,secret,logout_all_sessions=False);frappe.db.commit()
    session=requests.Session();base='http://127.0.0.1:8000'
    response=session.post(base+'/api/method/login',data={'usr':user,'pwd':secret});response.raise_for_status();del secret
    response=session.get(base+'/api/resource/Purchase Order/PUR-ORD-2026-00002');response.raise_for_status();doc=response.json()['data']
    response=session.post(base+'/api/method/snrg_supplychain.supply_chain.purchasing.compare_purchase_rates',data={'document':json.dumps(doc)});response.raise_for_status();comparison=response.json()['message']
    assert comparison[0]['previous_rate']==100 and comparison[0]['current_rate']==110
    response=session.post(base+'/api/method/frappe.desk.query_report.run',data={'report_name':'Overdue Supplier Deliveries','filters':json.dumps({'company':'SNRG Production Staging','supplier':'PURCHASING UI TEST ONLY'}),'ignore_prepared_report':1});response.raise_for_status();report=response.json()['message']
    assert len(report['result'])==1 and report['result'][0]['pending_qty']==10
    print(json.dumps({'buyer_rate_endpoint':'PASS','buyer_report_endpoint':'PASS','report_columns':len(report['columns']),'rows':len(report['result'])}))
finally:
    frappe.set_user('Administrator')
    if frappe.db.exists('User',user):frappe.delete_doc('User',user,ignore_permissions=True)
    frappe.db.commit();frappe.destroy()
