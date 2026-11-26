"""Commercial guards around native Workflow, Quality Inspection and stock/accounts.

This module does not own a state-transition engine or post ledger entries.
"""
import hashlib
import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, today, flt

from .legacy_service import (MD, SALES, STOCK, QC, FINANCE, canonical, due, immutable,
    matching_parent, positive, read_doc, remaining, require_roles, settings, validate_invoice)
from .policy import freight_split, money, number, rejection_deadlines

ACTIVE_CUSTODY_STATES = ('Authorized', 'Exceptions Approved', 'Finance Review', 'Pending Concession', 'Concession Approved')
SIGNED_STATES = ('Settlement Approved', 'Settled', 'Closed')
AUTH_FIELDS = ('company', 'customer', 'currency', 'request_date', 'items', 'policy_snapshot',
    'freight_estimate', 'freight_terms', 'approval_reason', 'revision_of', 'category_summary', 'claimed_value', 'approved_value')
FINANCE_FIELDS = ('route', 'supplier', 'settlement_items', 'restocking_charge', 'handling_charge',
    'waiver_amount', 'waiver_reason', 'return_warehouse')
REFERENCE_FIELDS = ('accounting_documents', 'stock_references', 'stock_reconciled',
    'charges_reconciled', 'ledger_reconciled', 'reconciliation_notes', 'difference_reason',
    'customer_invoice_number', 'customer_invoice_date', 'customer_invoice_attachment')
STAMPS = ('approved_by', 'approved_on', 'waiver_approved_by', 'waiver_approved_on',
    'waiver_fingerprint', 'exception_approved_by', 'exception_approved_on', 'exception_fingerprint',
    'settlement_approved_by', 'settlement_approved_on', 'settlement_fingerprint', 'designated_md_user',
    'native_migration_complete', 'legacy_migrated', 'legacy_review_required', 'legacy_inspections', 'legacy_settlements')


def state(doc):
    return doc.get('workflow_state') or doc.get('status') or 'Draft'


def changed(doc, old, fields):
    return old and any(canonical(doc.get(k)) != canonical(old.get(k)) for k in fields)


def digest(value):
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, default=str).encode()).hexdigest()


def legacy_read_only(doc, method=None):
    frappe.throw(_('Legacy return records are read-only. Use the linked MRA and native Quality Inspection.'))


def delay_guard(doc):
    if doc.get('revised_due_date') and not doc.get('delay_reason'):
        frappe.throw(_('Record a reason for the revised deadline.'))


def preserve_stamps(doc, old, names=STAMPS):
    if old:
        immutable(doc, old, names)
    elif any(doc.get(k) for k in names):
        frappe.throw(_('Approval and migration fields are server controlled.'))


def require_finance_approver():
    require_roles(settings().settlement_approver_role)
    if frappe.session.user == settings().waiver_approver:
        frappe.throw(_('Final settlement approval is delegated to Finance, not the designated MD.'))


def valid_authorization(doc):
    if not doc.approved_by or state(doc) in ('Draft', 'Pending Approval', 'Rejected', 'Legacy Review'):
        frappe.throw(_('An MD-authorized MRA is required.'))


