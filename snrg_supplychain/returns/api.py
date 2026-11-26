"""Permission-checked APIs for native ERPNext forms."""
import frappe
from frappe import _
from .native_service import read_doc, remaining, validate_invoice, state


@frappe.whitelist()
def act(doctype, name, action, reason=None):
    """Compatibility endpoint delegates to ERPNext's native workflow engine."""
    from frappe.model.workflow import apply_workflow
    mapping = {
        'request_approval':'Request Approval', 'authorize':'Authorize', 'reject':'Reject',
        'receive':'Confirm Receipt', 'approve_exceptions':'Approve Return Exceptions',
        'prepare_settlement':'Prepare Settlement', 'request_concession':'Request Concession',
        'approve_waiver':'Approve Concession', 'approve_settlement':'Approve Settlement',
        'settle':'Mark Settled', 'close':'Close Return', 'approve_disposal':'Approve Disposal',
    }
    if doctype not in ('Material Return Authorization','Return Receipt'):
        frappe.throw(_('Legacy inspection/settlement actions are retired. Use native QC and MRA Workflow.'))
    doc=read_doc(doctype,name)
    if reason:
        field='closure_reason' if action=='close' else 'exception_reason' if action=='approve_exceptions' else 'approval_reason'
        doc.set(field,reason);doc.save()
    return apply_workflow(doc.as_dict(),mapping.get(action,action)).as_dict()


@frappe.whitelist()
def invoice_sales(company, customer, item_code, uom, currency, invoice=None, start=0):
    frappe.has_permission('Material Return Authorization', 'create', throw=True)
    read_doc('Customer', customer)
    filters = {'company': company, 'customer': customer, 'currency': currency, 'docstatus': 1, 'is_return': 0}
    if invoice:
        filters['name'] = invoice
    # Parent get_list applies user permissions; child data is read only after parent access.
    rows = frappe.get_list('Sales Invoice', filters=filters,
        fields=['name', 'posting_date'], order_by='posting_date desc, creation desc',
        start=max(0, int(start)), page_length=50)
    result = []
    for row in rows:
        sale = read_doc('Sales Invoice', row.name)
        validate_invoice(sale, company, customer, currency)
        for line in sale.items:
            if line.item_code == item_code and line.uom == uom and float(line.qty) > 0:
                available = remaining(sale, line)
                if available > 0:
                    result.append(dict(sales_invoice=sale.name, sales_invoice_item=line.name,
                        invoice_date=str(sale.posting_date), net_rate=line.net_rate,
                        sold_qty=line.qty, remaining_qty=available, currency=sale.currency))
    return {'rows': result, 'next_start': int(start) + 50 if len(rows) == 50 else None}


@frappe.whitelist()
def linked_suppliers(customer):
    read_doc('Customer', customer)
    return frappe.get_list('Supplier', filters={'custom_is_customer': 1,
        'custom_linked_customer': customer, 'disabled': 0}, fields=['name', 'supplier_name'])


@frappe.whitelist()
def customer_history(company, customer, currency):
    frappe.has_permission('Material Return Authorization', 'read', throw=True)
    read_doc('Customer', customer)
    invoices = frappe.get_list('Sales Invoice', filters={'company': company, 'customer': customer,
        'currency': currency, 'docstatus': 1}, fields=['name', 'is_return', 'net_total'], page_length=0)
    purchases = sum(float(x.net_total) for x in invoices if not x.is_return)
    credits = -sum(float(x.net_total) for x in invoices if x.is_return)
    returns = frappe.get_list('Material Return Authorization', filters={'company': company,
        'customer': customer, 'currency': currency}, fields=['name', 'status', 'category_summary', 'approved_value'], page_length=0)
    return dict(currency=currency, purchases=purchases, credited_returns=credits,
        return_percentage=credits / purchases * 100 if purchases else 0, authorizations=returns,
        note='Posted credit-note percentage excludes customer-issued Purchase Invoices; MRA history includes both routes.')


