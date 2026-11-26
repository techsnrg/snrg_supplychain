"""Stock-first returns: native arrivals, subsequent QC, and non-stock settlement.

Version 2 custody cases remain on their original path; new version 3 cases never
create a custom Return Receipt. Native controllers retain valuation/GL posting.
"""
from collections import defaultdict
import frappe
from frappe import _
from frappe.utils import flt, today, now_datetime, getdate
from .stock_first_setup import ARRIVALS, CHILDREN, LOGISTICS
from . import native_service as service


def enabled(mra):
    return int(mra.get('native_returns_version') or 0) >= 3


def is_arrival(doc):
    return bool(doc.get('custom_return_mra') and doc.get('custom_return_purpose') == 'Arrival')


def receipt_view(doc):
    """Compatibility view for commercial arithmetic; never saved as a document."""
    result=frappe._dict(doctype=doc.doctype,name=doc.name,authorization=doc.custom_return_mra,
        company=doc.company,customer=doc.get('customer'),currency=doc.get('currency'),status='Received' if doc.docstatus==1 else 'Draft')
    for field in LOGISTICS:result[field]=doc.get('custom_return_'+field)
    result['items']=[]
    for row in doc.items:
        qi=frappe.db.get_value('Quality Inspection',dict(reference_type=doc.doctype,reference_name=doc.name,child_row_reference=row.name,docstatus=1),'name')
        result['items'].append(frappe._dict(name=row.name,item_code=row.item_code,uom=row.uom,received_qty=abs(flt(row.qty)),
            mra_item=row.custom_return_mra_item,batch_no=row.get('batch_no'),serial_no=row.get('serial_no'),
            quality_inspection=qi,unauthorized=0,source_invoice=row.custom_return_source_invoice,source_invoice_item=row.custom_return_source_invoice_item))
    return result


def arrival_docs(mra, submitted_only=False):
    for dt in ARRIVALS:
        for name in frappe.get_all(dt,filters=dict(custom_return_mra=mra.name,custom_return_purpose='Arrival',docstatus=1 if submitted_only else ['<',2]),pluck='name',order_by='creation,name'):
            yield service.read_doc(dt,name)


def context(mra):
    data=dict(receipts=[],inspections=[],allocations=[],exceptions=[],incomplete=[])
    if mra.is_new():return data
    running=defaultdict(float)
    for doc in arrival_docs(mra):
        receipt=receipt_view(doc);data['receipts'].append(receipt)
        if doc.docstatus!=1 or not receipt.documents_complete:data['incomplete'].append(doc.name)
        for row in receipt['items']:
            original=next((x for x in mra.items if x.name==row.mra_item),None)
            running[row.mra_item]+=row.received_qty
            row.unauthorized=int(not original or running[row.mra_item]>flt(original.approved_qty)+0.000001)
            if not row.quality_inspection:
                data['incomplete'].append(row.name);continue
            qi=service.read_doc('Quality Inspection',row.quality_inspection)
            data['inspections'].append(qi)
            for allocation in qi.custom_return_allocations:
                entry=dict(qi=qi,allocation=allocation,receipt=receipt,received=row)
                data['allocations'].append(entry)
                if allocation.decision=='Accept' and (row.unauthorized or allocation.finding in ('Fresh / Saleable','Customer Damage','Unsellable')):
                    data['exceptions'].append(entry)
    return data


def source_line(mra,row):
    original=next((x for x in mra.items if x.name==row.custom_return_mra_item),None)
    if not original or (original.item_code,original.uom)!=(row.item_code,row.uom):
        frappe.throw(_('Every arrival row must identify its authorized MRA item. Add unexpected items through an authorized revision.'))
    invoice=service.read_doc('Sales Invoice',original.sales_invoice)
    service.validate_invoice(invoice,mra.company,mra.customer,mra.currency)
    line=next((x for x in invoice.items if x.name==original.sales_invoice_item),None)
    if not line:frappe.throw(_('Original invoice line is missing.'))
    if (row.custom_return_source_invoice,row.custom_return_source_invoice_item)!=(invoice.name,line.name):
        frappe.throw(_('Arrival source must match the confirmed original sales invoice row.'))
    return invoice,line