def validate_mra(doc):
    config = settings()
    old = doc.get_doc_before_save()
    before, after = state(old) if old else 'Draft', state(doc)
    preserve_stamps(doc, old)
    if old:immutable(doc,old,('native_returns_version',))
    delay_guard(doc)
    if not old:
        require_roles(*SALES)
        if after != 'Draft':
            frappe.throw(_('New MRAs must start in Draft.'))
        doc.native_returns_version = 3
        doc.native_migration_complete = 1
    elif old.approved_by:
        immutable(doc, old, AUTH_FIELDS)
    if old and before == 'Closed' and after == 'Closed':
        immutable(doc, old, (*AUTH_FIELDS, *FINANCE_FIELDS, *REFERENCE_FIELDS, 'exception_reason', 'closure_reason'))
    if changed(doc, old, FINANCE_FIELDS + REFERENCE_FIELDS):
        require_roles(*FINANCE, config.settlement_approver_role)
        if before in SIGNED_STATES and changed(doc, old, FINANCE_FIELDS):
            frappe.throw(_('Revise the settlement through Workflow before changing approved amounts.'))
    if old and before == 'Draft' and after == 'Draft':
        require_roles(*SALES)
    if old and before == 'Pending Approval' and after == 'Pending Approval':
        require_roles(MD)
    if not old or not old.approved_by:
        calculate_authorization(doc)
    doc.designated_md_user = config.waiver_approver
    context = qc_context(doc)
    if old and int(doc.get('native_returns_version') or 0)>=3 and context['receipts']:
        immutable(doc,old,('route','supplier','return_warehouse'))
    fp = exception_digest(context)
    doc.has_return_exceptions = int(bool(context['exceptions']))
    doc.exceptions_approved = int(not context['exceptions'] or doc.exception_fingerprint == fp)
    if doc.settlement_items:
        calculate_settlement(doc, context)
    if before != after:
        # Frappe validates role/condition/transition using the active Workflow.
        # The checks here are commercial invariants and server-generated audit fields.
        if after == 'Pending Approval':
            if not doc.information_complete:
                frappe.throw(_('Mark request information complete.'))
            doc.complete_on = today()
            doc.due_date = due(today(), 'authorization_days')
        elif after == 'Authorized' and not doc.approved_by:
            require_roles(MD)
            if not doc.approval_reason:
                frappe.throw(_('Record the authorization reason.'))
            if not any(flt(x.approved_qty) > 0 for x in doc.items):
                frappe.throw(_('Approve at least one quantity.'))
            for row in doc.items:
                if flt(row.approved_qty) and (not row.sales_invoice or not row.invoice_confirmed):
                    frappe.throw(_('Confirm original-invoice valuation; no untraceable-price policy is configured.'))
                if flt(row.approved_qty) and row.claimed_category == 'Commercial Return' and row.condition != 'Current Saleable' and not row.exception_reason:
                    frappe.throw(_('Explain the commercial-condition exception.'))
            doc.policy_snapshot = config.policy_terms
            doc.approved_by, doc.approved_on = frappe.session.user, now_datetime()
            doc.due_date = None
        elif after == 'Rejected':
            require_roles(MD)
            if not doc.approval_reason:
                frappe.throw(_('Record the rejection reason.'))
        elif after == 'Exceptions Approved':
            require_roles(MD)
            require_complete_qc(context)
            if not doc.exception_reason:
                frappe.throw(_('Record the commercial acceptance exception reason.'))
            doc.exception_fingerprint = fp
            doc.exception_approved_by, doc.exception_approved_on = frappe.session.user, now_datetime()
            doc.exceptions_approved = 1
        elif after == 'Finance Review':
            require_roles(*FINANCE, config.settlement_approver_role)
            valid_authorization(doc)
            require_complete_qc(context)
            if context['exceptions'] and doc.exception_fingerprint != fp:
                frappe.throw(_('Obtain MD approval for commercial/unauthorized acceptance first.'))
            load_settlement_lines(doc, context)
            calculate_settlement(doc, context)
            doc.due_date = due(today(), 'settlement_days')
            doc.settlement_approved_by = doc.settlement_approved_on = doc.settlement_fingerprint = None
            if before == 'Legacy Review':
                if not doc.get('legacy_review_notes'):
                    frappe.throw(_('Record the legacy reconciliation review.'))
                doc.legacy_review_required = 0
        elif after == 'Pending Concession':
            if not doc.concession_required or not doc.waiver_reason:
                frappe.throw(_('Enter the requested concession and its reason.'))
        elif after == 'Concession Approved':
            require_roles(MD)
            if frappe.session.user != config.waiver_approver:
                frappe.throw(_('Only the designated Managing Director may approve concessions.'))
            if not doc.concession_required or not doc.waiver_reason:
                frappe.throw(_('A concession amount and reason are required.'))
            doc.waiver_fingerprint = concession_digest(doc)
            doc.waiver_approved_by, doc.waiver_approved_on = frappe.session.user, now_datetime()
        elif after == 'Settlement Approved':
            require_finance_approver()
            require_complete_qc(context)
            calculate_settlement(doc, context)
            if doc.has_return_exceptions and not doc.exceptions_approved:
                frappe.throw(_('Accepted exceptions have changed; obtain MD approval again.'))
            if doc.concession_required and doc.waiver_fingerprint != concession_digest(doc):
                frappe.throw(_('Obtain designated-MD concession approval for these exact amounts.'))
            doc.settlement_approved_by, doc.settlement_approved_on = frappe.session.user, now_datetime()
            doc.settlement_fingerprint = settlement_digest(doc)
            doc.due_date = due(today(), 'document_days')
        elif after == 'Settled':
            require_finance_approver()
            verify_accounting(doc)
            doc.due_date = None
        elif after == 'Closed':
            require_finance_approver()
            verify_closure(doc, context)
            doc.due_date = None
    if after in SIGNED_STATES and doc.settlement_items:
        if doc.settlement_fingerprint != settlement_digest(doc):
            frappe.throw(_('Approved settlement valuation/evidence changed. Revise through Workflow.'))
    doc.concession_approved = int(not doc.concession_required or doc.waiver_fingerprint == concession_digest(doc))
    doc.status = after
    if before == after and old and doc.concession_required and doc.waiver_fingerprint != concession_digest(doc):
        doc.waiver_approved_by = doc.waiver_approved_on = doc.waiver_fingerprint = None


