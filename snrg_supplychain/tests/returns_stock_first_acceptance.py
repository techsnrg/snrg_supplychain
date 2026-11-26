"""Real ERPNext v3 returns acceptance. Docker staging only; never production."""
import json
from pathlib import Path
import frappe
from frappe.utils import flt,today
from .returns_native_acceptance import guard,check,reject,workflow,make_sale,approve_finance,accounting_refs,CHECKS,COMPANY
from .returns_acceptance import seed,user,admin,stock_receipt
from snrg_supplychain.returns import api,stock_first


def baseline():
    guard()
    data=dict(counts={dt:frappe.db.count(dt) for dt in ('GL Entry','Stock Ledger Entry','Return Receipt','Return Inspection','Return Settlement')},
        legacy=frappe.get_all('Material Return Authorization',fields=['name','workflow_state','native_returns_version','approved_by','settlement_approved_by','gross_value','net_value'],order_by='name',limit_page_length=0),
        settings={x:frappe.db.get_single_value('Stock Settings',x) for x in ('action_if_quality_inspection_is_rejected','action_if_quality_inspection_is_not_submitted','allow_to_make_quality_inspection_after_purchase_or_delivery')})
    Path('/tmp/returns-stock-first-before.json').write_text(json.dumps(data,default=str));return dict(passed=True,counts=data['counts'])


def verify_install():
    guard();before=json.loads(Path('/tmp/returns-stock-first-before.json').read_text())
    check(before['counts']=={dt:frappe.db.count(dt) for dt in before['counts']},'Stock-first install creates no stock/accounting or custom custody transactions')
    check(json.loads(json.dumps(frappe.get_all('Material Return Authorization',fields=['name','workflow_state','native_returns_version','approved_by','settlement_approved_by','gross_value','net_value'],order_by='name',limit_page_length=0),default=str))==before['legacy'],'Install preserves all existing case versions, approvals and values')
    for dt in ('Delivery Note','Purchase Receipt','Stock Entry'):
        meta=frappe.get_meta(dt);check(meta.has_field('custom_return_mra') and meta.has_field('custom_return_documents_complete'),dt+' has inspected native arrival metadata')
    return dict(passed=True,checks=CHECKS)


def new_case(invoice,warehouse,route='SNRG Credit Note',supplier=None,qty=4):
    user('sales');line=invoice.items[0]
    doc=frappe.get_doc(dict(doctype='Material Return Authorization',company=COMPANY,customer=invoice.customer,currency='INR',information_complete=1,
        responsible_user=frappe.session.user,freight_terms='Actual freight after receipt',route=route,supplier=supplier,return_warehouse=warehouse,
        items=[dict(item_code=line.item_code,uom=line.uom,claimed_category='Suspected Manufacturing Defect',claimed_qty=qty,approved_qty=qty,
            reason='Stock-first QA',condition='Current Saleable',sales_invoice=invoice.name,sales_invoice_item=line.name,invoice_confirmed=1,invoice_source='Manually Selected')])).insert()
    check(doc.native_returns_version==3,'New MRA selects stock-first native receipts')
    doc=workflow(doc,'Request Approval');reject(lambda:workflow(doc,'Authorize'),'Sales cannot authorize a return')
    user('md');doc=frappe.get_doc(doc.doctype,doc.name);doc.approval_reason='Stock-first QA authorized';doc.save();doc=workflow(doc,'Authorize')
    reject(lambda:api.populate('Return Receipt',doc.name),'New cases cannot create custom custody receipts')
    return doc


