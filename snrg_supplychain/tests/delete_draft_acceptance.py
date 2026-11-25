import frappe
from frappe.utils import today,nowtime

def run():
 assert frappe.local.site=='production-staging.localhost'
 frappe.set_user('Administrator')
 checks=[]
 for module,dt in [('daily_production','Daily Production'),('bulk_disassembly','Bulk Disassembly')]:
  frappe.reload_doc('supply_chain','doctype',module)
  frappe.clear_cache(doctype=dt)
  service=__import__('snrg_supplychain.supply_chain.'+module,fromlist=['delete_draft'])
  assert all(r.delete for r in frappe.get_meta(dt).permissions if r.create)
  before=frappe.db.count('Stock Entry')
  doc=frappe.get_doc(dict(doctype=dt,station='Staging Assembly',posting_date=today(),posting_time=nowtime(),notes='Disposable delete-draft regression fixture',items=[dict(item_code='10166-WH',qty=1)]));doc.insert();frappe.db.commit()
  assert frappe.get_doc(dt,doc.name).status=='Draft'
  service.delete_draft(doc.name);frappe.db.commit()
  assert not frappe.db.exists(dt,doc.name)
  assert not frappe.db.exists(dt+' Item',{'parent':doc.name})
  checks.append(dt+': confirmed draft deleted with children and no stock posting')
  posted=frappe.db.get_value(dt,{'status':'Posted'},'name');assert posted
  for action in [lambda:service.delete_draft(posted),lambda:frappe.delete_doc(dt,posted)]:
   try:action()
   except frappe.ValidationError:frappe.db.rollback()
   else:raise AssertionError('Posted sheet deletion accepted')
  assert frappe.get_doc(dt,posted).status=='Posted'
  assert frappe.db.count('Stock Entry')==before
  checks.append(dt+': custom and native deletion preserve posted sheets')
 return {'site':frappe.local.site,'checks':checks}
