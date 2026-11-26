"""Native-returns integration acceptance. Refuses every site except Docker staging."""
import json
from pathlib import Path

import frappe

SITE='production-staging.localhost'


def guard():
    if frappe.local.site!=SITE:raise RuntimeError('Local Docker staging only')
    frappe.set_user('Administrator')


def snapshot():
    guard()
    data={dt:frappe.get_all(dt,fields=['name','status'],order_by='name',limit_page_length=0)
        for dt in ('Return Inspection','Return Settlement')}
    data['gl_count']=frappe.db.count('GL Entry')
    data['sle_count']=frappe.db.count('Stock Ledger Entry')
    Path('/tmp/returns-native-before.json').write_text(json.dumps(data,default=str))
    print(json.dumps({k:len(v) if isinstance(v,list) else v for k,v in data.items()}))
    return data

from frappe.utils import today,add_days,getdate,flt
from frappe.model.workflow import apply_workflow,get_transitions
from snrg_supplychain.returns import api
from snrg_supplychain.returns import native_service as service
from snrg_supplychain.tests.returns_acceptance import seed as legacy_seed,user,admin,stock_receipt

CHECKS=[]
COMPANY='SNRG Production Staging'


def check(value,message):
    if not value:raise AssertionError(message)
    CHECKS.append(message);print('PASS: '+message,flush=True)


def reject(fn,message):
    frappe.db.savepoint('native_returns_reject')
    try:fn()
    except (frappe.ValidationError,frappe.PermissionError):
        frappe.db.rollback(save_point='native_returns_reject');CHECKS.append(message)
        print('PASS: '+message,flush=True);return
    raise AssertionError('Expected rejection: '+message)


def workflow(doc,action):
    return apply_workflow(frappe.get_doc(doc.doctype,doc.name).as_dict(),action)


def verify_migration():
    guard()
    before=json.loads(Path('/tmp/returns-native-before.json').read_text())
    for dt in ('Return Inspection','Return Settlement'):
        after=frappe.get_all(dt,fields=['name','status'],order_by='name',limit_page_length=0)
        check(after==before[dt],dt+' history retained with original identities and statuses')
        check(frappe.get_meta(dt).read_only,dt+' is read-only legacy evidence')
    check(frappe.db.count('GL Entry')==before['gl_count'],'Refactor migration posted no GL entries')
    check(frappe.db.count('Stock Ledger Entry')==before['sle_count'],'Refactor migration posted no Stock Ledger entries')
    migrated=frappe.get_all('Quality Inspection',filters={'custom_legacy_inspection':['is','set']},fields=['name','reference_type','custom_legacy_inspection'])
    check(len(migrated)>=len(before['Return Inspection']),'Legacy QC imported into native Quality Inspection with provenance')
    check(frappe.db.get_value('Workflow',{'document_type':'Material Return Authorization','is_active':1},'name')=='SNRG Return Case Workflow','Native MRA Workflow is active')
    check(frappe.db.get_value('Workflow',{'document_type':'Return Receipt','is_active':1},'name')=='SNRG Return Custody Workflow','Native custody Workflow is active')
    check(frappe.db.count('Notification',{'name':['like','SNRG Returns -%'],'channel':'System Notification'})==3,'Native system Notifications configured without customer email delivery')
    check(frappe.db.count('Assignment Rule',{'name':['like','SNRG Returns -%']})==2,'Native Assignment Rules replace custom task scheduler')
    result=dict(passed=True,checks=CHECKS[:],native_qi_count=len(migrated))
    Path('/tmp/returns-native-migration.json').write_text(json.dumps(result))
    print(json.dumps(result))
    return result


def make_sale(customer,item,warehouse,rate):
    admin()
    doc=frappe.get_doc(dict(doctype='Sales Invoice',company=COMPANY,customer=customer,
        posting_date=today(),due_date=today(),currency='INR',selling_price_list='Standard Selling',
        price_list_currency='INR',plc_conversion_rate=1,update_stock=1,
        items=[dict(item_code=item,qty=20,rate=rate,uom='Nos',warehouse=warehouse)]))
    doc.insert();doc.submit();return doc


