"""Server-side return rules and role-separated transitions."""
import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, today

from .policy import freight_split, money, number, rejection_deadlines, working_due

MD = 'Managing Director'
SALES = ('Sales User', 'Sales Manager', MD)
STOCK = ('Stock User', 'Stock Manager')
QC = ('Quality Manager',)
FINANCE = ('Accounts User', 'Accounts Manager')
STAMPS = ('approved_by', 'approved_on', 'approved_date', 'waiver_approved_by',
          'waiver_approved_on', 'disposal_approved_by', 'completed_on', 'complete_on')


def require_roles(*roles):
    if not set(roles).intersection(frappe.get_roles()):
        frappe.throw(_('You do not have the required return role.'), frappe.PermissionError)


def settings():
    doc = frappe.get_cached_doc('Return Settings')
    if not doc.enabled:
        frappe.throw(_('Configure and enable Return Settings before using returns.'))
    return doc


def read_doc(doctype, name):
    doc = frappe.get_doc(doctype, name)
    doc.check_permission('read')
    return doc


def due(start, target):
    config = settings()
    holidays = frappe.get_all('Holiday', filters={'parent': config.holiday_list}, pluck='holiday_date')
    return working_due(start, config.get(target), holidays)


def stamp(doc, prefix='approved'):
    doc.set(prefix + '_by', frappe.session.user)
    doc.set(prefix + '_on', now_datetime())


def canonical(value):
    if isinstance(value, list):
        return [canonical(x) for x in value]
    if hasattr(value, 'as_dict'):
        return {k: canonical(v) for k, v in value.as_dict().items() if k not in ('modified', 'modified_by')}
    return value


def immutable(doc, old, fields):
    for field in fields:
        if json.dumps(canonical(doc.get(field)), default=str, sort_keys=True) != json.dumps(canonical(old.get(field)), default=str, sort_keys=True):
            frappe.throw(_('Field {0} is frozen. Create a recorded revision instead.').format(field))


def guard(doc):
    old = doc.get_doc_before_save()
    action = doc.flags.get('return_action')
    if not action:
        for field in ('status', *STAMPS):
            if old:
                immutable(doc, old, [field])
            elif field != 'status' and doc.get(field):
                frappe.throw(_('Approval and completion fields are server controlled.'))
        if not old and doc.get('status') != 'Draft':
            frappe.throw(_('New returns must start as Draft.'))
    if doc.revised_due_date and not doc.delay_reason:
        frappe.throw(_('A revised due date requires a delay reason.'))
    return old


def matching_parent(child, parent):
    for field in ('company', 'customer', 'currency'):
        if child.get(field) != parent.get(field):
            frappe.throw(_('Company, customer and currency must match the MRA.'))


def positive(value):
    if number(value) <= 0:
        frappe.throw(_('Quantity must be greater than zero.'))


def validate_mra(doc):
    if doc.flags.get('return_action') == 'close':
        require_roles(settings().settlement_approver_role)
    else:
        require_roles(*SALES)
    old = guard(doc)
    if old and old.status in ('Authorized', 'Rejected', 'Closed'):
        immutable(doc, old, ['company', 'customer', 'currency', 'items', 'policy_snapshot', 'freight_estimate', 'freight_terms', 'approval_reason', 'revision_of', 'category_summary', 'claimed_value', 'approved_value'])
        return
    elif old and old.status == 'Pending Approval':
        require_roles(MD)
    if not doc.items:
        frappe.throw(_('At least one item is required.'))
    categories = set()
    claimed = approved = 0
    for row in doc.items:
        positive(row.claimed_qty)
        if number(row.approved_qty) > number(row.claimed_qty):
            frappe.throw(_('Approved quantity cannot exceed claimed quantity.'))
        categories.add(row.claimed_category)
        if row.sales_invoice:
            invoice = read_doc('Sales Invoice', row.sales_invoice)
            validate_invoice(invoice, doc.company, doc.customer, doc.currency)
            line = next((x for x in invoice.items if x.name == row.sales_invoice_item), None)
            if not line or line.item_code != row.item_code or line.uom != row.uom:
                frappe.throw(_('Select an invoice item matching this item and UOM.'))
            row.net_rate = line.net_rate
            row.invoice_date = invoice.posting_date
            row.remaining_qty = remaining(invoice, line)
        else:
            row.net_rate = 0
            row.invoice_date = None
            row.sales_invoice_item = None
            row.invoice_source = None
            row.invoice_confirmed = 0
        claimed += float(number(row.claimed_qty) * number(row.net_rate))
        approved += float(number(row.approved_qty) * number(row.net_rate))
    doc.category_summary = next(iter(categories)) if len(categories) == 1 else 'Mixed'
    doc.claimed_value, doc.approved_value = claimed, approved
    number(doc.freight_estimate)
    if doc.revision_of:
        prior = read_doc(doc.doctype, doc.revision_of)
        matching_parent(doc, prior)
        if prior.status != 'Authorized':
            frappe.throw(_('Only an authorized MRA can be revised.'))


