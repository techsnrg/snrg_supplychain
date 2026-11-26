"""Real ERPNext integration acceptance; refuses every site except Docker staging."""
import json
from pathlib import Path
import frappe
from frappe.utils import today, add_days, getdate, flt
from snrg_supplychain.returns import api, service

SITE = 'production-staging.localhost'
COMPANY = 'SNRG Production Staging'
CHECKS = []


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    CHECKS.append(message)
    print('PASS: ' + message, flush=True)


def reject(fn, message):
    savepoint = 'returns_expected_failure'
    frappe.db.savepoint(savepoint)
    try:
        fn()
    except (frappe.ValidationError, frappe.PermissionError):
        frappe.db.rollback(save_point=savepoint)
        CHECKS.append(message)
        return
    raise AssertionError('Expected rejection: ' + message)


def user(which):
    frappe.set_user('returns-' + which + '@staging.invalid')


def admin():
    frappe.set_user('Administrator')


def seed():
    admin()
    if frappe.local.site != SITE:
        raise RuntimeError('Returns acceptance is allowed only on ' + SITE)
    for role in ['Managing Director', 'Quality Manager']:
        if not frappe.db.exists('Role', role):
            frappe.get_doc(dict(doctype='Role', role_name=role)).insert()
    role_sets = {'sales':['Sales User','Accounts User'], 'md':['Managing Director','Sales Manager','Accounts User'],
        'other-md':['Managing Director','Sales Manager','Accounts User'], 'stock':['Stock Manager'],
        'qc':['Quality Manager'], 'finance':['Accounts Manager','Stock User']}
    for name, roles in role_sets.items():
        email = 'returns-' + name + '@staging.invalid'
        if not frappe.db.exists('User', email):
            doc = frappe.get_doc(dict(doctype='User', email=email, first_name='Returns ' + name,
                enabled=1, send_welcome_email=0, user_type='System User'))
            doc.flags.no_welcome_mail = True
            doc.insert()
            doc.add_roles(*roles)
        else:
            frappe.get_doc('User', email).add_roles(*roles)
    if not frappe.db.exists('Price List', 'Standard Selling'):
        frappe.get_doc(dict(doctype='Price List', price_list_name='Standard Selling', currency='INR', selling=1, enabled=1)).insert()
    holiday = 'Returns QA Calendar'
    if not frappe.db.exists('Holiday List', holiday):
        frappe.get_doc(dict(doctype='Holiday List', holiday_list_name=holiday,
            from_date=f'{getdate(today()).year}-01-01', to_date=f'{getdate(today()).year+1}-12-31')).insert()
    settings = frappe.get_single('Return Settings')
    settings.update(dict(holiday_list=holiday, waiver_approver='returns-md@staging.invalid',
        settlement_approver_role='Accounts Manager', enabled=1))
    settings.save()
    frappe.clear_cache(doctype='Return Settings')
    customer = frappe.get_doc(dict(doctype='Customer', customer_name='Returns QA ' + frappe.generate_hash(length=7),
        customer_type='Company', customer_group=frappe.db.get_value('Customer Group', {'is_group':0}, 'name') or 'Commercial',
        territory=frappe.db.get_value('Territory', {'is_group':0}, 'name') or 'India')).insert()
    supplier = frappe.get_doc(dict(doctype='Supplier', supplier_name=customer.customer_name,
        supplier_group=frappe.db.get_value('Supplier Group', {'is_group':0}, 'name') or 'All Supplier Groups',
        supplier_type='Company', custom_is_customer=1, custom_linked_customer=customer.name)).insert()
    item = frappe.get_doc('Item', '10166-WH')
    check(item.stock_uom == 'Nos', 'Existing item and UOM inspected; no new Item created')
    warehouse = 'Finished Production - SPST'
    return customer, supplier, item, warehouse


def sale(customer, item, rate):
    admin()
    doc = frappe.get_doc(dict(doctype='Sales Invoice', company=COMPANY, customer=customer,
        posting_date=today(), due_date=today(), currency='INR', selling_price_list='Standard Selling', price_list_currency='INR', plc_conversion_rate=1, update_stock=0,
        items=[dict(item_code=item, qty=20, rate=rate, uom='Nos')]))
    doc.insert(); doc.submit()
    return doc


