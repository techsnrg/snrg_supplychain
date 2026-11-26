"""Scoped adapters for native documents. Untagged transactions use ERPNext unchanged."""
import frappe
from frappe import _
from frappe.utils import flt

from .native_service import (ACTIVE_CUSTODY_STATES, SIGNED_STATES, exception_digest,
    qc_context, rate_for, read_doc, require_complete_qc, state, valid_authorization)

ROW_TYPES={'Delivery Note':'Delivery Note Item','Sales Invoice':'Sales Invoice Item',
    'Purchase Receipt':'Purchase Receipt Item','Purchase Invoice':'Purchase Invoice Item'}


class ReturnInspectionAdapter:
    def validate_inspection(self):
        if self.get('custom_return_mra') and (self.get('custom_return_purpose') or 'Goods Return') in ('Goods Return','Arrival','Disposition'):
            # Returns are judged against custody QC and commercial acceptance, not the
            # site's global normal-purchase/delivery inspection policy. A failed product
            # test may be an eligible warranty return. All untagged documents call super.
            validate_return_document(self, preliminary=True)
            return
        return super().validate_inspection()


def stock_effect(doc):
    return doc.doctype in ('Delivery Note','Purchase Receipt') or bool(doc.get('update_stock'))


def validate_return_document(doc,method=None,preliminary=False):
    if not doc.get('custom_return_mra'):
        return
    mra=read_doc('Material Return Authorization',doc.custom_return_mra)
    valid_authorization(mra)
    if doc.company!=mra.company:
        frappe.throw(_('Return document company must match its MRA.'))
    purpose=doc.get('custom_return_purpose') or 'Goods Return'
    if purpose=='Freight':
        if doc.doctype!='Purchase Invoice' or doc.get('update_stock') or doc.get('is_return'):
            frappe.throw(_('Freight references use an ordinary non-stock transporter Purchase Invoice.'))
        return
    if purpose=='Charge':
        if doc.doctype!='Sales Invoice' or doc.is_return or doc.update_stock or doc.customer!=mra.customer:
            frappe.throw(_('Recovery charges require a non-stock Sales Invoice for the return customer.'))
        if state(mra)!='Settlement Approved' and doc.docstatus!=2:
            frappe.throw(_('Finance must approve the MRA before posting recovery charges.'))
        return
    if doc.doctype in ('Journal Entry','Payment Entry'):
        if state(mra)!='Settlement Approved' and doc.docstatus!=2:
            frappe.throw(_('Finance must approve the return before its payment/offset.'))
        return
    if int(mra.get('native_returns_version') or 0)>=3:
        from .stock_first import validate_document
        return validate_document(doc,mra,preliminary)
    if doc.doctype not in ROW_TYPES:
        frappe.throw(_('Use native sales-return or purchase-receipt documents for accepted stock.'))
    if state(mra) not in (*ACTIVE_CUSTODY_STATES,'Settlement Approved'):
        frappe.throw(_('Return case is not open for stock/accounting posting.'))
    if doc.get('currency') and doc.currency!=mra.currency:
        frappe.throw(_('Return currency must match the approved case.'))
    if doc.doctype in ('Sales Invoice','Delivery Note'):
        if mra.route!='SNRG Credit Note' or not doc.is_return or doc.customer!=mra.customer:
            frappe.throw(_('Sales return must match the MRA customer and credit-note route.'))
    else:
        if mra.route!='Customer Invoice' or doc.is_return or doc.supplier!=mra.supplier:
            frappe.throw(_('Purchase return receipt must match the selected customer-supplier route.'))
        supplier=read_doc('Supplier',doc.supplier)
        if not supplier.custom_is_customer or supplier.custom_linked_customer!=mra.customer or supplier.disabled:
            frappe.throw(_('Supplier must be explicitly linked to the return customer.'))
    if doc.doctype in ('Sales Invoice','Purchase Invoice') and state(mra)!='Settlement Approved':
        frappe.throw(_('Finance approval is required before the settlement invoice.'))
    context=qc_context(mra)
    require_complete_qc(context)
    if context['exceptions'] and mra.exception_fingerprint!=exception_digest(context):
        frappe.throw(_('Obtain MD approval for these exact commercial return exceptions.'))
    accepted={(x['qi'].name,x['allocation'].name):x for x in context['allocations'] if x['allocation'].decision=='Accept'}
    totals={}
    for row in doc.items:
        key=(row.get('custom_return_qi'),row.get('custom_return_allocation'))
        entry=accepted.get(key)
        if not entry:
            frappe.throw(_('Every goods row must reference a submitted QC allocation accepted for this MRA.'))
        receipt=entry['received']
        if (row.item_code,row.uom)!=(receipt.item_code,receipt.uom):
            frappe.throw(_('Native document item/UOM must match custody and QC.'))
        if doc.doctype in ('Delivery Note','Sales Invoice') and flt(row.qty)>=0:
            frappe.throw(_('Sales return quantities must be negative.'))
        if doc.doctype in ('Purchase Receipt','Purchase Invoice') and flt(row.qty)<=0:
            frappe.throw(_('Buying-route received quantities must be positive.'))
        if flt(row.get('rejected_qty')):
            frappe.throw(_('Commercially refused quantities stay in custody; do not bill them through rejected purchase quantities.'))
        qty=abs(flt(row.qty));totals[key]=totals.get(key,0)+qty
        if totals[key]>flt(entry['allocation'].qty)+0.000001:
            frappe.throw(_('Native goods quantity exceeds the accepted QC allocation.'))
        if stock_effect(doc):
            if not mra.return_warehouse or row.warehouse!=mra.return_warehouse:
                frappe.throw(_('Receive accepted returns into the case’s configured quarantine warehouse.'))
            if doc.docstatus==1 and posted_quantity(mra,key,exclude=(doc.doctype,doc.name))+totals[key]>flt(entry['allocation'].qty)+0.000001:
                frappe.throw(_('Accepted return stock has already been received through another native document.'))
        if not preliminary and doc.doctype in ('Sales Invoice','Purchase Invoice'):
            if abs(flt(row.net_rate)-rate_for(mra,entry))>0.01:
                frappe.throw(_('Settlement goods rate must match approved original net invoice valuation.'))