def original_stock(mra,row):
    invoice,line=source_line(mra,row)
    if line.get('delivery_note') and line.get('dn_detail'):
        parent=service.read_doc('Delivery Note',line.delivery_note)
        detail=next((x for x in parent.items if x.name==line.dn_detail),None)
        if parent.docstatus!=1 or not detail:frappe.throw(_('Original Delivery Note is not submitted.'))
        return parent,detail
    if invoice.update_stock:return invoice,line
    frappe.throw(_('Original invoice has neither its stock-updating sale nor a linked Delivery Note. Resolve the stock source before receiving.'))


def source_cost(mra,row):
    parent,line=original_stock(mra,row)
    sle=frappe.get_all('Stock Ledger Entry',filters=dict(voucher_type=parent.doctype,voucher_no=parent.name,
        voucher_detail_no=line.name,item_code=row.item_code,is_cancelled=0,actual_qty=['<',0]),
        fields=['actual_qty','stock_value_difference'],limit_page_length=0)
    qty=-sum(flt(x.actual_qty) for x in sle)
    cost=-sum(flt(x.stock_value_difference) for x in sle)/qty if qty else 0
    if cost<=0:frappe.throw(_('Original outgoing stock cost is missing or zero. Finance must resolve valuation before receiving.'))
    return cost


def cumulative_received(mra,exclude=None):
    # Entitlement is global across MRA cases, not just the current voucher.
    totals=defaultdict(float)
    source_items=[x.sales_invoice_item for x in mra.items]
    for dt in ARRIVALS:
        child=CHILDREN[dt]
        rows=frappe.db.sql(f"""select c.custom_return_source_invoice_item source_row,c.qty,p.name
            from `tab{child}` c join `tab{dt}` p on p.name=c.parent
            where p.docstatus=1 and p.custom_return_purpose='Arrival'
            and c.custom_return_source_invoice_item in %(items)s""",dict(items=source_items or ['']),as_dict=True)
        for row in rows:
            if exclude!=(dt,row.name):totals[row.source_row]+=abs(flt(row.qty))
    # Prior credit notes outside stock-first cases also consume original return entitlement.
    rows=frappe.db.sql("""select c.sales_invoice_item source_row,c.qty,p.custom_return_mra
        from `tabSales Invoice Item` c join `tabSales Invoice` p on p.name=c.parent
        where p.docstatus=1 and p.is_return=1 and c.sales_invoice_item in %(items)s""",dict(items=source_items or ['']),as_dict=True)
    for row in rows:
        if row.custom_return_mra and flt(frappe.db.get_value('Material Return Authorization',row.custom_return_mra,'native_returns_version'))>=3:continue
        totals[row.source_row]+=abs(flt(row.qty))
    return totals