def validate_invoice(invoice, company, customer, currency):
    if invoice.docstatus != 1 or invoice.is_return or (invoice.company, invoice.customer, invoice.currency) != (company, customer, currency):
        frappe.throw(_('Choose a submitted sale for the same company, customer and currency.'))


def remaining(invoice, line):
    # Standard posted returns only. No custom reservation / duplicate-claim system.
    rows = frappe.db.sql('''select coalesce(sum(abs(i.qty)), 0) from `tabSales Invoice Item` i
        join `tabSales Invoice` p on p.name=i.parent
        where p.docstatus=1 and p.is_return=1 and p.return_against=%s and i.sales_invoice_item=%s''', (invoice.name, line.name))
    return max(0, float(line.qty) - float(rows[0][0]))


def validate_receipt(doc):
    require_roles(*STOCK, *FINANCE)
    old = guard(doc)
    mra = read_doc('Material Return Authorization', doc.authorization)
    matching_parent(doc, mra)
    if mra.status != 'Authorized':
        frappe.throw(_('Receipt requires an authorized MRA.'))
    if frappe.db.exists('Material Return Authorization', {'revision_of': mra.name, 'status': 'Authorized'}):
        frappe.throw(_('Use the latest authorized revision.'))
    if old and old.status == 'Received':
        immutable(doc, old, ['authorization', 'company', 'customer', 'currency', 'items', 'received_on'])
        if frappe.db.exists('Return Settlement Item', {'parenttype': 'Return Settlement', 'inspection': ['in', frappe.get_all('Return Inspection', filters={'receipt': doc.name}, pluck='name')] or ['']}):
            immutable(doc, old, ['actual_freight', 'customer_freight', 'freight_responsibility', 'freight_bill', 'freight_finalized'])
    if not doc.items:
        frappe.throw(_('Record received items.'))
    approved = {x.name: x for x in mra.items}
    prior = dict(frappe.db.sql('''select i.mra_item, sum(i.received_qty) from `tabReturn Receipt Item` i
        join `tabReturn Receipt` p on p.name=i.parent
        where p.authorization=%s and p.status='Received' and p.name!=%s group by i.mra_item''', (mra.name, doc.name)))
    running = defaultdict(float)
    for row in doc.items:
        positive(row.received_qty)
        source = approved.get(row.mra_item)
        mismatch = not source or source.item_code != row.item_code or source.uom != row.uom
        available = max(0, float(source.approved_qty) - float(prior.get(row.mra_item, 0)) - running[row.mra_item]) if not mismatch else 0
        if not old or old.status != 'Received':
            row.unauthorized_qty = max(0, float(row.received_qty) - available)
            row.unauthorized = int(row.unauthorized_qty > 0)
        running[row.mra_item] += float(row.received_qty)
    for field in ('freight_estimate', 'actual_freight', 'customer_freight'):
        number(doc.get(field))
    if doc.status == 'Received' and doc.documents_complete and not doc.complete_on:
        doc.complete_on = today()
        doc.due_date = due(today(), 'inspection_days')
    if doc.freight_finalized:
        require_roles(*FINANCE)
        doc.customer_freight = float(freight_split(doc.actual_freight, doc.freight_responsibility, doc.customer_freight))
        if doc.freight_responsibility == 'Shared' and not doc.allocation_reason:
            frappe.throw(_('Explain the mixed-shipment freight allocation.'))
        if doc.paid_by == 'SNRG' and number(doc.actual_freight) and not doc.freight_bill:
            frappe.throw(_('Link the actual transporter Purchase Invoice.'))
        if doc.freight_bill:
            bill = read_doc('Purchase Invoice', doc.freight_bill)
            if bill.docstatus != 1 or bill.is_return or bill.company != doc.company or bill.supplier != doc.transporter or bill.currency != doc.currency:
                frappe.throw(_('Freight bill must be a submitted invoice for this transporter, company and currency.'))