def calculate_authorization(doc):
    if not doc.items:
        frappe.throw(_('At least one requested item is required.'))
    categories, claimed, approved = set(), 0, 0
    for row in doc.items:
        positive(row.claimed_qty)
        if number(row.approved_qty) > number(row.claimed_qty):
            frappe.throw(_('Approved quantity exceeds the claim.'))
        categories.add(row.claimed_category)
        if row.sales_invoice:
            invoice = read_doc('Sales Invoice', row.sales_invoice)
            validate_invoice(invoice, doc.company, doc.customer, doc.currency)
            line = next((x for x in invoice.items if x.name == row.sales_invoice_item), None)
            if not line or line.item_code != row.item_code or line.uom != row.uom or flt(line.qty) <= 0:
                frappe.throw(_('Select a matching original invoice item and UOM.'))
            row.net_rate, row.invoice_date = line.net_rate, invoice.posting_date
            row.remaining_qty = remaining(invoice, line)
        else:
            row.net_rate, row.invoice_date, row.sales_invoice_item, row.invoice_source, row.invoice_confirmed = 0, None, None, None, 0
        claimed += flt(row.claimed_qty) * flt(row.net_rate)
        approved += flt(row.approved_qty) * flt(row.net_rate)
    doc.category_summary = next(iter(categories)) if len(categories) == 1 else 'Mixed'
    doc.claimed_value, doc.approved_value = claimed, approved
    number(doc.freight_estimate)
    if doc.revision_of:
        prior = read_doc(doc.doctype, doc.revision_of)
        matching_parent(doc, prior)
        valid_authorization(prior)