def validate_arrival(doc,mra):
    if doc.doctype not in ARRIVALS:frappe.throw(_('Arrival must use a native Delivery Note, Purchase Receipt or Stock Entry.'))
    if service.state(mra) not in ('Authorized','Exceptions Approved'):
        frappe.throw(_('Arrival requires an open MD-authorized return case.'))
    service.require_roles(*service.STOCK)
    if not doc.items:frappe.throw(_('Record the actual arriving items.'))
    if doc.doctype=='Stock Entry' and doc.get('additional_costs'):frappe.throw(_('Keep receipt at original outgoing cost; reconcile freight separately instead of adding stock receipt valuation charges.'))
    warehouse=service.read_doc('Warehouse',mra.return_warehouse) if mra.return_warehouse else None
    if not warehouse or warehouse.company!=mra.company or warehouse.is_group or not warehouse.custom_returns_quarantine:
        frappe.throw(_('Select this company’s flagged Returns quarantine warehouse on the MRA.'))
    if doc.doctype=='Delivery Note' and (mra.route!='SNRG Credit Note' or not doc.is_return or doc.customer!=mra.customer):
        frappe.throw(_('Arrival Delivery Note must be this customer’s sales return.'))
    if doc.doctype=='Purchase Receipt':
        supplier=service.read_doc('Supplier',mra.supplier)
        if mra.route!='Customer Invoice' or doc.is_return or doc.supplier!=mra.supplier or supplier.disabled or not supplier.custom_is_customer or supplier.custom_linked_customer!=mra.customer:
            frappe.throw(_('Purchase arrival requires the selected Supplier linked to this customer.'))
    if doc.doctype=='Stock Entry' and (mra.route!='SNRG Credit Note' or doc.purpose!='Material Receipt'):
        frappe.throw(_('Stock Entry arrival is only the Material Receipt fallback for stock-updating sales invoices.'))
    if doc.docstatus==1:
        # Serialize entitlement checks across concurrent cases for the same sale.
        frappe.db.sql('select name from `tabSales Invoice Item` where name in %(names)s order by name for update',dict(names=sorted(x.sales_invoice_item for x in mra.items) or ['']))
    totals=cumulative_received(mra,(doc.doctype,doc.name))
    for row in doc.items:
        if (doc.doctype=='Delivery Note' and flt(row.qty)>=0) or (doc.doctype!='Delivery Note' and flt(row.qty)<=0):
            frappe.throw(_('Use positive receipt quantities or negative sales-return quantities.'))
        if (row.get('t_warehouse') if doc.doctype=='Stock Entry' else row.warehouse)!=mra.return_warehouse or row.get('s_warehouse'):
            frappe.throw(_('Arrival must go directly into the case’s Returns quarantine warehouse.'))
        invoice,line=source_line(mra,row)
        totals[line.name]+=abs(flt(row.qty))
        # Include existing native credits; stock-first credits have no stock effect but
        # remain an invoice-return entitlement. Our own received quantity is independent.
        if totals[line.name]>flt(line.qty)+0.000001:
            frappe.throw(_('Cumulative arriving quantity exceeds the original sold quantity.'))
        if flt(row.get('conversion_factor') or 1)!=flt(line.conversion_factor or 1):
            frappe.throw(_('Arrival must preserve the original invoice UOM conversion.'))
        if doc.doctype=='Delivery Note':
            parent,detail=original_stock(mra,row)
            source_cost(mra,row)  # Refuse missing/zero original stock cost before native posting.
            if parent.doctype!='Delivery Note' or doc.return_against!=parent.name or row.dn_detail!=detail.name:
                frappe.throw(_('Use a return against the exact original Delivery Note and row.'))
        elif doc.doctype=='Stock Entry':
            parent,detail=original_stock(mra,row)
            if parent.doctype!='Sales Invoice':frappe.throw(_('Use the original Delivery Note return where available.'))
            expected=source_cost(mra,row)
            if abs(flt(row.basic_rate)-expected)>0.0001 or row.get('allow_zero_valuation_rate'):
                frappe.throw(_('Stock receipt must use the original outgoing cost, not selling price or zero.'))
        else:
            if flt(row.get('rejected_qty')):frappe.throw(_('Receive all arrivals into Pending QC; classify them afterwards in Quality Inspection.'))
            if abs(flt(row.rate)-flt(line.net_rate))>0.01:
                frappe.throw(_('Purchase arrival uses the confirmed acquisition rate. Invoice differences require Finance review.'))
    validate_logistics(doc,mra)