def validate_inspection(doc):
    require_roles(*QC, MD)
    old = guard(doc)
    if not doc.flags.get('return_action'):
        require_roles(*QC)
    receipt = read_doc('Return Receipt', doc.receipt)
    if receipt.status != 'Received':
        frappe.throw(_('Record physical receipt before QC.'))
    doc.authorization = receipt.authorization
    doc.due_date = receipt.due_date
    if old and old.status == 'Completed':
        immutable(doc, old, ['receipt', 'items', 'authorization'])
    sources = {x.name: x for x in receipt.items}
    totals = defaultdict(float)
    for row in doc.items:
        source = sources.get(row.receipt_item)
        if not source:
            frappe.throw(_('Inspection line must reference this receipt.'))
        row.item_code = source.item_code
        positive(row.qty)
        totals[row.receipt_item] += float(row.qty)
        if totals[row.receipt_item] > float(source.received_qty):
            frappe.throw(_('QC split exceeds received quantity.'))
        old_row = next((x for x in (old.items if old else []) if x.name == row.name), None)
        if not doc.flags.get('return_action') and row.exception_approved_by != (old_row.exception_approved_by if old_row else None):
            frappe.throw(_('Exception approval is server controlled.'))
        if old_row and row.exception_approved_by:
            immutable(row, old_row, ['receipt_item', 'qty', 'finding', 'decision', 'notes', 'exception_reason'])
    if doc.dispute_status == 'Resolved' and (not doc.resolved_on or not doc.resolution):
        frappe.throw(_('Dispute resolution requires date and explanation.'))
    if doc.rejection_notice_date:
        if not doc.findings_notice:
            frappe.throw(_('Attach the rejection statement shared with the customer.'))
        doc.dispute_deadline, doc.collection_deadline = rejection_deadlines(doc.rejection_notice_date, doc.resolved_on if doc.dispute_status == 'Resolved' else None)
    else:
        doc.dispute_deadline = doc.collection_deadline = None
    if doc.disposition == 'Disposed' and (not doc.customer_disposal_instruction or not doc.disposal_approved_by):
        frappe.throw(_('Disposal requires written customer instructions and internal approval.'))
    if doc.disposition != 'Pending' and (not doc.disposition_date or not doc.disposition_evidence):
        frappe.throw(_('Record disposition date and evidence.'))