def validate_receipt(doc):
    old = doc.get_doc_before_save()
    before, after = state(old) if old else 'Draft', state(doc)
    require_roles(*STOCK, *FINANCE, MD)
    delay_guard(doc)
    preserve_stamps(doc, old, ('complete_on', 'disposal_approved_by', 'disposal_approved_on', 'quality_complete'))
    mra = read_doc('Material Return Authorization', doc.authorization)
    if int(mra.get('native_returns_version') or 0) >= 3:
        frappe.throw(_('Custom custody receipts are retired for new cases. Record a native stock arrival.'))
    matching_parent(doc, mra)
    valid_authorization(mra)
    if not old and (after != 'Draft' or state(mra) not in ACTIVE_CUSTODY_STATES):
        frappe.throw(_('New custody receipts require an active authorized MRA.'))
    if frappe.db.exists('Material Return Authorization', {'revision_of':mra.name, 'approved_by':['is','set']}):
        frappe.throw(_('Use the latest authorized MRA revision.'))
    if old and before != 'Draft':
        # Native QI updates only its own link on the custody row, never the physical count.
        immutable(doc, old, ('authorization','company','customer','currency','received_on'))
        for row in doc.items:
            prior = next((x for x in old.items if x.name == row.name), None)
            if not prior:
                frappe.throw(_('Received custody rows are frozen.'))
            immutable(row, prior, ('mra_item','item_code','uom','received_qty','unauthorized','unauthorized_qty','batch_no','serial_no'))
        if len(doc.items) != len(old.items):
            frappe.throw(_('Received custody rows are frozen.'))
    if not doc.items:
        frappe.throw(_('Record actual received material.'))
    if not old or before == 'Draft':
        sources = {x.name:x for x in mra.items}
        prior = dict(frappe.db.sql('''select i.mra_item, sum(i.received_qty) from `tabReturn Receipt Item` i
            join `tabReturn Receipt` p on p.name=i.parent where p.authorization=%s and p.status!='Draft'
            and p.name!=%s group by i.mra_item''', (mra.name, doc.name)))
        running = defaultdict(float)
        for row in doc.items:
            positive(row.received_qty)
            source = sources.get(row.mra_item)
            matches = source and source.item_code == row.item_code and source.uom == row.uom
            available = max(0, flt(source.approved_qty)-flt(prior.get(row.mra_item))-running[row.mra_item]) if matches else 0
            row.unauthorized_qty = max(0, flt(row.received_qty)-available)
            row.unauthorized = int(row.unauthorized_qty > 0)
            running[row.mra_item] += flt(row.received_qty)
    finance_fields = ('actual_freight','customer_freight','freight_bill','freight_finalized','freight_responsibility','allocation_reason')
    finance_changed = changed(doc, old, finance_fields) or (not old and doc.freight_finalized)
    if finance_changed:
        require_roles(*FINANCE)
    if state(mra) in SIGNED_STATES and old:
        immutable(doc, old, (*finance_fields, 'transporter','arranged_by','paid_by','freight_estimate'))
    for key in ('actual_freight','customer_freight','freight_estimate'):
        number(doc.get(key))
    if doc.freight_finalized:
        doc.customer_freight = float(freight_split(doc.actual_freight, doc.freight_responsibility, doc.customer_freight))
        if doc.freight_responsibility == 'Shared' and not doc.allocation_reason:
            frappe.throw(_('Explain shared-freight allocation.'))
        if doc.paid_by == 'SNRG' and flt(doc.actual_freight) and not doc.freight_bill:
            frappe.throw(_('Link the submitted actual transporter bill.'))
        if doc.freight_bill and finance_changed:
            bill = read_doc('Purchase Invoice', doc.freight_bill)
            if bill.docstatus != 1 or bill.is_return or (bill.company,bill.supplier,bill.currency)!=(doc.company,doc.transporter,doc.currency):
                frappe.throw(_('Freight bill must match transporter, company and currency.'))
            if flt(doc.actual_freight) > flt(bill.grand_total)+0.01:
                frappe.throw(_('Allocated actual freight cannot exceed the linked bill.'))
    if before != after:
        if after == 'Received' and before == 'Draft':
            require_roles(*STOCK)
        elif after == 'Disposal Approved':
            require_roles(MD)
            if not doc.customer_disposal_instruction:
                frappe.throw(_('Attach written customer disposal instructions.'))
            doc.disposal_approved_by, doc.disposal_approved_on = frappe.session.user, now_datetime()
    if after != 'Draft' and doc.documents_complete and not doc.complete_on:
        doc.complete_on, doc.due_date = today(), due(today(), 'inspection_days')
    if doc.dispute_status == 'Resolved' and (not doc.resolved_on or not doc.resolution):
        frappe.throw(_('Record dispute resolution and date.'))
    if doc.rejection_notice_date:
        if not doc.findings_notice:
            frappe.throw(_('Attach the rejection notice shared with the customer.'))
        doc.dispute_deadline, doc.collection_deadline = rejection_deadlines(doc.rejection_notice_date,
            doc.resolved_on if doc.dispute_status == 'Resolved' else None)
    else:
        doc.dispute_deadline = doc.collection_deadline = None
    if doc.disposition == 'Disposed' and (not doc.disposal_approved_by or not doc.customer_disposal_instruction):
        frappe.throw(_('Written customer instructions and MD disposal approval are required.'))
    if doc.disposition != 'Pending' and (not doc.disposition_date or not doc.disposition_evidence):
        frappe.throw(_('Record disposition date and evidence.'))
    doc.status = after


def is_return_qi(doc):
    return doc.get('reference_type') == 'Return Receipt' or bool(doc.get('custom_return_mra'))