def make_mra(invoice,warehouse,category='Suspected Manufacturing Defect',qty=4):
    user('sales');row=invoice.items[0]
    doc=frappe.get_doc(dict(doctype='Material Return Authorization',company=COMPANY,
        customer=invoice.customer,currency='INR',request_date=today(),information_complete=1,
        responsible_user=frappe.session.user,freight_estimate=25,freight_terms='Native refactor QA: actual freight after QC.',
        return_warehouse=warehouse,items=[dict(item_code=row.item_code,uom=row.uom,claimed_category=category,
            reason='Native feature acceptance QA',claimed_qty=qty,approved_qty=qty,sales_invoice=invoice.name,
            sales_invoice_item=row.name,invoice_source='Manually Selected',invoice_confirmed=1,condition='Current Saleable')]))
    doc.insert()
    check(doc.workflow_state=='Draft' and doc.native_migration_complete,'New case uses native Workflow and will not be re-imported as legacy')
    doc=workflow(doc,'Request Approval')
    check(doc.workflow_state=='Pending Approval' and doc.due_date,'Native Workflow starts the authorization SLA')
    reject(lambda:workflow(doc,'Authorize'),'Sales cannot perform the MD native Workflow action')
    user('md');doc=frappe.get_doc(doc.doctype,doc.name);doc.approval_reason='QA authorized subject to QC';doc.save()
    doc=workflow(doc,'Authorize')
    check(doc.approved_by=='returns-md@staging.invalid','Native MD action creates commercial authorization audit')
    changed=frappe.get_doc(doc.doctype,doc.name);changed.items[0].approved_qty+=1
    reject(changed.save,'Authorized item/value snapshot remains frozen')
    return frappe.get_doc(doc.doctype,doc.name)


def receipt(mra,qty=None):
    user('stock')
    values=api.populate('Return Receipt',mra.name)
    if qty is not None:values['items'][0]['received_qty']=qty
    values['documents_complete']=1
    before=(frappe.db.count('GL Entry'),frappe.db.count('Stock Ledger Entry'))
    doc=frappe.get_doc(values).insert();doc=workflow(doc,'Confirm Receipt')
    check(before==(frappe.db.count('GL Entry'),frappe.db.count('Stock Ledger Entry')),'Custody confirmation posts neither GL nor Stock Ledger')
    check(doc.due_date and doc.workflow_state=='Received','Native receipt Workflow starts the QC deadline')
    check(bool(frappe.db.exists('ToDo',{'reference_type':'Return Receipt','reference_name':doc.name,'status':'Open'})),'Native Assignment Rule assigns the custody/QC action')
    return doc


def freight(doc,amount=50,responsibility='SNRG'):
    admin()
    vendor=frappe.get_doc(dict(doctype='Supplier',supplier_name='Native Return Freight '+frappe.generate_hash(length=5),
        supplier_type='Company',supplier_group=frappe.db.get_value('Supplier Group',{'is_group':0},'name'),is_transporter=1)).insert()
    bill=frappe.get_doc(dict(doctype='Purchase Invoice',company=COMPANY,supplier=vendor.name,
        currency='INR',posting_date=today(),due_date=today(),bill_date=today(),bill_no='QA-FRT-'+frappe.generate_hash(length=5),
        custom_return_mra=doc.authorization,custom_return_purpose='Freight',
        items=[dict(item_name='Return freight service',description='Native QA transporter bill',qty=1,rate=amount,uom='Nos',
            expense_account=frappe.get_cached_value('Company',COMPANY,'default_expense_account'))]))
    bill.insert();bill.submit()
    user('finance');doc=frappe.get_doc(doc.doctype,doc.name)
    doc.update(dict(actual_freight=amount,freight_responsibility=responsibility,freight_bill=bill.name,transporter=vendor.name,freight_finalized=1))
    doc.save()
    check(flt(doc.customer_freight)==(amount if responsibility=='Customer' else 0),'Actual native transporter bill allocated independently of who pays it')
    return doc