def validate_logistics(doc,mra):
    old=doc.get_doc_before_save()
    fields=tuple('custom_return_'+f for f in LOGISTICS)
    if old and service.state(mra)=='Closed':service.immutable(doc,old,fields)
    if not old and doc.custom_return_freight_finalized:service.require_roles(*service.FINANCE)
    if old and service.changed(doc,old,fields):
        # Operational notice fields are owned by warehouse; monetary evidence by Finance.
        if any(doc.get('custom_return_'+f)!=old.get('custom_return_'+f) for f in ('actual_freight','customer_freight','freight_bill','freight_finalized','freight_responsibility','allocation_reason')):
            service.require_roles(*service.FINANCE)
        else:service.require_roles(*service.STOCK,*service.FINANCE,service.MD)
        if service.state(mra) in service.SIGNED_STATES:
            service.immutable(doc,old,tuple('custom_return_'+f for f in ('actual_freight','customer_freight','freight_bill','freight_finalized','freight_responsibility','allocation_reason')))
    if not doc.custom_return_responsible_user:doc.custom_return_responsible_user=frappe.session.user
    if not doc.custom_return_due_date:doc.custom_return_due_date=service.due(today(),'inspection_days')
    if doc.custom_return_freight_finalized:
        from .policy import freight_split
        doc.custom_return_customer_freight=float(freight_split(doc.custom_return_actual_freight,doc.custom_return_freight_responsibility or 'SNRG',doc.custom_return_customer_freight))
        if flt(doc.custom_return_actual_freight):
            if not doc.custom_return_freight_bill:frappe.throw(_('Link the actual transporter bill before finalizing freight.'))
            bill=service.read_doc('Purchase Invoice',doc.custom_return_freight_bill)
            if bill.docstatus!=1 or bill.is_return or bill.company!=doc.company or bill.currency!=mra.currency or bill.supplier!=doc.custom_return_transporter:
                frappe.throw(_('Actual freight bill must match the submitted transporter bill in this company.'))
            if flt(doc.custom_return_actual_freight)>flt(bill.grand_total)+0.01:frappe.throw(_('Freight allocation exceeds the actual bill.'))
        if doc.custom_return_freight_responsibility=='Shared' and not doc.custom_return_allocation_reason:frappe.throw(_('Explain shared freight.'))
    from .policy import rejection_deadlines
    if doc.custom_return_rejection_notice_date:
        if not doc.custom_return_findings_notice:frappe.throw(_('Attach the rejection notice.'))
        disputed=doc.custom_return_dispute_status=='Resolved'
        if disputed and (not doc.custom_return_resolved_on or not doc.custom_return_resolution):frappe.throw(_('Record dispute resolution and date.'))
        deadlines=rejection_deadlines(doc.custom_return_rejection_notice_date,doc.custom_return_resolved_on if disputed else None)
        doc.custom_return_dispute_deadline,doc.custom_return_collection_deadline=deadlines
    # Server-only disposal signature; a checkbox/string entered by a user is not approval.
    if old:service.immutable(doc,old,('custom_return_disposal_approved_by','custom_return_disposal_approved_on'))
    elif doc.custom_return_disposal_approved_by or doc.custom_return_disposal_approved_on:frappe.throw(_('Disposal signature is server controlled.'))


def validate_qi(doc):
    service.require_roles(*service.QC)
    arrival=service.read_doc(doc.reference_type,doc.reference_name)
    if not is_arrival(arrival) or arrival.docstatus!=1 or not arrival.custom_return_documents_complete:
        frappe.throw(_('Inspect a submitted native arrival with complete receipt documents.'))
    mra=service.read_doc('Material Return Authorization',arrival.custom_return_mra)
    if not enabled(mra) or service.state(mra) not in ('Authorized','Exceptions Approved'):
        frappe.throw(_('Return the case to receipt/QC before changing inspection evidence.'))
    source=next((x for x in arrival.items if x.name==doc.child_row_reference and x.item_code==doc.item_code),None)
    if not source:frappe.throw(_('Select the exact native arrival row.'))
    if frappe.db.exists('Quality Inspection',dict(reference_type=doc.reference_type,reference_name=doc.reference_name,
        child_row_reference=source.name,docstatus=['<',2],name=['!=',doc.name])):frappe.throw(_('Use the existing active inspection for this receipt row.'))
    doc.custom_return_mra=mra.name;doc.company=mra.company
    if not doc.custom_return_allocations:frappe.throw(_('Classify every received quantity.'))
    total=0
    for row in doc.custom_return_allocations:
        service.positive(row.qty);total+=flt(row.qty)
        if row.decision=='Accept' and row.finding in ('Fresh / Saleable','Customer Damage','Unsellable') and not row.exception_reason:
            frappe.throw(_('Explain exceptional commercial acceptance.'))
    if total>abs(flt(source.qty))+0.000001 or (doc.docstatus==1 and abs(total-abs(flt(source.qty)))>0.000001):
        frappe.throw(_('QC allocations must equal the physically posted arrival quantity.'))