def validate_quality_inspection(doc, method=None):
    if doc.get('reference_type') in ('Delivery Note','Purchase Receipt','Stock Entry') and doc.get('reference_name'):
        from .stock_first import is_arrival, validate_qi
        if is_arrival(frappe.get_doc(doc.reference_type, doc.reference_name)):
            return validate_qi(doc)
    if not is_return_qi(doc):
        if doc.get('custom_return_mra') or doc.get('custom_return_receipt') or doc.get('custom_return_allocations'):
            frappe.throw(_('Return QC fields apply only to a Return Receipt reference.'))
        return
    require_roles(*QC)
    receipt = read_doc('Return Receipt', doc.reference_name)
    if state(receipt) not in ('Received','Disposal Approved') or not receipt.documents_complete:
        frappe.throw(_('Complete the physical custody receipt and its documents before QC.'))
    mra = read_doc('Material Return Authorization', receipt.authorization)
    if state(mra) not in ('Authorized','Exceptions Approved') and not doc.flags.get('returns_migration'):
        frappe.throw(_('Revise the MRA back to receipt/QC through Workflow before changing QC.'))
    source_id = doc.get('child_row_reference') or doc.get('custom_return_receipt_item')
    source = next((x for x in receipt.items if x.name == source_id), None)
    if not source or source.item_code != doc.item_code:
        frappe.throw(_('QC must identify the exact received item row.'))
    existing = frappe.db.get_value('Quality Inspection', {'reference_type':'Return Receipt',
        'reference_name':receipt.name,'child_row_reference':source.name,'docstatus':['<',2],'name':['!=',doc.name]}, 'name')
    if existing:
        frappe.throw(_('Use the existing active native inspection for this custody row.'))
    doc.custom_return_mra, doc.custom_return_receipt = mra.name, receipt.name
    doc.custom_return_receipt_item, doc.child_row_reference = source.name, source.name
    doc.company = receipt.company
    if doc.batch_no and doc.batch_no != source.batch_no:
        frappe.throw(_('QC batch must match custody evidence.'))
    if not doc.get('custom_return_allocations'):
        frappe.throw(_('Classify the received quantity into commercial dispositions.'))
    total = 0
    for allocation in doc.custom_return_allocations:
        positive(allocation.qty)
        total += flt(allocation.qty)
        if allocation.decision == 'Accept' and (source.unauthorized or allocation.finding in ('Fresh / Saleable','Customer Damage','Unsellable')) and not allocation.exception_reason:
            frappe.throw(_('Explain proposed exceptional acceptance for MD review.'))
    if total > flt(source.received_qty)+0.000001 or (doc.docstatus == 1 and abs(total-flt(source.received_qty))>0.000001):
        frappe.throw(_('QC disposition quantities must reconcile to the custody count.'))
    # Product-test Accepted/Rejected remains entirely native. It does not decide credit eligibility.


def quality_updated(doc, method=None):
    if not is_return_qi(doc):
        return
    if doc.reference_type != 'Return Receipt':
        parent=frappe.get_doc(doc.reference_type,doc.reference_name)
        complete=all(frappe.db.exists('Quality Inspection',dict(reference_type=parent.doctype,reference_name=parent.name,child_row_reference=row.name,docstatus=1)) for row in parent.items)
        frappe.db.set_value(parent.doctype,parent.name,{'custom_return_quality_complete':int(complete),'custom_return_due_date':None if complete else due(today(),'inspection_days')},update_modified=False)
        if complete:
            for rule in frappe.get_all('ToDo',filters={'reference_type':doc.reference_type,'reference_name':doc.reference_name,'status':'Open','description':['like','Inspect return:%']},pluck='name'):
                todo=frappe.get_doc('ToDo',rule);todo.status='Closed';todo.save(ignore_permissions=True)
        return
    receipt = frappe.get_doc('Return Receipt', doc.reference_name)
    complete = all(frappe.db.get_value('Quality Inspection', row.quality_inspection, 'docstatus') == 1
        for row in receipt.items if row.quality_inspection) and all(row.quality_inspection for row in receipt.items)
    frappe.db.set_value('Return Receipt', receipt.name, 'quality_complete', int(bool(complete)), update_modified=False)


def quality_before_cancel(doc, method=None):
    if is_return_qi(doc):
        mra = read_doc('Material Return Authorization', doc.custom_return_mra)
        if state(mra) not in ('Authorized','Exceptions Approved'):
            frappe.throw(_('Revise the MRA to receipt/QC before cancelling linked inspection evidence.'))


def qc_context(mra):
    if int(mra.get('native_returns_version') or 0) >= 3:
        from .stock_first import context
        return context(mra)
    data = dict(receipts=[], inspections=[], allocations=[], exceptions=[], incomplete=[])
    if mra.is_new():
        return data
    names = frappe.get_all('Return Receipt', filters={'authorization':mra.name}, pluck='name')
    for name in names:
        receipt = read_doc('Return Receipt', name)
        data['receipts'].append(receipt)
        if state(receipt) == 'Draft':
            data['incomplete'].append(receipt.name)
        for received in receipt.items:
            if not received.quality_inspection:
                data['incomplete'].append(received.name)
                continue
            qi = read_doc('Quality Inspection', received.quality_inspection)
            if qi.docstatus != 1 or qi.reference_name != receipt.name or qi.child_row_reference != received.name:
                data['incomplete'].append(received.name)
                continue
            data['inspections'].append(qi)
            for allocation in qi.custom_return_allocations:
                entry = dict(qi=qi, allocation=allocation, receipt=receipt, received=received)
                data['allocations'].append(entry)
                if allocation.decision == 'Accept' and (received.unauthorized or allocation.finding in ('Fresh / Saleable','Customer Damage','Unsellable')):
                    data['exceptions'].append(entry)
    return data