def inspect(doc,split=False,commercial=False):
    user('qc');values=api.populate('Quality Inspection',doc.name,doc.items[0].name)
    qi=frappe.get_doc(values)
    qi.custom_return_allocations[0].update(dict(finding='Fresh / Saleable' if commercial else 'Manufacturing Defect',
        decision='Accept',notes='Native QC confirms condition',exception_reason='QA exceptional commercial acceptance' if commercial or doc.items[0].unauthorized else None))
    if split:
        qi.custom_return_allocations[0].qty-=1
        qi.append('custom_return_allocations',dict(qty=1,finding='Customer Damage',decision='Reject',notes='QA storage damage'))
    qi.quality_inspection_template='Returns QA Product Check'
    qi.append('readings',dict(specification='Returns QA Functional Check',numeric=0,value='Pass',reading_value='Fail' if not commercial else 'Pass'))
    qi.insert();qi.submit()
    qi=frappe.get_doc('Quality Inspection',qi.name)
    check(qi.docstatus==1 and qi.reference_type=='Return Receipt','Native QC submits against exact non-posting custody row')
    check(qi.status==('Accepted' if commercial else 'Rejected'),'Native product-test status is retained separately from commercial acceptance')
    source=frappe.get_doc('Return Receipt',doc.name)
    check(source.quality_complete and source.items[0].quality_inspection==qi.name,'Native QI writes its reference back and completes custody QC')
    return qi


def approve_finance(mra,exceptions=False,concession=False):
    if exceptions:
        user('finance')
        reject(lambda:workflow(mra,'Prepare Settlement'),'Finance cannot accept fresh/unauthorized quantities without MD review')
        user('md');doc=frappe.get_doc(mra.doctype,mra.name);doc.exception_reason='QA case-specific commercial acceptance';doc.save();mra=workflow(doc,'Approve Return Exceptions')
    user('finance');mra=workflow(mra,'Prepare Settlement')
    check(mra.workflow_state=='Finance Review' and mra.settlement_items,'Native Finance Workflow builds settlement directly on MRA')
    if concession:
        mra=frappe.get_doc(mra.doctype,mra.name);mra.restocking_charge=flt(mra.standard_restocking)/2;mra.waiver_reason='QA MD-only restocking concession';mra.save()
        reject(lambda:workflow(mra,'Approve Settlement'),'Finance cannot approve an unsigned concession')
        mra=workflow(mra,'Request Concession')
        user('other-md');reject(lambda:workflow(mra,'Approve Concession'),'A different MD-role user cannot approve the designated-user concession')
        user('md');mra=workflow(mra,'Approve Concession')
        check(mra.waiver_approved_by=='returns-md@staging.invalid','Native concession Workflow records the designated MD')
    user('md');reject(lambda:workflow(mra,'Approve Settlement'),'Managing Director cannot perform final Finance approval')
    user('finance');mra=workflow(mra,'Approve Settlement')
    check(mra.settlement_approved_by=='returns-finance@staging.invalid','Final approval belongs to Finance rather than the MD')
    return mra


def accounting_refs(mra,settlement,stock,charge=None,offset=None):
    user('finance');doc=frappe.get_doc(mra.doctype,mra.name)
    doc.append('accounting_documents',dict(document_type=settlement.doctype,document_name=settlement.name,purpose='Settlement'))
    if charge:doc.append('accounting_documents',dict(document_type='Sales Invoice',document_name=charge.name,purpose='Charge'))
    if offset:doc.append('accounting_documents',dict(document_type=offset.doctype,document_name=offset.name,purpose='Offset / Payment'))
    doc.append('stock_references',dict(document_type=stock.doctype,document_name=stock.name,notes='Native accepted return stock'))
    doc.stock_reconciled=doc.charges_reconciled=doc.ledger_reconciled=1
    doc.reconciliation_notes='QA native stock, charges and both party ledgers reconciled';doc.save()
    doc=workflow(doc,'Mark Settled')
    check(doc.workflow_state=='Settled','Native documents reconcile and settle on MRA without a custom settlement parent')
    return doc