def validate_settlement(doc):
    require_roles(*FINANCE, settings().settlement_approver_role, MD)
    old = guard(doc)
    if not doc.flags.get('return_action'):
        require_roles(*FINANCE, settings().settlement_approver_role)
    mra = read_doc('Material Return Authorization', doc.authorization)
    matching_parent(doc, mra)
    if mra.status != 'Authorized':
        frappe.throw(_('Settlement requires an authorized MRA.'))
    if old and old.status in ('Approved', 'Settled'):
        immutable(doc, old, ['authorization', 'company', 'customer', 'currency', 'items', 'route', 'supplier', 'gross_value', 'restocking_charge', 'handling_charge', 'waiver_amount', 'waiver_reason'])
    if not doc.items:
        frappe.throw(_('Select accepted inspection lines.'))
    gross = standard = 0
    receipt_names = set()
    for row in doc.items:
        inspection = read_doc('Return Inspection', row.inspection)
        if inspection.status != 'Completed' or inspection.authorization != mra.name:
            frappe.throw(_('Select a completed inspection for this MRA.'))
        inspected = next((x for x in inspection.items if x.name == row.inspection_item), None)
        if not inspected or inspected.decision != 'Accept':
            frappe.throw(_('Only accepted QC lines can be settled.'))
        receipt = read_doc('Return Receipt', inspection.receipt)
        received = next(x for x in receipt.items if x.name == inspected.receipt_item)
        source = next((x for x in mra.items if x.name == received.mra_item), None)
        if source and source.item_code == inspected.item_code and source.sales_invoice and source.invoice_confirmed:
            row.sales_invoice = source.sales_invoice
            row.sales_invoice_item = source.sales_invoice_item
            rate = source.net_rate
        else:
            if not row.sales_invoice or not row.sales_invoice_item or not row.valuation_reason:
                frappe.throw(_('Unexpected goods require a verified original invoice line and valuation explanation. Untraceable fallback is not configured.'))
            invoice = read_doc('Sales Invoice', row.sales_invoice)
            validate_invoice(invoice, doc.company, doc.customer, doc.currency)
            invoice_line = next((x for x in invoice.items if x.name == row.sales_invoice_item), None)
            if not invoice_line or invoice_line.item_code != inspected.item_code or invoice_line.uom != received.uom:
                frappe.throw(_('Settlement valuation invoice line must match the received item and UOM.'))
            rate = invoice_line.net_rate
        receipt_names.add(receipt.name)
        row.item_code, row.qty, row.net_rate = inspected.item_code, inspected.qty, rate
        row.amount = float(money(number(row.qty) * number(row.net_rate)))
        row.restocking_amount = float(money(number(row.amount) * number(25) / 100)) if inspected.finding == 'Fresh / Saleable' else 0
        gross += row.amount
        standard += row.restocking_amount
    freight = 0
    for name in receipt_names:
        receipt = read_doc('Return Receipt', name)
        if not receipt.freight_finalized:
            frappe.throw(_('Finalize actual freight allocation before settlement.'))
        freight += float(receipt.customer_freight)
    doc.gross_value, doc.standard_restocking, doc.freight_charge = gross, standard, freight
    if not doc.due_date:
        doc.due_date = due(today(), 'settlement_days')
    if doc.restocking_charge is None or (doc.is_new() and not doc.restocking_charge):
        doc.restocking_charge = standard
    for field in ('restocking_charge', 'handling_charge', 'waiver_amount'):
        number(doc.get(field))
    concession = max(0, standard - float(doc.restocking_charge)) + float(doc.waiver_amount or 0)
    if float(doc.waiver_amount or 0) > float(doc.freight_charge or 0) + float(doc.handling_charge or 0):
        frappe.throw(_('Freight/handling waiver cannot exceed those charges.'))
    if concession and not doc.waiver_reason:
        frappe.throw(_('Explain the requested concession.'))
    if old:
        changed = any(canonical(doc.get(x)) != canonical(old.get(x)) for x in ('items', 'restocking_charge', 'handling_charge', 'waiver_amount', 'waiver_reason', 'freight_charge', 'standard_restocking'))
        if changed and not doc.flags.get('return_action'):
            doc.waiver_approved_by = doc.waiver_approved_on = None
    doc.net_value = float(money(gross)) - float(doc.restocking_charge or 0) - freight - float(doc.handling_charge or 0) + float(doc.waiver_amount or 0)
    if doc.net_value < 0:
        frappe.throw(_('Charges exceed the accepted goods value; Finance must resolve separately.'))
    if doc.route == 'Customer Invoice':
        if not doc.supplier:
            frappe.throw(_('Select the Supplier linked to this customer.'))
        supplier = read_doc('Supplier', doc.supplier)
        if not supplier.custom_is_customer or supplier.custom_linked_customer != doc.customer or supplier.disabled:
            frappe.throw(_('Supplier must be enabled and explicitly linked to this customer.'))
    elif doc.supplier:
        frappe.throw(_('Supplier applies only to the customer-invoice route.'))