def require_complete_qc(context):
    if not context['receipts'] or context['incomplete']:
        frappe.throw(_('Complete native QC for every received item before Finance review.'))


def exception_digest(context):
    return digest([dict(qi=x['qi'].name,row=x['allocation'].name,qty=x['allocation'].qty,
        finding=x['allocation'].finding,reason=x['allocation'].exception_reason,
        receipt=x['receipt'].name,received=x['received'].name) for x in context['exceptions']])


def load_settlement_lines(doc, context):
    doc.set('settlement_items', [])
    for entry in context['allocations']:
        if entry['allocation'].decision == 'Accept':
            doc.append('settlement_items',dict(quality_inspection=entry['qi'].name,
                allocation_row=entry['allocation'].name,receipt=entry['receipt'].name if entry['receipt'].doctype=='Return Receipt' else None,
                native_receipt_type=entry['receipt'].doctype if entry['receipt'].doctype!='Return Receipt' else None,
                native_receipt=entry['receipt'].name if entry['receipt'].doctype!='Return Receipt' else None,
                native_receipt_item=entry['received'].name if entry['receipt'].doctype!='Return Receipt' else None))
    if doc.restocking_charge is None or (not doc.settlement_approved_by and not doc.waiver_reason):
        doc.restocking_charge = sum(flt(x['allocation'].qty)*rate_for(doc,x)*0.25
            for x in context['allocations'] if x['allocation'].decision=='Accept' and x['allocation'].finding=='Fresh / Saleable')


def rate_for(mra, entry):
    received, allocation = entry['received'], entry['allocation']
    source = next((x for x in mra.items if x.name == received.mra_item and x.item_code == received.item_code and x.uom == received.uom), None)
    invoice_name = source.sales_invoice if source else allocation.sales_invoice
    invoice_item = source.sales_invoice_item if source else allocation.sales_invoice_item
    if not invoice_name or not invoice_item:
        frappe.throw(_('Select a verified original invoice for unexpected goods; no fallback price is configured.'))
    invoice = read_doc('Sales Invoice', invoice_name)
    validate_invoice(invoice, mra.company, mra.customer, mra.currency)
    line = next((x for x in invoice.items if x.name == invoice_item), None)
    if not line or (line.item_code,line.uom)!=(received.item_code,received.uom):
        frappe.throw(_('Return valuation must match the original item and UOM.'))
    return flt(source.net_rate if source else line.net_rate)


def calculate_settlement(doc, context):
    lookup = {(x['qi'].name,x['allocation'].name):x for x in context['allocations'] if x['allocation'].decision=='Accept'}
    selected = {(x.quality_inspection,x.allocation_row) for x in doc.settlement_items}
    if selected != set(lookup) or len(selected) != len(doc.settlement_items):
        frappe.throw(_('Finance review must include every currently accepted QC quantity exactly once.'))
    gross = standard = 0
    receipt_names = set()
    for row in doc.settlement_items:
        entry = lookup[(row.quality_inspection,row.allocation_row)]
        row.receipt, row.item_code = (entry['receipt'].name if entry['receipt'].doctype=='Return Receipt' else None), entry['received'].item_code
        row.qty, row.net_rate, row.finding = entry['allocation'].qty, rate_for(doc,entry), entry['allocation'].finding
        row.amount = float(money(number(row.qty)*number(row.net_rate)))
        row.restocking_amount = float(money(number(row.amount)*number(25)/100)) if row.finding=='Fresh / Saleable' else 0
        source = next((x for x in doc.items if x.name == entry['received'].mra_item), None)
        row.sales_invoice = source.sales_invoice if source else entry['allocation'].sales_invoice
        row.sales_invoice_item = source.sales_invoice_item if source else entry['allocation'].sales_invoice_item
        gross += row.amount; standard += row.restocking_amount
        receipt_names.add(entry['receipt'].name)
    freight = 0
    for receipt in context['receipts']:
        if not receipt.freight_finalized:
            frappe.throw(_('Finance must reconcile actual freight for every shipment.'))
        freight += flt(receipt.customer_freight)
    doc.gross_value, doc.standard_restocking, doc.freight_charge = gross, standard, freight
    for key in ('restocking_charge','handling_charge','waiver_amount'):
        number(doc.get(key))
    doc.concession_required = max(0, standard-flt(doc.restocking_charge))+flt(doc.waiver_amount)
    if flt(doc.waiver_amount) > freight+flt(doc.handling_charge)+0.01:
        frappe.throw(_('Freight/handling waiver exceeds those charges.'))
    if doc.concession_required and not doc.waiver_reason:
        frappe.throw(_('Explain the requested concession.'))
    doc.net_value = gross-flt(doc.restocking_charge)-freight-flt(doc.handling_charge)+flt(doc.waiver_amount)
    if doc.route == 'Customer Invoice':
        supplier = read_doc('Supplier', doc.supplier) if doc.supplier else None
        if not supplier or supplier.disabled or not supplier.custom_is_customer or supplier.custom_linked_customer != doc.customer:
            frappe.throw(_('Select an enabled Supplier explicitly linked to this customer.'))
    if doc.return_warehouse:
        warehouse = read_doc('Warehouse', doc.return_warehouse)
        if warehouse.company != doc.company or warehouse.is_group:
            frappe.throw(_('Select this company’s non-group returns warehouse.'))