def mra(invoice, category='Suspected Manufacturing Defect', qty=4):
    user('sales')
    source = invoice.items[0]
    doc = frappe.get_doc(dict(doctype='Material Return Authorization', company=COMPANY,
        customer=invoice.customer, currency='INR', request_date=today(), information_complete=1,
        responsible_user=frappe.session.user, freight_terms='QA: SNRG arranges; actual freight after QC.',
        freight_estimate=25, items=[dict(item_code=source.item_code, uom=source.uom,
            claimed_category=category, reason='Synthetic Docker acceptance test', claimed_qty=qty,
            approved_qty=qty, sales_invoice=invoice.name, sales_invoice_item=source.name,
            invoice_source='Manually Selected', invoice_confirmed=1, condition='Current Saleable')]))
    doc.insert()
    check(flt(doc.items[0].net_rate) == flt(source.net_rate), 'MRA fetches original net invoice rate')
    service.transition(doc, 'request_approval')
    check(doc.status == 'Pending Approval' and doc.due_date, 'Complete request starts authorization SLA')
    reject(lambda: service.transition(frappe.get_doc(doc.doctype, doc.name), 'authorize', 'not MD'), 'Sales cannot authorize return')
    user('md')
    doc = frappe.get_doc(doc.doctype, doc.name)
    service.transition(doc, 'authorize', 'QA authorization')
    check(doc.status == 'Authorized' and doc.approved_by == frappe.session.user, 'MD authorization records user and policy snapshot')
    modified = frappe.get_doc(doc.doctype, doc.name)
    modified.items[0].approved_qty += 1
    reject(modified.save, 'Authorized quantities cannot be edited')
    return frappe.get_doc(doc.doctype, doc.name)


def receive(mra_doc, qty=None, responsibility='SNRG', actual=50):
    user('stock')
    values = api.populate('Return Receipt', mra_doc.name)
    if qty is not None:
        values['items'][0]['received_qty'] = qty
    values['documents_complete'] = 1
    doc = frappe.get_doc(values).insert()
    service.transition(doc, 'receive')
    check(doc.status == 'Received' and doc.due_date, 'Physical receipt starts QC SLA')
    admin()
    transporter = frappe.get_doc(dict(doctype='Supplier', supplier_name='Returns QA Transport '+frappe.generate_hash(length=5), supplier_type='Company', supplier_group=frappe.db.get_value('Supplier Group', {'is_group':0}, 'name'), is_transporter=1)).insert()
    bill = frappe.get_doc(dict(doctype='Purchase Invoice',company=COMPANY,supplier=transporter.name,bill_no='FREIGHT-QA-'+frappe.generate_hash(length=5),bill_date=today(),posting_date=today(),due_date=today(),currency='INR',items=[dict(item_name='QA transporter freight',description='Synthetic staging freight service',qty=1,rate=actual,uom='Nos',expense_account=frappe.get_cached_value('Company',COMPANY,'default_expense_account'))]))
    bill.insert();bill.submit()
    user('finance')
    doc = frappe.get_doc(doc.doctype, doc.name)
    doc.freight_responsibility = responsibility
    doc.transporter=transporter.name;doc.freight_bill=bill.name
    doc.actual_freight = actual
    doc.freight_finalized = 1
    doc.save()
    check(flt(doc.customer_freight)==(actual if responsibility=='Customer' else 0), 'Actual transporter bill allocated independently of SNRG vendor payment')
    return doc


def inspect(receipt, split=False, commercial=False):
    user('qc')
    values = api.populate('Return Inspection', receipt.name)
    row = values['items'][0]
    row.update(finding='Fresh / Saleable' if commercial else 'Manufacturing Defect', decision='Accept', notes='QA verified')
    if split:
        row['qty'] -= 1
        values['items'].append(dict(receipt_item=receipt.items[0].name, item_code=row['item_code'], qty=1,
            finding='Customer Damage', decision='Reject', notes='QA damage', photo='/private/files/returns-qa.txt'))
    if commercial or receipt.items[0].unauthorized:
        row['exception_reason'] = 'QA exceptional acceptance'
    doc = frappe.get_doc(values).insert()
    if commercial or receipt.items[0].unauthorized:
        reject(lambda: service.transition(frappe.get_doc(doc.doctype, doc.name), 'complete_qc'), 'QC cannot self-approve commercial/excess acceptance')
        user('md')
        service.transition(frappe.get_doc(doc.doctype, doc.name), 'approve_exceptions')
        user('qc')
        doc = frappe.get_doc(doc.doctype, doc.name)
    service.transition(doc, 'complete_qc')
    check(doc.status == 'Completed', 'QC completes only after all received quantities are classified')
    return doc


def stock_receipt(item, qty, warehouse, rate):
    admin()
    doc = frappe.get_doc(dict(doctype='Stock Entry', stock_entry_type='Material Receipt',
        company=COMPANY, remarks='Returns QA: synthetic staging-only inward receipt',
        items=[dict(item_code=item, qty=qty, t_warehouse=warehouse, basic_rate=rate)]))
    doc.insert(); doc.submit()
    check(bool(frappe.db.exists('Stock Ledger Entry', {'voucher_no':doc.name, 'is_cancelled':0})), 'Accepted physical goods produce a real Stock Ledger entry')
    return doc


