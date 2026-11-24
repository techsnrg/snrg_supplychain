import frappe
from frappe.utils import today, nowtime, flt
from erpnext.stock.utils import get_stock_balance
from snrg_supplychain.supply_chain import bulk_disassembly as service

def run():
 assert frappe.local.site == 'production-staging.localhost'
 frappe.set_user('Administrator')
 checks=[]
 doc=frappe.get_doc(dict(doctype='Bulk Disassembly',station='Staging Assembly',posting_date=today(),posting_time=nowtime(),notes='QA staging only: native BOM disassembly acceptance',items=[dict(item_code='10166-WH',qty=2),dict(item_code='10132-WH',qty=2)]))
 doc.insert();frappe.db.commit()
 assert doc.source_warehouse=='Finished Production - SPST'
 assert doc.target_warehouse=='Production Inputs - SPST'
 preview=service.review(doc.name)
 assert not preview['shortages'],preview
 assert not preview['valuation_issues'],preview
 checks.append('Reversed warehouse defaults and default BOM recovery review pass')
 entries=[service.make_entry(doc,r,service.settings(doc)) for r in doc.items]
 expected={}
 for entry in entries:
  assert entry.purpose=='Disassemble'
  for r in entry.items:
   key=(r.item_code,r.s_warehouse or r.t_warehouse)
   if key not in expected:expected[key]=[get_stock_balance(*key),0]
   expected[key][1]+=(-1 if r.s_warehouse else 1)*flt(r.qty)*flt(r.conversion_factor)
 service.post(doc.name,preview['review_token']);frappe.db.commit()
 service.process(doc.name,'Administrator')
 doc=frappe.get_doc('Bulk Disassembly',doc.name)
 assert doc.status=='Posted',[(r.status,r.error) for r in doc.items]
 names=[r.stock_entry for r in doc.items]
 for row in doc.items:
  entry=frappe.get_doc('Stock Entry',row.stock_entry)
  assert entry.docstatus==1 and entry.purpose=='Disassemble' and entry.custom_bulk_disassembly_row==row.name
  ledger=frappe.get_all('Stock Ledger Entry',filters=dict(voucher_no=entry.name,is_cancelled=0),fields=['actual_qty','stock_value_difference'])
  assert ledger and abs(sum(flt(r.stock_value_difference) for r in ledger))<0.02,ledger
  gl=frappe.get_all('GL Entry',filters=dict(voucher_no=entry.name,is_cancelled=0),fields=['debit','credit'])
  assert gl and abs(sum(flt(r.debit)-flt(r.credit) for r in gl))<0.02,gl
 for key,(before,change) in expected.items():assert abs(get_stock_balance(*key)-before-change)<0.000001,(key,before,change,get_stock_balance(*key))
 checks.append('Two native Disassemble entries submit; finished goods decrease, components increase, stock values and GL balance')
 service.process(doc.name,'Administrator')
 assert frappe.db.count('Stock Entry',{'custom_bulk_disassembly':doc.name})==2
 checks.append('Retry preserves two original entries without duplication')
 shortage=frappe.get_doc(dict(doctype='Bulk Disassembly',station='Staging Assembly',posting_date=today(),posting_time=nowtime(),notes='QA staging only: blocked review',items=[dict(item_code='10166-WH',qty=100000000)]));shortage.insert();frappe.db.commit()
 result=service.review(shortage.name);assert result['shortages']
 try:service.post(shortage.name,result['review_token'])
 except frappe.ValidationError:frappe.db.rollback()
 else:raise AssertionError('Shortage was accepted')
 assert not frappe.db.count('Stock Entry',{'custom_bulk_disassembly':shortage.name})
 checks.append('Insufficient finished goods block posting without creating entries')
 draft=frappe.get_doc(dict(doctype='Bulk Disassembly',station='Staging Assembly',posting_date=today(),posting_time=nowtime(),notes='QA staging only: UI preview',items=[dict(item_code='10166-WH',qty=1),dict(item_code='10132-WH',qty=1)]));draft.insert();frappe.db.commit()
 old=service.review(draft.name)['review_token'];draft.items[0].qty=2;draft.save();frappe.db.commit()
 try:service.post(draft.name,old)
 except frappe.ValidationError:frappe.db.rollback()
 else:raise AssertionError('Stale review accepted')
 checks.append('Edited quantities invalidate a previous review token')
 return dict(site=frappe.local.site,checks=checks,posted_sheet=doc.name,stock_entries=names,blocked_sheet=shortage.name,preview_sheet=draft.name)