def concession_digest(doc):
    return digest({k:doc.get(k) for k in ('settlement_items','route','supplier','gross_value',
        'standard_restocking','restocking_charge','freight_charge','handling_charge','waiver_amount','waiver_reason')})


def settlement_digest(doc):
    return digest({k:doc.get(k) for k in (*FINANCE_FIELDS,'gross_value','standard_restocking','freight_charge','net_value','exception_fingerprint','waiver_fingerprint')})


def verify_accounting(doc):
    if doc.settlement_fingerprint != settlement_digest(doc):
        frappe.throw(_('The approved settlement has changed.'))
    if not (doc.stock_reconciled and doc.charges_reconciled and doc.ledger_reconciled and doc.reconciliation_notes):
        frappe.throw(_('Reconcile native stock, charges and both party ledgers before settlement.'))
    billed = charges = 0
    offset = False
    for ref in doc.accounting_documents:
        account = read_doc(ref.document_type,ref.document_name)
        if account.docstatus != 1 or account.company != doc.company:
            frappe.throw(_('Accounting references must be submitted in this company.'))
        if account.get('custom_return_mra') != doc.name and not is_legacy_reference(doc,ref.document_type,ref.document_name):
            frappe.throw(_('Native document must carry this MRA reference.'))
        if ref.purpose == 'Settlement':
            if account.currency != doc.currency:
                frappe.throw(_('Settlement currency must match the MRA.'))
            if doc.route == 'SNRG Credit Note':
                if ref.document_type!='Sales Invoice' or not account.is_return or account.customer!=doc.customer:
                    frappe.throw(_('Link this customer’s native credit note.'))
            else:
                if ref.document_type!='Purchase Invoice' or account.is_return or account.supplier!=doc.supplier:
                    frappe.throw(_('Link the mapped supplier’s native Purchase Invoice.'))
                if account.bill_no!=doc.customer_invoice_number or getdate(account.bill_date)!=getdate(doc.customer_invoice_date):
                    frappe.throw(_('Purchase Invoice must match the customer bill number and date.'))
            billed += abs(flt(account.net_total))
        elif ref.purpose == 'Charge':
            if ref.document_type!='Sales Invoice' or account.is_return or account.customer!=doc.customer or account.update_stock:
                frappe.throw(_('Recovery must be a non-stock charge invoice for this customer.'))
            charges += flt(account.net_total)
        elif ref.purpose == 'Offset / Payment':
            if ref.document_type=='Journal Entry':
                parties={(x.party_type,x.party) for x in account.accounts}
                if ('Customer',doc.customer) not in parties or ('Supplier',doc.supplier) not in parties:
                    frappe.throw(_('Offset must reference both mapped parties.'))
                required={x.document_name for x in doc.accounting_documents if x.purpose=='Settlement'}
                references={x.reference_name for x in account.accounts if x.reference_type=='Purchase Invoice'}
                if doc.route=='Customer Invoice' and not required.intersection(references):
                    frappe.throw(_('Offset must reference the linked Purchase Invoice.'))
            elif ref.document_type=='Payment Entry':
                if account.party_type!='Supplier' or account.party!=doc.supplier:
                    frappe.throw(_('Payment must belong to the mapped supplier.'))
            else:
                frappe.throw(_('Use native Journal Entry or Payment Entry for offset/payment.'))
            offset=True
    doc.accounting_difference=billed-flt(doc.gross_value)
    if abs(doc.accounting_difference)>0.01 and not doc.difference_reason:
        frappe.throw(_('Explain the native invoice versus approved goods-value difference.'))
    if flt(doc.gross_value) and not billed:
        frappe.throw(_('Link the submitted credit note or Purchase Invoice.'))
    expected_charges=flt(doc.restocking_charge)+flt(doc.freight_charge)+flt(doc.handling_charge)-flt(doc.waiver_amount)
    # Netting through a settlement invoice requires an explicit documented reconciliation.
    if abs(charges-expected_charges)>0.01 and not (doc.difference_reason and abs((billed-charges)-flt(doc.net_value))<0.01):
        frappe.throw(_('Posted recovery charges do not reconcile to the approved settlement.'))
    if doc.route=='Customer Invoice' and flt(doc.gross_value) and (not offset or not doc.customer_invoice_attachment):
        frappe.throw(_('Customer-invoice route needs bill evidence and a separate offset/payment reference.'))
    from .native_stock import validate_stock_reconciliation
    validate_stock_reconciliation(doc,qc_context(doc))
    if doc.settlement_items and not doc.stock_references:
        frappe.throw(_('Link the native documents that actually received the accepted stock.'))
    for ref in doc.stock_references:
        stock=read_doc(ref.document_type,ref.document_name)
        if stock.docstatus!=1 or stock.company!=doc.company:
            frappe.throw(_('Stock reference must be submitted in this company.'))
        if stock.get('custom_return_mra')!=doc.name and not is_legacy_reference(doc,ref.document_type,ref.document_name):
            frappe.throw(_('Stock reference must carry this MRA.'))
        if ref.document_type in ('Sales Invoice','Purchase Invoice') and not stock.update_stock:
            frappe.throw(_('Invoice stock reference must update stock.'))