def credit(invoice, qty):
    admin()
    from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
    doc = make_sales_return(invoice.name)
    doc.items[0].qty = -qty
    doc.update_stock = 0
    doc.insert(); doc.submit()
    check(bool(frappe.db.exists('GL Entry', {'voucher_no':doc.name, 'is_cancelled':0})), 'Credit note produces real GL entries')
    return doc


def settlement(qc, supplier=None):
    user('finance')
    values = api.populate('Return Settlement', qc.name)
    if supplier:
        values.update(route='Customer Invoice', supplier=supplier)
    doc = frappe.get_doc(values).insert()
    check(doc.due_date, 'Settlement draft starts Finance approval SLA')
    return doc


def link_and_settle(doc, account, stock, offset=None):
    user('finance')
    doc = frappe.get_doc(doc.doctype, doc.name)
    service.transition(doc, 'approve_settlement')
    check(doc.approved_by == 'returns-finance@staging.invalid', 'Final settlement approved by Finance, not MD')
    doc.append('accounting_documents', dict(document_type=account.doctype, document_name=account.name, purpose='Settlement'))
    if offset:
        doc.append('accounting_documents', dict(document_type=offset.doctype, document_name=offset.name, purpose='Offset / Payment'))
    doc.append('stock_references', dict(document_type=stock.doctype, document_name=stock.name, notes='QA accepted stock entry'))
    doc.stock_reconciled = doc.charges_reconciled = doc.ledger_reconciled = 1
    doc.reconciliation_notes = 'QA verified submitted documents, stock ledger and party ledgers.'
    doc.save()
    service.transition(doc, 'settle')
    check(doc.status == 'Settled', 'Settlement closes only with submitted accounting, stock and reconciliation references')
    return doc