def post_arrival(mra,split=True):
    user('stock');choices=api.arrival_options(mra.name);choice=choices[0]
    values=api.stock_arrival(mra.name,choice['doctype'],choice.get('source'))
    doc=frappe.get_doc(values);doc.custom_return_documents_complete=1
    # Mark known zero freight reconciled by Finance after the physical receipt.
    before=frappe.db.count('Stock Ledger Entry');doc.insert();doc.submit()
    check(doc.docstatus==1 and frappe.db.count('Stock Ledger Entry')>before,'Native arrival posts stock before any QC or customer settlement')
    check(bool(frappe.db.exists('ToDo',{'reference_type':doc.doctype,'reference_name':doc.name,'status':'Open'})),'Native assignment tracks QC on the posted arrival')
    check(not frappe.db.exists('Quality Inspection',dict(reference_type=doc.doctype,reference_name=doc.name)),'Arrival needs no prior QC and does not invent an inspection')
    sle=frappe.get_all('Stock Ledger Entry',filters=dict(voucher_type=doc.doctype,voucher_no=doc.name,is_cancelled=0),fields=['actual_qty','stock_value_difference','warehouse'])
    check(abs(sum(flt(x.actual_qty) for x in sle)-4)<0.001 and all(x.warehouse==mra.return_warehouse for x in sle),'All four arrived units enter only the Returns quarantine warehouse')
    user('finance');doc=frappe.get_doc(doc.doctype,doc.name);doc.custom_return_freight_responsibility='SNRG';doc.custom_return_freight_finalized=1;doc.save()
    return doc,sle


def inspect(arrival,split=True):
    user('qc');values=api.arrival_inspection(arrival.doctype,arrival.name,arrival.items[0].name)
    doc=frappe.get_doc(values);doc.manual_inspection=1;doc.status='Rejected'
    doc.custom_return_allocations[0].update(dict(qty=3 if split else 4,decision='Accept',finding='Manufacturing Defect',notes='Warranty acceptance despite failed product test'))
    if split:doc.append('custom_return_allocations',dict(qty=1,decision='Reject',finding='Customer Damage',notes='Customer-caused damage'))
    doc.insert();doc.submit();check(doc.docstatus==1 and doc.status=='Rejected','Native QC runs after posted receipt and preserves failed product-test status')
    return doc


def move(mra,qi,target,arrival):
    user('stock')
    for row in qi.custom_return_allocations:
        if row.decision=='Reject':
            unsafe=frappe.get_doc(api.stock_disposition(mra.name,qi.name,row.name,target))
            reject(lambda:(unsafe.insert(),unsafe.submit()),'Commercially refused goods cannot be released into usable inventory')
            doc=frappe.get_doc(arrival.doctype,arrival.name);doc.custom_return_disposition='Collected';doc.custom_return_disposition_evidence='/files/stock-first-collection-proof.pdf';doc.save()
        values=api.stock_disposition(mra.name,qi.name,row.name,target if row.decision=='Accept' else None)
        doc=frappe.get_doc(values);doc.insert();doc.submit()
        check(doc.docstatus==1,'Native '+doc.doctype+' posts '+row.decision+' QC disposition once')
        reject(lambda:api.stock_disposition(mra.name,qi.name,row.name,target if row.decision=='Accept' else None),'Already moved QC allocation cannot be moved twice')