def transition(doc, action, reason=None):
    doc.check_permission('write')
    settings()
    doc.flags.return_action = action
    state = doc.status
    if doc.doctype == 'Material Return Authorization':
        if action == 'request_approval' and state == 'Draft':
            require_roles(*SALES)
            if not doc.information_complete:
                frappe.throw(_('Mark the request information complete.'))
            doc.complete_on = today()
            doc.due_date = due(today(), 'authorization_days')
            doc.status = 'Pending Approval'
        elif action in ('authorize', 'reject') and state == 'Pending Approval':
            require_roles(MD)
            if not reason:
                frappe.throw(_('Record the approval/rejection reason.'))
            if action == 'authorize':
                if not any(float(x.approved_qty or 0) > 0 for x in doc.items):
                    frappe.throw(_('Approve at least one quantity.'))
                for row in doc.items:
                    if float(row.approved_qty or 0) and (not row.sales_invoice or not row.invoice_confirmed):
                        frappe.throw(_('Confirm invoice valuation for approved lines; untraceable valuation policy is not configured.'))
                    if float(row.approved_qty or 0) and row.condition != 'Current Saleable' and row.claimed_category == 'Commercial Return' and not row.exception_reason:
                        frappe.throw(_('Explain the commercial-condition exception.'))
                doc.policy_snapshot = settings().policy_terms
            doc.approval_reason = reason
            stamp(doc)
            doc.status = 'Authorized' if action == 'authorize' else 'Rejected'
        elif action == 'close' and state == 'Authorized':
            require_roles(settings().settlement_approver_role)
            doc.closure_reason = reason
            verify_closure(doc)
            doc.status = 'Closed'
            doc.closure_reason = reason
        else:
            frappe.throw(_('Invalid authorization transition.'))
    elif doc.doctype == 'Return Receipt' and action == 'receive' and state == 'Draft':
        require_roles(*STOCK)
        doc.status = 'Received'
    elif doc.doctype == 'Return Inspection':
        validate_inspection(doc)
        if action == 'complete_qc' and state == 'Draft':
            require_roles(*QC)
            receipt = read_doc('Return Receipt', doc.receipt)
            if not receipt.documents_complete:
                frappe.throw(_('Required receipt documents are incomplete.'))
            totals = defaultdict(float)
            for row in doc.items:
                totals[row.receipt_item] += float(row.qty)
                source = next(x for x in receipt.items if x.name == row.receipt_item)
                if row.decision == 'Accept' and (source.unauthorized or row.finding in ('Fresh / Saleable', 'Customer Damage', 'Unsellable')) and not row.exception_approved_by:
                    frappe.throw(_('MD approval is required for commercial, unauthorized or goodwill acceptance.'))
            if any(abs(totals[x.name] - float(x.received_qty)) > 0.000001 for x in receipt.items):
                frappe.throw(_('Classify every received quantity before completing QC.'))
            if frappe.db.exists('Return Inspection', {'receipt': receipt.name, 'status': 'Completed', 'name': ['!=', doc.name]}):
                frappe.throw(_('Use the existing completed inspection for this receipt.'))
            doc.completed_on = today()
            doc.status = 'Completed'
        elif action == 'approve_exceptions' and state == 'Draft':
            require_roles(MD)
            for row in doc.items:
                if row.decision == 'Accept' and row.exception_reason:
                    row.exception_approved_by = frappe.session.user
        elif action == 'approve_disposal' and state == 'Completed':
            require_roles(MD)
            if not doc.customer_disposal_instruction:
                frappe.throw(_('Attach written customer disposal instructions.'))
            doc.disposal_approved_by = frappe.session.user
        else:
            frappe.throw(_('Invalid inspection transition.'))
    elif doc.doctype == 'Return Settlement':
        validate_settlement(doc)
        if action == 'approve_waiver' and state == 'Draft':
            require_roles(MD)
            if frappe.session.user != settings().waiver_approver:
                frappe.throw(_('Only the designated Managing Director user may approve concessions.'))
            stamp(doc, 'waiver_approved')
        elif action == 'approve_settlement' and state == 'Draft':
            require_roles(settings().settlement_approver_role)
            concession = max(0, doc.standard_restocking - float(doc.restocking_charge or 0)) + float(doc.waiver_amount or 0)
            if concession and not doc.waiver_approved_by:
                frappe.throw(_('Obtain MD concession approval first.'))
            stamp(doc)
            doc.approved_date = today()
            doc.due_date = due(today(), 'document_days')
            doc.status = 'Approved'
        elif action == 'settle' and state == 'Approved':
            require_roles(settings().settlement_approver_role)
            verify_accounting(doc)
            doc.status = 'Settled'
        else:
            frappe.throw(_('Invalid settlement transition.'))
    else:
        frappe.throw(_('Invalid return transition.'))
    doc.save()
    doc.add_comment('Comment', text=f'{action}: {reason or ""}')
    return doc