def verify_closure(doc,context=None):
    context=context or qc_context(doc)
    if not context['receipts']:
        if not doc.closure_reason:
            frappe.throw(_('Explain short-closing without receipt.'))
        return
    require_complete_qc(context)
    if int(doc.get('native_returns_version') or 0) >= 3:
        from .stock_first import close_guard
        close_guard(doc,context)
    for receipt in context['receipts']:
        if not receipt.freight_finalized:
            frappe.throw(_('Reconcile actual freight before closing the case.'))
        if receipt.dispute_status=='Open':
            frappe.throw(_('Resolve all open disputes.'))
        rejected=any(x['receipt'].name==receipt.name and x['allocation'].decision=='Reject' for x in context['allocations'])
        if rejected and receipt.disposition=='Pending':
            frappe.throw(_('Record collection/return/disposal of rejected goods.'))
    if any(x['allocation'].decision=='Accept' for x in context['allocations']):
        if state(doc) not in ('Settled','Closed'):
            frappe.throw(_('Complete Finance settlement before closing accepted returns.'))
        verify_accounting(doc)
    elif any(flt(r.customer_freight) for r in context['receipts']) or any(
        flt(doc.get(k)) for k in ('handling_charge', 'restocking_charge', 'waiver_amount')
    ):
        # A rejected-only case can still owe actual freight or handling.
        calculate_settlement(doc, context)
        verify_accounting(doc)


def prevent_delete(doc,method=None):
    if doc.doctype in ('Return Inspection','Return Settlement') or state(doc)!='Draft':
        frappe.throw(_('Preserve the return audit trail; only unused drafts can be deleted.'))


def is_legacy_reference(mra,doctype,name):
    for legacy_name in json.loads(mra.legacy_settlements or '[]'):
        legacy=frappe.get_doc('Return Settlement',legacy_name)
        if any(x.document_type==doctype and x.document_name==name
               for x in list(legacy.accounting_documents)+list(legacy.stock_references)):
            return True
    return False


def validate_shipment(doc,method=None):
    if not doc.get('custom_return_mra'):
        return
    mra=read_doc('Material Return Authorization',doc.custom_return_mra)
    valid_authorization(mra)
    if doc.get('custom_return_direction')=='Rejected Goods Return':
        valid=(doc.pickup_from_type=='Company' and doc.pickup_company==mra.company and
               doc.delivery_to_type=='Customer' and doc.delivery_customer==mra.customer)
    else:
        valid=(doc.pickup_from_type=='Customer' and doc.pickup_customer==mra.customer and
               doc.delivery_to_type=='Company' and doc.delivery_company==mra.company)
    if not valid:
        frappe.throw(_('Return shipment pickup/delivery parties must match its MRA and direction.'))
    if doc.get('custom_return_receipt'):
        custody=read_doc('Return Receipt',doc.custom_return_receipt)
        if custody.authorization!=mra.name:
            frappe.throw(_('Shipment custody receipt belongs to another MRA.'))