@frappe.whitelist()
def populate(doctype, source, receipt_item=None):
    """Prepare native form drafts without posting stock or accounts."""
    if doctype == 'Return Receipt':
        mra=read_doc('Material Return Authorization',source)
        if int(mra.get('native_returns_version') or 0)>=3:frappe.throw(_('Use a native stock arrival for this case.'))
        frappe.has_permission(doctype,'create',throw=True)
        if state(mra) not in ('Authorized','Exceptions Approved','Finance Review'):
            frappe.throw(_('Use an active MD-authorized case.'))
        quantities=dict(frappe.db.sql("""select i.mra_item,sum(i.received_qty) from `tabReturn Receipt Item` i
            join `tabReturn Receipt` p on p.name=i.parent where p.authorization=%s and p.status!='Draft' group by i.mra_item""",mra.name))
        return dict(doctype=doctype,authorization=mra.name,company=mra.company,customer=mra.customer,
            currency=mra.currency,responsible_user=frappe.session.user,freight_estimate=mra.freight_estimate,
            items=[dict(mra_item=x.name,item_code=x.item_code,uom=x.uom,
                received_qty=max(0,float(x.approved_qty or 0)-float(quantities.get(x.name) or 0)))
                for x in mra.items if float(x.approved_qty or 0)>float(quantities.get(x.name) or 0)])
    if doctype=='Quality Inspection':
        receipt=read_doc('Return Receipt',source)
        frappe.has_permission(doctype,'create',throw=True)
        row=next((x for x in receipt.items if x.name==receipt_item),None)
        if not row:
            frappe.throw(_('Select the exact custody item to inspect.'))
        existing=frappe.db.get_value('Quality Inspection',{'reference_type':'Return Receipt','reference_name':receipt.name,
            'child_row_reference':row.name,'docstatus':['<',2]},'name')
        if existing:return dict(existing=existing,doctype='Quality Inspection')
        return dict(doctype=doctype,company=receipt.company,inspection_type='Incoming',reference_type='Return Receipt',
            reference_name=receipt.name,child_row_reference=row.name,custom_return_mra=receipt.authorization,
            custom_return_receipt=receipt.name,custom_return_receipt_item=row.name,item_code=row.item_code,
            batch_no=row.batch_no,sample_size=row.received_qty,inspected_by=frappe.session.user,
            custom_return_allocations=[dict(qty=row.received_qty)])
    frappe.throw(_('New cases use MRA settlement and native Quality Inspection.'))


@frappe.whitelist()
def approval_context():
    frappe.has_permission('Material Return Authorization', 'read', throw=True)
    return {'settlement_role': frappe.db.get_single_value('Return Settings', 'settlement_approver_role') or 'Accounts Manager'}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def custody_item_query(doctype,txt,searchfield,start,page_len,filters):
    receipt=read_doc('Return Receipt',filters.get('receipt'))
    codes=list({x.item_code for x in receipt.items})
    return frappe.get_list('Item',filters={'name':['in',codes],'item_code':['like','%'+txt+'%']},
        fields=['name','item_name'],start=start,page_length=page_len,as_list=True)


@frappe.whitelist()
def native_document_options(authorization):
    mra=read_doc('Material Return Authorization',authorization)
    if state(mra)!='Settlement Approved':
        frappe.throw(_('Approve the settlement through Workflow first.'))
    if int(mra.get('native_returns_version') or 0)>=3:
        if mra.route=='SNRG Credit Note':
            return [dict(label='Credit Note only — stock already received: '+x,doctype='Sales Invoice',invoice=x,update_stock=0) for x in dict.fromkeys(r.sales_invoice for r in mra.settlement_items)]
        return [dict(label='Purchase Invoice only — stock already received',doctype='Purchase Invoice',update_stock=0)]
    if mra.route=='SNRG Credit Note':
        options=[]
        for invoice in dict.fromkeys(x.sales_invoice for x in mra.settlement_items):
            options += [dict(label='Credit Note + stock return against '+invoice,doctype='Sales Invoice',invoice=invoice,update_stock=1),
                dict(label='Credit Note only against '+invoice,doctype='Sales Invoice',invoice=invoice,update_stock=0)]
        return options
    return [dict(label='Purchase Receipt into returns warehouse',doctype='Purchase Receipt'),
        dict(label='Purchase Invoice (receives stock if no Purchase Receipt exists)',doctype='Purchase Invoice')]