def run():
    guard()
    config_before={k:frappe.db.get_single_value('Stock Settings',k) for k in ('action_if_quality_inspection_is_rejected','action_if_quality_inspection_is_not_submitted','allow_to_make_quality_inspection_after_purchase_or_delivery')}
    customer,supplier,item,source_warehouse=legacy_seed()
    for name in ('md','other-md','finance','stock'):
        frappe.get_doc('User','returns-'+name+'@staging.invalid').add_roles('Return Reviewer')
    quarantine='Returns QA Quarantine - SPST'
    if not frappe.db.exists('Warehouse',quarantine):
        frappe.get_doc(dict(doctype='Warehouse',warehouse_name='Returns QA Quarantine',company=COMPANY)).insert()
    if not frappe.db.exists('Quality Inspection Parameter','Returns QA Functional Check'):
        frappe.get_doc(dict(doctype='Quality Inspection Parameter',parameter='Returns QA Functional Check')).insert()
    if not frappe.db.exists('Quality Inspection Template','Returns QA Product Check'):
        template=frappe.get_doc(dict(doctype='Quality Inspection Template',quality_inspection_template_name='Returns QA Product Check',
            item_quality_inspection_parameter=[dict(specification='Returns QA Functional Check',numeric=0,value='Pass')])).insert()
    if not frappe.db.exists('Price List','Minimum Selling Rate'):
        frappe.get_doc(dict(doctype='Price List',price_list_name='Minimum Selling Rate',currency='INR',selling=1,enabled=1)).insert()
    if not frappe.db.exists('Item Price',{'item_code':item.name,'price_list':'Minimum Selling Rate','currency':'INR'}):
        frappe.get_doc(dict(doctype='Item Price',item_code=item.name,price_list='Minimum Selling Rate',currency='INR',uom=item.stock_uom,price_list_rate=80)).insert()
    opening=stock_receipt(item.name,100,source_warehouse,80)
    original=make_sale(customer.name,item.name,source_warehouse,100)
    latest=make_sale(customer.name,item.name,source_warehouse,120)
    user('sales');found=api.invoice_sales(COMPANY,customer.name,item.name,item.stock_uom,'INR')
    check(found['rows'][0]['sales_invoice']==latest.name,'Optional latest-invoice lookup still uses real eligible sales')
    first=make_mra(original,quarantine)
    received=freight(receipt(first))
    qi=inspect(received,split=True)
    first=approve_finance(first)
    user('finance')
    credit=frappe.get_doc(api.native_document(first.name,'Sales Invoice',original.name,1));credit.insert();credit.submit()
    check(credit.is_return and credit.update_stock and credit.return_against==original.name,'Native credit-note mapper preserves original invoice and returns stock once')
    check(bool(frappe.db.exists('GL Entry',{'voucher_no':credit.name,'is_cancelled':0})) and bool(frappe.db.exists('Stock Ledger Entry',{'voucher_no':credit.name,'is_cancelled':0})),'Credit note creates real native GL and Stock Ledger entries')
    check(flt(credit.net_total)==-300,'Credit covers only three commercially accepted units at original net rate 100')
    first=accounting_refs(first,credit,credit)
    reject(lambda:workflow(first,'Close Return'),'Rejected goods must have disposition before case closure')
    admin();notice=frappe.get_doc(dict(doctype='File',file_name='native-return-qa.txt',content='Synthetic native return notice',is_private=1)).insert()
    user('stock');received=frappe.get_doc('Return Receipt',received.name)
    received.findings_notice=notice.file_url;received.rejection_notice_date=today();received.save()
    check(getdate(received.dispute_deadline)==getdate(add_days(today(),15)) and getdate(received.collection_deadline)==getdate(add_days(today(),30)),'15-day dispute and 30-day collection policy retained on custody')
    received.dispute_status='Resolved';received.resolved_on=add_days(today(),25);received.resolution='QA resolution';received.save()
    check(getdate(received.collection_deadline)==getdate(add_days(today(),40)),'Collection extends to 15 days after later dispute resolution')
    received.disposition='Collected';received.disposition_date=today();received.disposition_evidence=notice.file_url;received.save()
    user('finance');first=workflow(first,'Close Return');check(first.workflow_state=='Closed','Credit-note case closes through native Workflow')
    reject(lambda:frappe.get_doc('Sales Invoice',credit.name).cancel(),'Closed case protects its linked native credit note from cancellation')
    # Customer-issued invoice route; product QC can fail while the return is accepted.
    second=make_mra(latest,quarantine,category='Commercial Return',qty=2)
    user('finance');second=frappe.get_doc(second.doctype,second.name);second.route='Customer Invoice';second.supplier=supplier.name;second.save()
    received2=freight(receipt(second),responsibility='Customer')
    qi2=inspect(received2,commercial=True)
    second=approve_finance(second,exceptions=True,concession=True)
    check(flt(second.standard_restocking)==60 and flt(second.restocking_charge)==30 and flt(second.freight_charge)==50,'25 percent standard charge, MD reduction and actual freight reconcile on MRA')
    user('finance');second=frappe.get_doc(second.doctype,second.name)
    second.customer_invoice_number='NATIVE-QA-'+frappe.generate_hash(length=5);second.customer_invoice_date=today();second.customer_invoice_attachment=notice.file_url;second.save()
    receipt_doc=frappe.get_doc(api.native_document(second.name,'Purchase Receipt'))
    receipt_doc.insert();receipt_doc.submit()
    check(receipt_doc.docstatus==1 and sum(flt(x.qty) for x in receipt_doc.items)==2 and not any(flt(x.rejected_qty) for x in receipt_doc.items),'Native Purchase Receipt receives only commercially accepted goods')
    pi=frappe.get_doc(api.native_document(second.name,'Purchase Invoice'));pi.insert();pi.submit()
    check(not pi.update_stock and pi.items[0].purchase_receipt==receipt_doc.name,'Native Purchase Receipt → Purchase Invoice mapping avoids a second stock receipt')
    def duplicate_receipt():
        duplicate=frappe.get_doc(api.native_document(second.name,'Purchase Invoice'));duplicate.update_stock=1
        duplicate.insert();duplicate.submit()
    reject(duplicate_receipt,'Same accepted stock cannot be received again through a second native invoice')
    admin()
    charge=frappe.get_doc(dict(doctype='Sales Invoice',company=COMPANY,customer=customer.name,posting_date=today(),due_date=today(),
        selling_price_list='Standard Selling',price_list_currency='INR',plc_conversion_rate=1,currency='INR',
        custom_return_mra=second.name,custom_return_purpose='Charge',
        items=[dict(item_name='Approved return charges',description='Restocking and actual freight',qty=1,rate=80,uom='Nos',income_account=frappe.get_cached_value('Company',COMPANY,'default_income_account'))]))
    charge.insert();charge.submit()
    je=frappe.get_doc(dict(doctype='Journal Entry',voucher_type='Journal Entry',company=COMPANY,posting_date=today(),
        custom_return_mra=second.name,custom_return_purpose='Offset',accounts=[
            dict(account=frappe.get_cached_value('Company',COMPANY,'default_payable_account'),party_type='Supplier',party=supplier.name,
                debit_in_account_currency=240,reference_type='Purchase Invoice',reference_name=pi.name),
            dict(account=frappe.get_cached_value('Company',COMPANY,'default_receivable_account'),party_type='Customer',party=customer.name,
                credit_in_account_currency=240,reference_type='Sales Invoice',reference_name=latest.name)]))
    je.insert();je.submit()
    second=accounting_refs(second,pi,receipt_doc,charge,je);second=workflow(second,'Close Return')
    check(second.workflow_state=='Closed','Customer-invoice case closes with mapped Supplier and native separate offset')
    # Multiple shipments, excess approval, failed native product QC and direct PI stock route.
    third=make_mra(latest,quarantine,qty=2)
    user('finance');third=frappe.get_doc(third.doctype,third.name);third.route='Customer Invoice';third.supplier=supplier.name;third.save()
    first_shipment=freight(receipt(third,qty=1))
    third_qi=inspect(first_shipment)
    extra_shipment=freight(receipt(third,qty=2))
    check(flt(extra_shipment.items[0].unauthorized_qty)==1,'Cumulative shipments identify one excess unit beyond authorization')
    extra_qi=inspect(extra_shipment)
    third=approve_finance(third,exceptions=True)
    user('finance');third=frappe.get_doc(third.doctype,third.name)
    third.customer_invoice_number='NATIVE-QA-DIRECT-'+frappe.generate_hash(length=4);third.customer_invoice_date=today();third.customer_invoice_attachment=notice.file_url;third.save()
    admin();old_incoming=frappe.db.get_value('Item',item.name,'inspection_required_before_purchase')
    frappe.db.set_value('Item',item.name,'inspection_required_before_purchase',1);frappe.clear_cache(doctype='Item')
    user('finance');direct=frappe.get_doc(api.native_document(third.name,'Purchase Invoice'));direct.insert();direct.submit()
    check(direct.update_stock and len(direct.items)==2,'Direct Purchase Invoice receives multiple accepted custody allocations once')
    check(third_qi.status=='Rejected' and extra_qi.status=='Rejected','Failed product readings remain Rejected while warranty goods are commercially accepted')
    check(bool(frappe.db.exists('Stock Ledger Entry',{'voucher_no':direct.name,'is_cancelled':0})),'Return-scoped adapter admits approved defective goods without disabling ordinary inspection requirements')
    admin();frappe.db.set_value('Item',item.name,'inspection_required_before_purchase',old_incoming);frappe.clear_cache(doctype='Item')
    direct_offset=frappe.get_doc(dict(doctype='Journal Entry',voucher_type='Journal Entry',company=COMPANY,posting_date=today(),
        custom_return_mra=third.name,custom_return_purpose='Offset',accounts=[
            dict(account=frappe.get_cached_value('Company',COMPANY,'default_payable_account'),party_type='Supplier',party=supplier.name,
                debit_in_account_currency=360,reference_type='Purchase Invoice',reference_name=direct.name),
            dict(account=frappe.get_cached_value('Company',COMPANY,'default_receivable_account'),party_type='Customer',party=customer.name,
                credit_in_account_currency=360,reference_type='Sales Invoice',reference_name=latest.name)]))
    direct_offset.insert();direct_offset.submit()
    third=accounting_refs(third,direct,direct,offset=direct_offset);third=workflow(third,'Close Return')
    check(third.workflow_state=='Closed','Excess/multiple-shipment direct-PI case closes through native Finance Workflow')
    # Prove ordinary inspection rules and visibility are not weakened by return adapters.
    admin();frappe.db.savepoint('normal_qc_flags')
    old_flag=frappe.db.get_value('Item',item.name,'inspection_required_before_purchase')
    frappe.db.set_value('Item',item.name,'inspection_required_before_purchase',1);frappe.clear_cache(doctype='Item')
    ordinary=frappe.get_doc(dict(doctype='Purchase Receipt',company=COMPANY,supplier=supplier.name,currency='INR',
        items=[dict(item_code=item.name,qty=1,rate=120,uom='Nos',warehouse=quarantine)]))
    reject(lambda:(ordinary.insert(),ordinary.submit()),'Untagged ordinary Purchase Receipt still stops when required native QC is missing')
    frappe.db.rollback(save_point='normal_qc_flags');frappe.clear_cache(doctype='Item')
    normal_qi=frappe.get_doc(dict(doctype='Quality Inspection',company=COMPANY,inspection_type='Incoming',reference_type='Stock Entry',
        reference_name=opening.name,child_row_reference=opening.items[0].name,item_code=item.name,sample_size=1,inspected_by='Administrator',manual_inspection=1,status='Accepted'))
    normal_qi.insert();normal_qi.submit()
    user('finance');reject(lambda:frappe.get_doc('Quality Inspection',normal_qi.name).check_permission('read'),'Return Reviewer cannot open unrelated native inspections')
    visible=frappe.get_list('Quality Inspection',fields=['name'],page_length=0)
    check(normal_qi.name not in {x.name for x in visible} and qi.name in {x.name for x in visible},'Return Reviewer lists return QC only')
    admin();config_after={k:frappe.db.get_single_value('Stock Settings',k) for k in config_before}
    check(config_after==config_before,'Global native inspection settings remain unchanged')
    html=frappe.get_print(first.doctype,first.name,print_format='Material Return Authorization')
    check(first.name in html and 'DRAFT — NOT VALID' not in html,'Native print framework renders authorized MRA after refactor')
    from frappe.utils.pdf import get_pdf
    # Browser uses the host proxy; wkhtmltopdf runs inside the app container.
    previous_host = frappe.local.conf.host_name
    try:
        frappe.local.conf.host_name = 'http://127.0.0.1:8000'
        pdf = get_pdf(html.replace(previous_host, frappe.local.conf.host_name))
    finally:
        frappe.local.conf.host_name = previous_host
    Path('/tmp/returns-native-acceptance.pdf').write_bytes(pdf)
    check(pdf.startswith(b'%PDF'),'Native MRA PDF renders successfully')
    check(frappe.db.count('Return Settlement')==len(json.loads(Path('/tmp/returns-native-before.json').read_text())['Return Settlement']),'Complete flow created no custom settlement parent')
    check(frappe.db.count('Return Inspection')==len(json.loads(Path('/tmp/returns-native-before.json').read_text())['Return Inspection']),'Complete flow created no custom inspection parent')
    frappe.db.commit()
    result=dict(site=SITE,passed=True,checks=CHECKS,records=dict(customer=customer.name,supplier=supplier.name,
        credit_mra=first.name,invoice_mra=second.name,direct_invoice_mra=third.name,credit_note=credit.name,purchase_receipt=receipt_doc.name,
        purchase_invoice=pi.name,offset=je.name,credit_qi=qi.name,invoice_qi=qi2.name,credit_custody=received.name,
        invoice_custody=received2.name,original_sale=original.name,latest_sale=latest.name),pdf='/tmp/returns-native-acceptance.pdf')
    Path('/tmp/returns-native-results.json').write_text(json.dumps(result,default=str))
    print(json.dumps(result,default=str));return result


def verify_repeat_migration():
    guard()
    def evidence():
        return dict(counts={dt:frappe.db.count(dt) for dt in ('Quality Inspection','Return Inspection','Return Settlement','GL Entry','Stock Ledger Entry')},
            cases=frappe.get_all('Material Return Authorization',fields=['name','workflow_state','approved_by','settlement_approved_by','gross_value','net_value'],order_by='name',limit_page_length=0))
    before=evidence()
    from snrg_supplychain.returns.native_setup import after_migrate
    previous = frappe.flags.in_migrate
    try:
        frappe.flags.in_migrate = True
        after_migrate();after_migrate()
    finally:
        frappe.flags.in_migrate = previous
    check(evidence()==before,'Repeated native migration preserves case signatures, QC counts, legacy records and both ledgers')
    frappe.db.commit()
    result=dict(passed=True,checks=CHECKS[:])
    Path('/tmp/returns-native-repeat.json').write_text(json.dumps(result,default=str))
    return result