def verify_accounting(doc):
    if not (doc.stock_reconciled and doc.charges_reconciled and doc.ledger_reconciled and doc.reconciliation_notes):
        frappe.throw(_('Finance must reconcile stock, charges and ledgers and record the reconciliation.'))
    settlement_count = 0
    billed_value = 0
    offset = False
    for ref in doc.accounting_documents:
        account = read_doc(ref.document_type, ref.document_name)
        if account.docstatus != 1 or account.company != doc.company:
            frappe.throw(_('Accounting references must be submitted in this company.'))
        if ref.purpose == 'Settlement':
            settlement_count += 1
            billed_value += abs(float(account.net_total))
            if account.currency != doc.currency:
                frappe.throw(_('Settlement currency differs from MRA.'))
            if doc.route == 'SNRG Credit Note':
                if ref.document_type != 'Sales Invoice' or not account.is_return or account.customer != doc.customer:
                    frappe.throw(_('Link this customer’s submitted credit note.'))
            else:
                if ref.document_type != 'Purchase Invoice' or account.is_return or account.supplier != doc.supplier:
                    frappe.throw(_('Link the customer-supplier’s submitted Purchase Invoice.'))
                if account.bill_no != doc.customer_invoice_number or getdate(account.bill_date) != getdate(doc.customer_invoice_date):
                    frappe.throw(_('Customer invoice number/date must match the Purchase Invoice.'))
        if ref.purpose == 'Offset / Payment':
            if ref.document_type not in ('Journal Entry', 'Payment Entry'):
                frappe.throw(_('Offset/payment must reference a Journal Entry or Payment Entry.'))
            if ref.document_type == 'Journal Entry':
                parties = {(x.party_type, x.party) for x in account.accounts}
                if ('Customer', doc.customer) not in parties or ('Supplier', doc.supplier) not in parties:
                    frappe.throw(_('Offset Journal Entry must reference both this customer and linked supplier.'))
            elif account.party_type != 'Supplier' or account.party != doc.supplier:
                frappe.throw(_('Payment Entry must reference the linked supplier.'))
            offset = True
    doc.accounting_difference = billed_value - float(doc.gross_value)
    if abs(doc.accounting_difference) > 0.01 and not doc.difference_reason:
        frappe.throw(_('Explain the difference between settlement invoice value and approved goods value.'))
    if not settlement_count:
        frappe.throw(_('Link at least one submitted settlement document.'))
    if doc.route == 'Customer Invoice' and (not offset or not doc.customer_invoice_attachment or not doc.customer_invoice_number or not doc.customer_invoice_date):
        frappe.throw(_('Customer-invoice settlement needs the customer bill and payment/offset reference.'))
    if not doc.stock_references:
        frappe.throw(_('Link the documents that posted the accepted stock.'))
    for ref in doc.stock_references:
        stock = read_doc(ref.document_type, ref.document_name)
        if ref.document_type in ('Delivery Note', 'Sales Invoice') and (stock.get('customer') != doc.customer or not stock.is_return):
            frappe.throw(_('Sales stock document must be a return for this customer.'))
        if ref.document_type in ('Purchase Receipt', 'Purchase Invoice') and (doc.route != 'Customer Invoice' or stock.get('supplier') != doc.supplier or stock.is_return):
            frappe.throw(_('Purchase stock document must be an inward receipt from the linked supplier.'))
        if stock.docstatus != 1 or stock.company != doc.company:
            frappe.throw(_('Stock reference must be submitted in this company.'))
        if ref.document_type in ('Sales Invoice', 'Purchase Invoice') and not stock.update_stock:
            frappe.throw(_('An invoice stock reference must actually update stock.'))


def verify_closure(mra):
    settlements = frappe.get_all('Return Settlement', filters={'authorization': mra.name}, pluck='name')
    settled = defaultdict(float)
    for name in settlements:
        doc = read_doc('Return Settlement', name)
        if doc.status != 'Settled':
            frappe.throw(_('Finish all settlement records before closing.'))
        verify_accounting(doc)
        for row in doc.items:
            settled[(row.inspection, row.inspection_item)] += float(row.qty)
    receipts = frappe.get_all('Return Receipt', filters={'authorization': mra.name}, pluck='name')
    if not receipts:
        if not mra.closure_reason:
            frappe.throw(_('Explain closure without physical receipt.'))
    for receipt in receipts:
        inspections = frappe.get_all('Return Inspection', filters={'receipt': receipt, 'status': 'Completed'}, pluck='name')
        if len(inspections) != 1:
            frappe.throw(_('Every receipt needs a completed inspection.'))
        qc = read_doc('Return Inspection', inspections[0])
        if qc.dispute_status == 'Open':
            frappe.throw(_('Resolve open disputes before closure.'))
        if any(x.decision == 'Reject' for x in qc.items) and qc.disposition == 'Pending':
            frappe.throw(_('Record the disposition of rejected goods.'))
        for row in qc.items:
            if row.decision == 'Accept' and abs(settled[(qc.name, row.name)] - float(row.qty)) > 0.000001:
                frappe.throw(_('Accepted QC quantities and settled quantities must reconcile.'))


def prevent_delete(doc, method=None):
    if doc.get('status') != 'Draft':
        frappe.throw(_('Only draft return documents can be deleted.'))