def run():
    guard();before=json.loads(Path('/tmp/returns-stock-first-before.json').read_text())
    customer,supplier,item,warehouse=seed()
    # Native stock users need invoice read permission for confirmed source/valuation evidence.
    for who in ('stock','qc','md','other-md','finance'):frappe.get_doc('User','returns-'+who+'@staging.invalid').add_roles('Return Reviewer')
    frappe.get_doc('User','returns-stock@staging.invalid').add_roles('Accounts User')
    admin()
    quarantine='Returns Pending QC v3 - SPST'
    if not frappe.db.exists('Warehouse',quarantine):frappe.get_doc(dict(doctype='Warehouse',warehouse_name='Returns Pending QC v3',company=COMPANY,custom_returns_quarantine=1)).insert()
    stock_receipt(item.name,150,warehouse,80)
    original=make_sale(customer.name,item.name,warehouse,100)
    # Price and stock cost intentionally differ.
    mra=new_case(original,quarantine);arrival,sle=post_arrival(mra)
    check(arrival.doctype=='Stock Entry','Stock-updating invoice without a Delivery Note uses native Material Receipt fallback')
    probe=frappe._dict(custom_return_mra_item=mra.items[0].name,custom_return_source_invoice=original.name,custom_return_source_invoice_item=original.items[0].name,item_code=item.name,uom='Nos')
    expected=stock_first.source_cost(mra,probe)
    check(abs(sum(flt(x.stock_value_difference) for x in sle)-4*expected)<0.02 and expected!=100,'Arrival preserves original stock cost independently from selling price 100')
    user('stock');values=api.stock_arrival(mra.name,'Stock Entry',original.name) if False else None
    # Uninspected inventory cannot be consumed via an ordinary untagged voucher.
    admin();ordinary=frappe.get_doc(dict(doctype='Stock Entry',stock_entry_type='Material Issue',company=COMPANY,items=[dict(item_code=item.name,qty=1,uom='Nos',s_warehouse=quarantine)]))
    reject(lambda:(ordinary.insert(),ordinary.submit()),'Quarantine prevents ordinary stock consumption before QC disposition')
    qi=inspect(arrival)
    user('stock');reject(lambda:frappe.get_doc(arrival.doctype,arrival.name).cancel(),'Posted arrival cannot be cancelled while its native QC is active')
    mra=approve_finance(mra)
    user('finance');values=api.native_document(mra.name,'Sales Invoice',original.name,update_stock=1)
    credit=frappe.get_doc(values);check(not credit.update_stock,'Settlement factory forces non-stock credit even when caller requests stock')
    before_sle=frappe.db.count('Stock Ledger Entry');credit.insert();credit.submit()
    check(frappe.db.count('Stock Ledger Entry')==before_sle and abs(credit.net_total)==300,'Credit note settles three accepted units at 100 without receiving stock again')
    bad=frappe.get_doc(api.native_document(mra.name,'Sales Invoice',original.name));bad.update_stock=1
    reject(lambda:(bad.insert(),bad.submit()),'Manual stock-updating credit is rejected after arrival')
    mra=accounting_refs(mra,credit,arrival)
    reject(lambda:workflow(mra,'Close Return'),'Case cannot close while inspected goods remain in Pending QC')
    move(mra,qi,warehouse,arrival);user('finance');mra=workflow(mra,'Close Return');check(mra.workflow_state=='Closed','Credit route closes after physical and financial reconciliation')
    # Native Delivery Note route, then a non-stock Sales Invoice and its return.
    admin();dn=frappe.get_doc(dict(doctype='Delivery Note',company=COMPANY,customer=customer.name,currency='INR',items=[dict(item_code=item.name,qty=10,rate=120,uom='Nos',warehouse=warehouse)]));dn.insert();dn.submit()
    from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice
    sale=make_sales_invoice(dn.name);sale.insert();sale.submit()
    second=new_case(sale,quarantine);arrival2,sle2=post_arrival(second);check(arrival2.doctype=='Delivery Note' and arrival2.is_return and arrival2.return_against==dn.name,'Original delivery uses native Delivery Note return into quarantine')
    qi2=inspect(arrival2);second=approve_finance(second);user('finance')
    credit2=frappe.get_doc(api.native_document(second.name,'Sales Invoice',sale.name));credit2.insert();credit2.submit();second=accounting_refs(second,credit2,arrival2)
    move(second,qi2,warehouse,arrival2);user('finance');second=workflow(second,'Close Return');check(second.workflow_state=='Closed','Delivery Note arrival and subsequent credit complete without duplicate stock')
    # Customer-issued invoice route: arrival is acquisition-valued native PR.
    third=new_case(original,quarantine,'Customer Invoice',supplier.name)
    arrival3,sle3=post_arrival(third);check(arrival3.doctype=='Purchase Receipt' and abs(sum(flt(x.stock_value_difference) for x in sle3)-400)<0.02,'Customer invoice route receives native PR at confirmed acquisition rate, not zero')
    qi3=inspect(arrival3);user('finance');third=frappe.get_doc(third.doctype,third.name);third.customer_invoice_number='QA-STOCK-FIRST';third.customer_invoice_date=today();third.customer_invoice_attachment='/files/stock-first-bill.pdf';third.save();third=approve_finance(third)
    user('finance');pi=frappe.get_doc(api.native_document(third.name,'Purchase Invoice'));pi.due_date=today();pi.insert();pi.submit()
    check(not pi.update_stock and pi.items[0].purchase_receipt==arrival3.name and pi.net_total==300,'Purchase Invoice bills accepted quantity against arrival PR without second stock receipt')
    admin();offset=frappe.get_doc(dict(doctype='Journal Entry',voucher_type='Journal Entry',company=COMPANY,posting_date=today(),custom_return_mra=third.name,custom_return_purpose='Offset',accounts=[
        dict(account=frappe.get_cached_value('Company',COMPANY,'default_payable_account'),party_type='Supplier',party=supplier.name,debit_in_account_currency=300,reference_type='Purchase Invoice',reference_name=pi.name),
        dict(account=frappe.get_cached_value('Company',COMPANY,'default_receivable_account'),party_type='Customer',party=customer.name,credit_in_account_currency=300,reference_type='Sales Invoice',reference_name=original.name)]));offset.insert();offset.submit()
    third=accounting_refs(third,pi,arrival3,offset=offset);move(third,qi3,warehouse,arrival3);user('finance');third=workflow(third,'Close Return');check(third.workflow_state=='Closed','Customer-invoice route closes with native purchase return for refused units and separate offset')
    # Ordinary, untagged QC policy remains active.
    admin();old_flag=frappe.db.get_value('Item',item.name,'inspection_required_before_purchase')
    frappe.db.set_value('Item',item.name,'inspection_required_before_purchase',1);frappe.clear_cache(doctype='Item')
    ordinary=frappe.get_doc(dict(doctype='Purchase Receipt',company=COMPANY,supplier=supplier.name,currency='INR',items=[dict(item_code=item.name,qty=1,rate=100,uom='Nos',warehouse=warehouse)]))
    reject(lambda:(ordinary.insert(),ordinary.submit()),'Ordinary untagged purchases still require native pre-receipt QC')
    frappe.db.set_value('Item',item.name,'inspection_required_before_purchase',old_flag);frappe.clear_cache(doctype='Item')
    extra=new_case(original,quarantine,qty=13)
    user('stock');values=api.stock_arrival(extra.name,'Stock Entry',original.name)
    too_many=frappe.get_doc(values);too_many.custom_return_documents_complete=1
    reject(lambda:(too_many.insert(),too_many.submit()),'Global source entitlement blocks over-receipt across separate MRAs')
    user('finance');extra=frappe.get_doc(extra.doctype,extra.name);extra.closure_reason='QA source-limit check: no arrival';extra.save();extra=workflow(extra,'Close Without Accepted Goods')
    admin()
    balance=frappe.get_all('Stock Ledger Entry',filters={'warehouse':quarantine,'is_cancelled':0},fields=['actual_qty','stock_value_difference'],limit_page_length=0)
    check(abs(sum(flt(x.actual_qty) for x in balance))<0.000001 and abs(sum(flt(x.stock_value_difference) for x in balance))<0.02,'Returns quarantine finishes with zero residual quantity and valuation after disposition')
    check({x:frappe.db.get_single_value('Stock Settings',x) for x in before['settings']}==before['settings'],'Global purchase/delivery QC settings remain unchanged')
    check(frappe.db.count('Return Receipt')==before['counts']['Return Receipt'],'All stock-first flows created zero custom Return Receipts')
    for receipt in (arrival,arrival2,arrival3):
        gl=frappe.get_all('GL Entry',filters=dict(voucher_type=receipt.doctype,voucher_no=receipt.name,is_cancelled=0),fields=['debit','credit'])
        check(abs(sum(flt(x.debit)-flt(x.credit) for x in gl))<0.01,'Native arrival '+receipt.name+' has balanced valuation GL')
    frappe.db.commit()
    result=dict(passed=True,checks=CHECKS,site=frappe.local.site,records=dict(credit_mra=mra.name,delivery_mra=second.name,purchase_mra=third.name,
        arrival=arrival.name,arrival_type=arrival.doctype,delivery_arrival=arrival2.name,purchase_arrival=arrival3.name,credit_note=credit.name,purchase_invoice=pi.name,qi=qi.name,quarantine=quarantine,original_sale=original.name))
    Path('/tmp/returns-stock-first-results.json').write_text(json.dumps(result,default=str));return result