def posted_quantity(mra,key,exclude=None,allowed_documents=None):
    total=0
    for dt,child in ROW_TYPES.items():
        parents=frappe.get_all(dt,filters={'custom_return_mra':mra.name,'docstatus':1},fields=['name']+(['update_stock'] if dt.endswith('Invoice') else []))
        for parent in parents:
            if exclude==(dt,parent.name) or (dt.endswith('Invoice') and not parent.update_stock):
                continue
            if allowed_documents is not None and (dt,parent.name) not in allowed_documents:
                continue
            rows=frappe.get_all(child,filters={'parent':parent.name,'custom_return_qi':key[0],
                'custom_return_allocation':key[1]},fields=['qty'])
            total+=sum(abs(flt(x.qty)) for x in rows)
    return total


def validate_stock_reconciliation(mra,context):
    if int(mra.get('native_returns_version') or 0)>=3:
        from .stock_first import reconcile
        return reconcile(mra,context)
    allowed={(x.document_type,x.document_name) for x in mra.stock_references}
    for entry in context['allocations']:
        if entry['allocation'].decision=='Accept':
            if entry['qi'].get('custom_legacy_inspection'):
                continue  # Exact legacy references remain validated; new QC is always reconciled.
            key=(entry['qi'].name,entry['allocation'].name)
            if abs(posted_quantity(mra,key,allowed_documents=allowed)-flt(entry['allocation'].qty))>0.000001:
                frappe.throw(_('Linked native stock documents do not reconcile to every accepted QC quantity.'))


def before_cancel(doc,method=None):
    if doc.get('custom_return_mra'):
        mra=read_doc('Material Return Authorization',doc.custom_return_mra)
        from .stock_first import before_cancel as stock_first_cancel
        stock_first_cancel(doc)
        if state(mra) in SIGNED_STATES:
            frappe.throw(_('Revise the return settlement through Workflow before cancelling linked native documents.'))