class ReturnQualityAdapter:
    def validate_inspection_required(self):
        if self.reference_type in ARRIVALS and self.reference_name:
            parent=frappe.get_doc(self.reference_type,self.reference_name)
            if is_arrival(parent):
                validate_qi(self);return
        return super().validate_inspection_required()

    def validate_not_used_by_submitted_document(self):
        if self.reference_type in ARRIVALS and self.reference_name:
            parent=frappe.get_doc(self.reference_type,self.reference_name)
            if is_arrival(parent):
                service.quality_before_cancel(self);ensure_no_disposition(self.custom_return_mra,self.name);return
        return super().validate_not_used_by_submitted_document()


def ensure_no_disposition(mra,qi=None):
    for dt in ('Stock Entry','Purchase Receipt'):
        for name in frappe.get_all(dt,filters=dict(custom_return_mra=mra,custom_return_purpose='Disposition',docstatus=1),pluck='name'):
            doc=frappe.get_doc(dt,name)
            if not qi or any(x.custom_return_qi==qi for x in doc.items):frappe.throw(_('Reverse posted stock dispositions before changing receipt or QC evidence.'))


def movement_totals(mra):
    totals=defaultdict(float)
    for name in frappe.get_all('Stock Entry',filters=dict(custom_return_mra=mra.name,custom_return_purpose='Disposition',docstatus=1),pluck='name'):
        doc=frappe.get_doc('Stock Entry',name)
        for row in doc.items:totals[(row.custom_return_qi,row.custom_return_allocation)]+=flt(row.qty)
    for name in frappe.get_all('Purchase Receipt',filters=dict(custom_return_mra=mra.name,custom_return_purpose='Disposition',docstatus=1),pluck='name'):
        for row in frappe.get_doc('Purchase Receipt',name).items:totals[(row.custom_return_qi,row.custom_return_allocation)]+=abs(flt(row.qty))
    return totals


def validate_disposition(doc,mra):
    purchase_return=doc.doctype=='Purchase Receipt' and doc.is_return
    if not purchase_return and (doc.doctype!='Stock Entry' or doc.purpose not in ('Material Transfer','Material Issue')):
        frappe.throw(_('Use native Material Transfer or Material Issue for QC disposition.'))
    data=context(mra);service.require_complete_qc(data)
    if data['exceptions'] and mra.exception_fingerprint!=service.exception_digest(data):frappe.throw(_('Obtain MD acceptance of the commercial exceptions.'))
    if service.state(mra) not in ('Authorized','Exceptions Approved','Finance Review','Settlement Approved','Settled'):
        frappe.throw(_('The return case is not open for stock disposition.'))
    lock_allocations(doc)
    lookup={(x['qi'].name,x['allocation'].name):x for x in data['allocations']};totals=movement_totals(mra)
    if doc.docstatus==1 and not doc.is_new() and frappe.db.get_value(doc.doctype,doc.name,'docstatus')==1:
        for row in doc.items:totals[(row.custom_return_qi,row.custom_return_allocation)]-=abs(flt(row.qty))
    for row in doc.items:
        key=(row.custom_return_qi,row.custom_return_allocation);entry=lookup.get(key)
        if not entry or (not purchase_return and flt(row.qty)<=0) or (purchase_return and flt(row.qty)>=0):frappe.throw(_('Every movement requires its submitted QC allocation and correct quantity sign.'))
        totals[key]+=abs(flt(row.qty))
        if totals[key]>flt(entry['allocation'].qty)+0.000001:frappe.throw(_('QC allocation has already been moved or this movement exceeds it.'))
        if (row.warehouse if purchase_return else row.s_warehouse)!=mra.return_warehouse:frappe.throw(_('Disposition must leave this case’s Returns quarantine warehouse.'))
        if not purchase_return and doc.purpose=='Material Transfer':
            if entry['allocation'].decision=='Reject':frappe.throw(_('Commercially rejected goods must stay quarantined until collection, return or approved disposal.'))
            target=service.read_doc('Warehouse',row.t_warehouse)
            if target.company!=mra.company or target.is_group or target.custom_returns_quarantine or row.t_warehouse==mra.return_warehouse:
                frappe.throw(_('Select a separate non-quarantine destination warehouse in this company.'))
        elif entry['allocation'].decision!='Reject':
            frappe.throw(_('Material Issue is only for commercially rejected goods; accepted goods need a warehouse transfer.'))
        if purchase_return or doc.purpose=='Material Issue':
            if mra.route=='Customer Invoice' and not purchase_return:frappe.throw(_('Return refused purchased goods through a Purchase Return against the arrival receipt.'))
            if purchase_return and (doc.return_against!=entry['receipt'].name or row.purchase_receipt_item!=entry['received'].name):frappe.throw(_('Purchase Return must reference the exact arrival row.'))
            receipt=service.read_doc(entry['receipt'].doctype,entry['receipt'].name)
            if not receipt.custom_return_disposition_evidence:frappe.throw(_('Attach collection/dispatch/disposal evidence before issuing rejected stock.'))
            if receipt.custom_return_disposition=='Disposed' and not receipt.custom_return_disposal_approved_by:
                frappe.throw(_('Written customer instructions and designated MD disposal approval are required.'))
            if receipt.custom_return_disposition not in ('Collected','Returned to Customer','Disposed'):frappe.throw(_('Record the rejected-goods disposition.'))