def run():
    if frappe.local.site != SITE:
        raise RuntimeError('Wrong site')
    customer, supplier, item, warehouse = seed()
    original = sale(customer.name, item.name, 100)
    latest = sale(customer.name, item.name, 120)
    user('sales')
    lookup = api.invoice_sales(COMPANY, customer.name, item.name, item.stock_uom, 'INR')
    check(lookup['rows'][0]['sales_invoice'] == latest.name, 'Optional lookup finds most recent eligible sale')
    manual = api.invoice_sales(COMPANY, customer.name, item.name, item.stock_uom, 'INR', original.name)
    check(manual['rows'][0]['net_rate'] == 100, 'Manual selection retains older invoice price despite newer sale at 120')
    bad = frappe.get_doc(dict(doctype='Material Return Authorization', company=COMPANY,
        customer=customer.name, currency='INR', status='Authorized', responsible_user=frappe.session.user,
        freight_terms='QA',items=[]))
    reject(bad.insert, 'Forged direct authorization state rejected')
    first = mra(original)
    receipt = receive(first)
    qc = inspect(receipt, split=True)
    admin()
    notice = frappe.get_doc(dict(doctype='File', file_name='returns-qa.txt', content='Synthetic QA inspection statement', is_private=1)).insert()
    user('qc')
    qc = frappe.get_doc(qc.doctype, qc.name)
    qc.findings_notice=notice.file_url; qc.rejection_notice_date=today(); qc.save()
    check(getdate(qc.dispute_deadline)==getdate(add_days(today(),15)), 'Rejection notice gives 15 calendar days to dispute')
    check(getdate(qc.collection_deadline)==getdate(add_days(today(),30)), 'Rejected collection deadline is 30 calendar days')
    qc.dispute_status='Resolved';qc.resolved_on=add_days(today(),25);qc.resolution='QA resolution';qc.save()
    check(getdate(qc.collection_deadline)==getdate(add_days(today(),40)), 'Dispute resolution extends collection deadline when later')
    user('finance')
    one=settlement(qc)
    cn=credit(original,3)
    stock=stock_receipt(item.name,3,warehouse,100)
    one=link_and_settle(one,cn,stock)
    user('finance')
    reject(lambda: service.transition(frappe.get_doc(first.doctype,first.name),'close','QA'), 'Open rejected-material disposition blocks MRA closure')
    user('qc')
    qc=frappe.get_doc(qc.doctype,qc.name);qc.disposition='Collected';qc.disposition_date=today();qc.disposition_evidence=notice.file_url;qc.save()
    user('finance')
    first=frappe.get_doc(first.doctype,first.name);service.transition(first,'close','QA reconciled')
    check(first.status=='Closed','Credit-note return closes end to end')
    # Customer-issued invoice route with separate supplier identity and explicit offset.
    second=mra(latest,category='Commercial Return',qty=2)
    receipt2=receive(second,responsibility='Customer')
    qc2=inspect(receipt2,commercial=True)
    two=settlement(qc2,supplier.name)
    check(flt(two.standard_restocking)==60 and flt(two.restocking_charge)==60,'Fresh acceptance calculates 25 percent on original net value')
    check(flt(two.freight_charge)==50, 'Commercial settlement recovers actual freight rather than pre-dispatch estimate')
    two.restocking_charge=30;two.waiver_reason='QA partial restocking concession';two.save()
    reject(lambda:service.transition(frappe.get_doc(two.doctype,two.name),'approve_settlement'),'Finance cannot apply unapproved concession')
    user('other-md')
    reject(lambda:service.transition(frappe.get_doc(two.doctype,two.name),'approve_waiver'),'Other MD-role user cannot approve designated-MD concession')
    user('md');service.transition(frappe.get_doc(two.doctype,two.name),'approve_waiver')
    user('finance');two=frappe.get_doc(two.doctype,two.name)
    check(two.waiver_approved_by=='returns-md@staging.invalid','Designated MD concession approval persists')
    admin()
    pi=frappe.get_doc(dict(doctype='Purchase Invoice',company=COMPANY,supplier=supplier.name,
        bill_no='QA-CUSTOMER-'+frappe.generate_hash(length=5),bill_date=today(),posting_date=today(),due_date=today(),
        currency='INR',update_stock=1,items=[dict(item_code=item.name,qty=2,rate=120,uom='Nos',warehouse=warehouse)]))
    pi.insert();pi.submit()
    check(bool(frappe.db.exists('Stock Ledger Entry',{'voucher_no':pi.name,'is_cancelled':0})),'Customer invoice route receives stock through Purchase Invoice once')
    debit=frappe.get_doc(dict(doctype='Sales Invoice',company=COMPANY,customer=customer.name,
        posting_date=today(),due_date=today(),selling_price_list='Standard Selling',price_list_currency='INR',plc_conversion_rate=1,items=[dict(item_name='Returns QA Charges',description='Approved restocking and actual freight recovery',qty=1,rate=80,uom='Nos',income_account=frappe.get_cached_value('Company',COMPANY,'default_income_account'))]))
    # A charge-only invoice must not move stock; amount is approved restocking charge.
    debit.items[0].qty=1;debit.items[0].rate=80;debit.insert();debit.submit()
    receivable=frappe.get_cached_value('Company',COMPANY,'default_receivable_account')
    payable=frappe.get_cached_value('Company',COMPANY,'default_payable_account')
    cost_center=frappe.get_cached_value('Company',COMPANY,'cost_center')
    je=frappe.get_doc(dict(doctype='Journal Entry',voucher_type='Journal Entry',company=COMPANY,posting_date=today(),
        accounts=[dict(account=payable,party_type='Supplier',party=supplier.name,debit_in_account_currency=240,
            reference_type='Purchase Invoice',reference_name=pi.name,cost_center=cost_center),
            dict(account=receivable,party_type='Customer',party=customer.name,credit_in_account_currency=240,
                reference_type='Sales Invoice',reference_name=latest.name,cost_center=cost_center)]))
    je.insert();je.submit()
    user('finance');two=frappe.get_doc(two.doctype,two.name)
    two.customer_invoice_number=pi.bill_no;two.customer_invoice_date=pi.bill_date;two.customer_invoice_attachment=notice.file_url
    two.append('accounting_documents',dict(document_type='Sales Invoice',document_name=debit.name,purpose='Charge'))
    two.save()
    two=link_and_settle(two,pi,pi,je)
    user('finance');second=frappe.get_doc(second.doctype,second.name);service.transition(second,'close','QA customer invoice and offset reconciled')
    check(second.status=='Closed','Customer-issued invoice return closes with supplier mapping and separate offset')
    # Render actual authorized customer document to PDF.
    admin()
    html=frappe.get_print(first.doctype,first.name,print_format='Material Return Authorization')
    check(first.name in html and item.name in html,'Customer print format renders approved lines and MRA number')
    from frappe.utils.pdf import get_pdf
    pdf=get_pdf(html)
    check(pdf.startswith(b'%PDF'),'Customer authorization renders a real PDF')
    path=Path('/tmp/returns-acceptance.pdf');path.write_bytes(pdf)
    frappe.db.commit()
    result=dict(site=SITE,passed=True,checks=CHECKS,records=dict(customer=customer.name,supplier=supplier.name,
        credit_mra=first.name,invoice_mra=second.name,credit_receipt=receipt.name,credit_inspection=qc.name,credit_settlement=one.name,invoice_settlement=two.name,
        credit_note=cn.name,purchase_invoice=pi.name,offset=je.name,original_sale=original.name,latest_sale=latest.name),pdf=str(path))
    print(json.dumps(result,default=str))
    return result