def extended():
 from unittest.mock import patch
 assert frappe.local.site == 'production-staging.localhost'
 frappe.set_user('Administrator')
 checks=[]
 # Metadata first; custom Item Type is copied from an existing finished item.
 for dt in ('Item','BOM','Bulk Disassembly','Production Station'):
  assert frappe.get_meta(dt).fields
 code='QA-DISASSEMBLY-NO-COST'
 if not frappe.db.exists('Item',code):
  original=frappe.get_doc('Item','10166-WH')
  item=frappe.copy_doc(original);item.item_code=code;item.item_name='QA Disassembly Missing Cost';item.default_bom=None;item.valuation_rate=0;item.standard_rate=0;item.last_purchase_rate=0;item.insert()
 if not frappe.db.exists('BOM',dict(item=code,docstatus=1)):
  original=frappe.get_doc('BOM','BOM-10166-WH-002')
  bom=frappe.copy_doc(original);bom.item=code;bom.is_default=1;bom.insert();bom.submit()
 missing=frappe.get_doc(dict(doctype='Bulk Disassembly',station='Staging Assembly',posting_date=today(),posting_time=nowtime(),notes='QA staging: missing finished-good valuation',items=[dict(item_code=code,qty=1)]));missing.insert();frappe.db.commit()
 preview=service.review(missing.name)
 assert any(r['item_code']==code for r in preview['valuation_issues']),preview
 assert preview['shortages']
 checks.append('Never-valued finished goods show a missing-cost blocker during review')
 # An expanded production station must never turn moulded parts into polymer.
 try:
  service.settings(frappe._dict(station='Staging Expanded'))
 except frappe.ValidationError as exc:
  assert 'recovers stocked components' in str(exc)
  checks.append('Expanded raw-material stations are blocked; disassembly recovers stocked components')
 else:raise AssertionError('Expanded recovery accepted')
 viewer='production-viewer@staging.invalid'
 assert frappe.db.exists('User',viewer)
 frappe.set_user(viewer)
 try:service.review(missing.name)
 except frappe.PermissionError:checks.append('User without disassembly write permission cannot review')
 else:raise AssertionError('Unauthorized review accepted')
 finally:frappe.set_user('Administrator')
 # Queue atomically; simulate a competing consumer without changing actual bins.
 pending=frappe.get_doc(dict(doctype='Bulk Disassembly',station='Staging Assembly',posting_date=today(),posting_time=nowtime(),notes='QA staging: worker stock guard',items=[dict(item_code='10166-WH',qty=1)]));pending.insert();frappe.db.commit()
 preview=service.review(pending.name)
 with patch.object(frappe,'enqueue'):
  service.post(pending.name,preview['review_token']);frappe.db.commit()
 with patch.object(service,'check_entry_stock',return_value=[dict(item_code='10166-WH',required=1,available=0,warehouse=pending.source_warehouse)]):service.process(pending.name,'Administrator')
 pending=frappe.get_doc('Bulk Disassembly',pending.name)
 assert pending.status=='Failed' and not frappe.db.count('Stock Entry',dict(custom_bulk_disassembly=pending.name))
 checks.append('Worker rechecks stock and rolls back a depleted row without orphan entries')
 return dict(site=frappe.local.site,checks=checks,missing_cost_sheet=missing.name,failed_sheet=pending.name)