def guard_quarantine(doc,method=None):
    """Block ordinary dispatch or stock consumption from quarantine, including untagged documents."""
    if doc.docstatus==2:return
    source=[]
    if doc.doctype in ('Delivery Note','Sales Invoice') and not doc.get('is_return'):
        source=[x.warehouse for x in doc.items]
    elif doc.doctype in ('Purchase Receipt','Purchase Invoice') and doc.get('is_return') and (doc.doctype=='Purchase Receipt' or doc.get('update_stock')):
        source=[x.warehouse for x in doc.items]
    elif doc.doctype=='Stock Entry':source=[x.s_warehouse for x in doc.items if x.s_warehouse]
    for warehouse in source:
        if frappe.get_cached_value('Warehouse',warehouse,'custom_returns_quarantine'):
            if not (doc.doctype in ('Stock Entry','Purchase Receipt') and doc.get('custom_return_mra') and doc.get('custom_return_purpose')=='Disposition'):
                frappe.throw(_('Returns quarantine stock cannot be dispatched or consumed. Use an inspected MRA disposition transfer first.'))


def validate_document(doc,mra,preliminary=False):
    if is_arrival(doc):validate_arrival(doc,mra);return
    if doc.custom_return_purpose=='Disposition':validate_disposition(doc,mra);return
    if doc.doctype not in ('Sales Invoice','Purchase Invoice'):frappe.throw(_('New return stock is posted only through the arrival document.'))
    if doc.update_stock:frappe.throw(_('Arrival already posted stock. Settlement invoices must have Update Stock cleared.'))
    if service.state(mra)!='Settlement Approved':frappe.throw(_('Finance approval is required before settlement posting.'))
    if doc.doctype=='Sales Invoice':
        if mra.route!='SNRG Credit Note' or not doc.is_return or doc.customer!=mra.customer:frappe.throw(_('Use this customer’s native credit note.'))
    elif mra.route!='Customer Invoice' or doc.is_return or doc.supplier!=mra.supplier:frappe.throw(_('Use the mapped supplier’s native invoice.'))
    data=context(mra);service.require_complete_qc(data)
    if data['exceptions'] and mra.exception_fingerprint!=service.exception_digest(data):frappe.throw(_('Obtain MD exception approval.'))
    lookup={(x['qi'].name,x['allocation'].name):x for x in data['allocations'] if x['allocation'].decision=='Accept'}
    lock_allocations(doc)
    totals=defaultdict(float)
    for other in frappe.get_all(doc.doctype,filters=dict(custom_return_mra=mra.name,custom_return_purpose='Goods Return',docstatus=1,name=['!=',doc.name]),pluck='name'):
        for row in frappe.get_doc(doc.doctype,other).items:totals[(row.custom_return_qi,row.custom_return_allocation)]+=abs(flt(row.qty))
    for row in doc.items:
        key=(row.custom_return_qi,row.custom_return_allocation);entry=lookup.get(key)
        if not entry or (row.item_code,row.uom)!=(entry['received'].item_code,entry['received'].uom):frappe.throw(_('Settlement rows must match accepted native QC allocations.'))
        if (doc.doctype=='Sales Invoice' and flt(row.qty)>=0) or (doc.doctype=='Purchase Invoice' and flt(row.qty)<=0):frappe.throw(_('Invalid settlement quantity sign.'))
        totals[key]+=abs(flt(row.qty))
        if totals[key]>flt(entry['allocation'].qty)+0.000001:frappe.throw(_('Accepted quantity has already been invoiced or exceeds QC acceptance.'))
        if not preliminary and abs(flt(row.net_rate)-service.rate_for(mra,entry))>0.01:frappe.throw(_('Settlement price must match confirmed original net invoice value.'))
        if doc.doctype=='Purchase Invoice' and (row.purchase_receipt,row.pr_detail)!=(entry['receipt'].name,entry['received'].name):
            frappe.throw(_('Supplier invoice must bill its exact posted Purchase Receipt row.'))