def repeat_install():
    guard()
    def evidence():
        return dict(counts={dt:frappe.db.count(dt) for dt in ('GL Entry','Stock Ledger Entry','Return Receipt','Quality Inspection')},
            cases=frappe.get_all('Material Return Authorization',fields=['name','workflow_state','native_returns_version','approved_by','settlement_approved_by','gross_value','net_value'],order_by='name',limit_page_length=0))
    before=evidence();previous=frappe.flags.in_migrate
    try:
        frappe.flags.in_migrate=True
        from snrg_supplychain.returns.native_setup import after_migrate
        after_migrate();after_migrate()
    finally:frappe.flags.in_migrate=previous
    check(evidence()==before,'Repeated stock-first install preserves ledger counts, native QC, legacy custody and all signed case values')
    frappe.db.commit();result=dict(passed=True,checks=CHECKS)
    Path('/tmp/returns-stock-first-repeat.json').write_text(json.dumps(result,default=str));return result


def provision_ui_user():
    """Called only by the host credential bootstrapper; result goes directly to OS keyring."""
    guard()
    email='returns-stock-first-ui@staging.invalid'
    if not frappe.db.exists('User',email):
        doc=frappe.get_doc(dict(doctype='User',email=email,first_name='Returns Stock First UI QA',enabled=1,send_welcome_email=0,user_type='System User'))
        doc.flags.no_welcome_mail=True;doc.insert()
    doc=frappe.get_doc('User',email);doc.add_roles('Sales User','Sales Manager','Accounts User','Stock Manager','Quality Manager','Managing Director','Return Reviewer')
    from frappe.utils.password import update_password
    password=frappe.generate_hash(length=32)
    update_password(email,password,logout_all_sessions=True);frappe.db.commit()
    return dict(user=email,password=password)


def verify_saved_valuation():
    guard();saved=json.loads(Path('/tmp/returns-stock-first-results.json').read_text());records=saved['records']
    doc=frappe.get_doc('Delivery Note',records['delivery_arrival']);mra=frappe.get_doc('Material Return Authorization',records['delivery_mra'])
    expected=stock_first.source_cost(mra,doc.items[0]);sle=frappe.get_all('Stock Ledger Entry',filters=dict(voucher_type=doc.doctype,voucher_no=doc.name,is_cancelled=0),fields=['stock_value_difference'])
    check(abs(sum(flt(x.stock_value_difference) for x in sle)-4*expected)<0.02,'Delivery Note return stock value matches original outgoing cost independently from sales price')
    for dt,name in [(records['arrival_type'],records['arrival']),('Delivery Note',records['delivery_arrival']),('Purchase Receipt',records['purchase_arrival'])]:
        check(not frappe.db.exists('ToDo',dict(reference_type=dt,reference_name=name,status='Open')),'Completed native inspection closes its receipt QC assignment')
    saved['checks']+=CHECKS;Path('/tmp/returns-stock-first-results.json').write_text(json.dumps(saved,default=str));return dict(passed=True,checks=CHECKS)