@frappe.whitelist()
def native_document(authorization,doctype,invoice=None,update_stock=1):
    from frappe.utils import today,cint
    mra=read_doc('Material Return Authorization',authorization)
    if state(mra)!='Settlement Approved':
        frappe.throw(_('Finance approval is required before creating settlement documents.'))
    if int(mra.get('native_returns_version') or 0)>=3:
        from .stock_first_api import settlement
        return settlement(authorization,doctype,invoice)
    if doctype not in ('Sales Invoice','Purchase Receipt','Purchase Invoice'):
        frappe.throw(_('Use a supported native return/receipt document.'))
    frappe.has_permission(doctype,'create',throw=True)
    lines=list(mra.settlement_items)
    if doctype=='Sales Invoice':
        if mra.route!='SNRG Credit Note':frappe.throw(_('Select the credit-note route.'))
        source=read_doc('Sales Invoice',invoice)
        validate_invoice(source,mra.company,mra.customer,mra.currency)
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
        doc=make_sales_return(source.name)
        mapped={x.sales_invoice_item:x.as_dict() for x in doc.items}
        doc.set('items',[])
        for line in lines:
            if line.sales_invoice!=invoice:continue
            values=mapped.get(line.sales_invoice_item)
            if not values:frappe.throw(_('Original invoice row could not be mapped.'))
            values={k:v for k,v in values.items() if k not in ('name','parent','parenttype','parentfield','idx','doctype','creation','modified','owner','docstatus')}
            values.update(qty=-line.qty,warehouse=mra.return_warehouse,quality_inspection=None,
                custom_return_qi=line.quality_inspection,custom_return_allocation=line.allocation_row)
            doc.append('items',values)
        doc.update_stock=cint(update_stock)
    else:
        if mra.route!='Customer Invoice':frappe.throw(_('Select the customer-invoice route.'))
        receipts=frappe.get_list('Purchase Receipt',filters={'custom_return_mra':mra.name,'docstatus':1},fields=['name'],page_length=2)
        if doctype=='Purchase Invoice' and receipts:
            if len(receipts)>1:frappe.throw(_('Create the native Purchase Invoice from the appropriate receipts and link the MRA.'))
            from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice
            doc=make_purchase_invoice(receipts[0].name)
            doc.update_stock=0
        else:
            doc=frappe.new_doc(doctype)
            doc.update(dict(company=mra.company,supplier=mra.supplier,currency=mra.currency,posting_date=today()))
            if doctype=='Purchase Invoice':doc.update_stock=1
            for line in lines:
                doc.append('items',dict(item_code=line.item_code,qty=line.qty,rate=line.net_rate,
                    uom=next(x.uom for x in frappe.get_doc('Return Receipt',line.receipt).items
                        if x.name==frappe.get_doc('Quality Inspection',line.quality_inspection).child_row_reference),
                    warehouse=mra.return_warehouse,custom_return_qi=line.quality_inspection,custom_return_allocation=line.allocation_row))
        if doctype=='Purchase Invoice':
            doc.bill_no,doc.bill_date=mra.customer_invoice_number,mra.customer_invoice_date
    doc.custom_return_mra=mra.name
    doc.custom_return_purpose='Goods Return'
    return doc.as_dict()


@frappe.whitelist()
def arrival_options(authorization):
    from .stock_first_api import options
    return options(authorization)


@frappe.whitelist()
def stock_arrival(authorization,doctype,source=None):
    from .stock_first_api import arrival
    return arrival(authorization,doctype,source)


@frappe.whitelist()
def arrival_inspection(doctype,name,receipt_item):
    from .stock_first_api import inspection
    return inspection(doctype,name,receipt_item)


@frappe.whitelist()
def stock_disposition(authorization,quality_inspection,allocation,target_warehouse=None):
    from .stock_first_api import disposition
    return disposition(authorization,quality_inspection,allocation,target_warehouse)


@frappe.whitelist()
def approve_native_disposal(doctype,name):
    from frappe.utils import now_datetime
    from .native_service import require_roles,MD
    from .stock_first import ARRIVALS,is_arrival
    require_roles(MD)
    if doctype not in ARRIVALS:frappe.throw(_('Select a native return arrival.'))
    doc=read_doc(doctype,name)
    if not is_arrival(doc) or doc.docstatus!=1 or not doc.custom_return_customer_disposal_instruction:
        frappe.throw(_('Attach written customer disposal instructions to the submitted return arrival.'))
    mra=read_doc('Material Return Authorization',doc.custom_return_mra)
    if state(mra) in ('Closed','Rejected'):frappe.throw(_('Reopen the case before changing disposal approval.'))
    doc.db_set({'custom_return_disposal_approved_by':frappe.session.user,'custom_return_disposal_approved_on':now_datetime()})
    doc.add_comment('Info','MD approved disposal against written customer instructions.')
    return frappe.get_doc(doctype,name).as_dict()


@frappe.whitelist()
def disposition_options(authorization):
    from .stock_first_api import case
    from .stock_first import context,movement_totals
    mra=case(authorization);totals=movement_totals(mra)
    return [dict(qi=x['qi'].name,allocation=x['allocation'].name,
        label=f"{x['received'].item_code} · {x['allocation'].decision} · {float(x['allocation'].qty)-totals[(x['qi'].name,x['allocation'].name)]:g} · {x['qi'].name}")
        for x in context(mra)['allocations'] if float(x['allocation'].qty)>totals[(x['qi'].name,x['allocation'].name)]]