def reconcile(mra,data):
    allowed={(x.document_type,x.document_name) for x in mra.stock_references}
    for receipt in data['receipts']:
        if (receipt.doctype,receipt.name) not in allowed:frappe.throw(_('Link every posted native arrival in Stock References.'))
    # The settlement must cover each accepted allocation exactly once; matching totals
    # alone must not let one accepted row replace another.
    billed=defaultdict(float)
    for ref in mra.accounting_documents:
        if ref.purpose=='Settlement':
            for row in service.read_doc(ref.document_type,ref.document_name).items:
                billed[(row.custom_return_qi,row.custom_return_allocation)]+=abs(flt(row.qty))
    for entry in data['allocations']:
        expected=flt(entry['allocation'].qty) if entry['allocation'].decision=='Accept' else 0
        if abs(billed[(entry['qi'].name,entry['allocation'].name)]-expected)>0.000001:
            frappe.throw(_('Settlement quantities must reconcile to each accepted QC allocation exactly once.'))


def close_guard(mra,data):
    totals=movement_totals(mra)
    for entry in data['allocations']:
        key=(entry['qi'].name,entry['allocation'].name)
        if abs(totals[key]-flt(entry['allocation'].qty))>0.000001:
            frappe.throw(_('Move every inspected quantity out of Pending QC before closing: saleable, repair, rejected or disposal.'))


def update_after_submit(doc,method=None):
    old=doc.get_doc_before_save()
    if old and (is_arrival(old) or is_arrival(doc)):
        service.immutable(doc,old,('custom_return_mra','custom_return_purpose'))
    if is_arrival(doc):validate_logistics(doc,service.read_doc('Material Return Authorization',doc.custom_return_mra))


def before_cancel(doc,method=None):
    if not doc.get('custom_return_mra'):return
    mra=service.read_doc('Material Return Authorization',doc.custom_return_mra)
    if not enabled(mra):return
    if is_arrival(doc):
        if frappe.db.exists('Quality Inspection',dict(reference_type=doc.doctype,reference_name=doc.name,docstatus=1)):
            frappe.throw(_('Cancel linked QC before cancelling the stock arrival.'))
        ensure_no_disposition(mra.name)


def lock_allocations(doc):
    if doc.docstatus==1:
        names=sorted({x.get('custom_return_allocation') for x in doc.items if x.get('custom_return_allocation')})
        frappe.db.sql('select name from `tabReturn QC Allocation` where name in %(names)s order by name for update',dict(names=names or ['']))
