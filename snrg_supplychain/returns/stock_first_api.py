"""Native drafts only. Users review and submit through standard ERPNext forms."""
import frappe
from frappe import _
from frappe.utils import flt,today,now_datetime
from . import native_service as service
from .stock_first import enabled,original_stock,source_cost,cumulative_received,context,ARRIVALS,is_arrival


def case(name):
    mra=service.read_doc('Material Return Authorization',name)
    if not enabled(mra):frappe.throw(_('Use the legacy case’s original receipt path.'))
    service.valid_authorization(mra)
    return mra


def options(name):
    mra=case(name);result=[]
    for row in mra.items:
        probe=frappe._dict(item_code=row.item_code,uom=row.uom,custom_return_mra_item=row.name,
            custom_return_source_invoice=row.sales_invoice,custom_return_source_invoice_item=row.sales_invoice_item)
        if mra.route=='Customer Invoice':kind,source='Purchase Receipt',None
        else:
            parent,_=original_stock(mra,probe)
            kind,source=('Delivery Note',parent.name) if parent.doctype=='Delivery Note' else ('Stock Entry',parent.name)
        if not any(x['doctype']==kind and x['source']==source for x in result):
            result.append(dict(doctype=kind,source=source,label=f'{kind} — '+(source or 'customer-supplier receipt')))
    return result


def arrival(name,doctype,source=None):
    mra=case(name)
    if service.state(mra) not in ('Authorized','Exceptions Approved'):frappe.throw(_('Receive on an open authorized MRA.'))
    if not mra.return_warehouse:frappe.throw(_('Finance must select the Returns quarantine warehouse on the MRA first.'))
    choice=next((x for x in options(name) if x['doctype']==doctype and x['source']==source),None)
    if not choice:frappe.throw(_('Choose an eligible native arrival source.'))
    frappe.has_permission(doctype,'create',throw=True)
    from collections import defaultdict
    from .stock_first import arrival_docs
    used=defaultdict(float)
    for posted in arrival_docs(mra,True):
        for item in posted.items:used[item.custom_return_mra_item]+=abs(flt(item.qty))
    if doctype=='Delivery Note':
        from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_return
        doc=make_sales_return(source);mapped={x.dn_detail:x.as_dict() for x in doc.items};doc.set('items',[])
    else:
        doc=frappe.new_doc(doctype);doc.company=mra.company
        if doctype=='Stock Entry':doc.stock_entry_type=doc.purpose='Material Receipt'
        else:doc.supplier=mra.supplier;doc.currency=mra.currency
    for row in mra.items:
        qty=max(0,flt(row.approved_qty)-used[row.name])
        if not qty:continue
        values=dict(item_code=row.item_code,uom=row.uom,qty=qty,custom_return_mra_item=row.name,
            custom_return_source_invoice=row.sales_invoice,custom_return_source_invoice_item=row.sales_invoice_item)
        invoice=service.read_doc('Sales Invoice',row.sales_invoice)
        line=next(x for x in invoice.items if x.name==row.sales_invoice_item)
        values.update(conversion_factor=line.conversion_factor,stock_uom=line.stock_uom)
        probe=frappe._dict(values)
        if doctype=='Purchase Receipt':values.update(rate=row.net_rate,warehouse=mra.return_warehouse)
        else:
            parent,detail=original_stock(mra,probe)
            if parent.name!=source:continue
            if doctype=='Delivery Note':
                original=mapped.get(detail.name)
                if not original:frappe.throw(_('Original delivery row has no remaining native return quantity.'))
                clean={k:v for k,v in original.items() if k not in ('doctype','name','parent','parenttype','parentfield','idx','docstatus','creation','modified','owner')}
                clean.update(values);values=clean;values.update(qty=-qty,warehouse=mra.return_warehouse,quality_inspection=None)
            else:
                cost=source_cost(mra,probe)
                values.update(t_warehouse=mra.return_warehouse,basic_rate=cost,custom_return_stock_cost=cost,
                    expense_account=detail.get('expense_account') or frappe.get_cached_value('Company',mra.company,'stock_adjustment_account'))
        doc.append('items',values)
    if not doc.items:frappe.throw(_('No approved quantities remain for this arrival. Enter excess only against an eligible original sold row.'))
    doc.custom_return_mra=mra.name;doc.custom_return_purpose='Arrival'
    doc.custom_return_responsible_user=frappe.session.user;doc.custom_return_freight_estimate=mra.freight_estimate
    return doc.as_dict()


def inspection(doctype,name,rowname):
    parent=service.read_doc(doctype,name)
    if not is_arrival(parent) or parent.docstatus!=1:frappe.throw(_('Select a submitted native arrival.'))
    case(parent.custom_return_mra);frappe.has_permission('Quality Inspection','create',throw=True)
    row=next((x for x in parent.items if x.name==rowname),None)
    if not row:frappe.throw(_('Select the exact native receipt row.'))
    existing=frappe.db.get_value('Quality Inspection',dict(reference_type=doctype,reference_name=name,child_row_reference=rowname,docstatus=['<',2]),'name')
    if existing:return dict(existing=existing,doctype='Quality Inspection')
    return dict(doctype='Quality Inspection',company=parent.company,inspection_type='Incoming',reference_type=doctype,reference_name=name,
        child_row_reference=row.name,item_code=row.item_code,batch_no=row.get('batch_no'),sample_size=abs(flt(row.qty)),
        inspected_by=frappe.session.user,custom_return_mra=parent.custom_return_mra,custom_return_allocations=[dict(qty=abs(flt(row.qty)))])


def settlement(name,doctype,invoice=None):
    mra=case(name)
    if service.state(mra)!='Settlement Approved':frappe.throw(_('Finance must approve the settlement first.'))
    frappe.has_permission(doctype,'create',throw=True)
    data=context(mra);lookup={(x['qi'].name,x['allocation'].name):x for x in data['allocations']}
    if doctype=='Sales Invoice' and mra.route=='SNRG Credit Note':
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
        doc=make_sales_return(invoice);mapped={x.sales_invoice_item:x.as_dict() for x in doc.items};doc.set('items',[])
        for line in mra.settlement_items:
            if line.sales_invoice!=invoice:continue
            values=dict(mapped[line.sales_invoice_item]);values.pop('name',None)
            values.update(qty=-line.qty,warehouse=mra.return_warehouse,quality_inspection=None,
                custom_return_qi=line.quality_inspection,custom_return_allocation=line.allocation_row)
            doc.append('items',values)
    elif doctype=='Purchase Invoice' and mra.route=='Customer Invoice':
        doc=frappe.new_doc(doctype);doc.company=mra.company;doc.supplier=mra.supplier;doc.currency=mra.currency
        doc.bill_no=mra.customer_invoice_number;doc.bill_date=mra.customer_invoice_date
        for line in mra.settlement_items:
            entry=lookup[(line.quality_inspection,line.allocation_row)]
            doc.append('items',dict(item_code=line.item_code,uom=entry['received'].uom,qty=line.qty,rate=line.net_rate,
                warehouse=mra.return_warehouse,purchase_receipt=entry['receipt'].name,pr_detail=entry['received'].name,
                custom_return_qi=line.quality_inspection,custom_return_allocation=line.allocation_row))
    else:frappe.throw(_('Select the non-stock settlement invoice for this route.'))
    doc.update_stock=0;doc.custom_return_mra=mra.name;doc.custom_return_purpose='Goods Return'
    return doc.as_dict()


def disposition(name,qi,allocation,target=None):
    mra=case(name);frappe.has_permission('Stock Entry','create',throw=True)
    entry=next((x for x in context(mra)['allocations'] if x['qi'].name==qi and x['allocation'].name==allocation),None)
    if not entry:frappe.throw(_('Select a submitted QC allocation from this case.'))
    from .stock_first import movement_totals
    qty=flt(entry['allocation'].qty)-movement_totals(mra)[(qi,allocation)]
    if qty<=0:frappe.throw(_('This QC quantity has already been moved.'))
    if not target and entry['allocation'].decision!='Reject':frappe.throw(_('Choose a destination warehouse for accepted goods.'))
    received=entry['received']
    item_details=dict(item_code=received.item_code,uom=received.uom,stock_uom=received.stock_uom,
        conversion_factor=received.conversion_factor,custom_return_qi=qi,custom_return_allocation=allocation)
    if not target and mra.route=='Customer Invoice':
        from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_return
        doc=make_purchase_return(entry['receipt'].name);mapped=next(x.as_dict() for x in doc.items if x.purchase_receipt_item==received.name);doc.set('items',[])
        mapped.pop('name',None);mapped.update(item_details,qty=-qty,received_qty=-qty,rejected_qty=0,warehouse=mra.return_warehouse)
        doc.append('items',mapped);doc.custom_return_mra=name;doc.custom_return_purpose='Disposition'
        return doc.as_dict()
    doc=frappe.new_doc('Stock Entry');doc.company=mra.company;doc.stock_entry_type=doc.purpose='Material Transfer' if target else 'Material Issue'
    doc.custom_return_mra=name;doc.custom_return_purpose='Disposition'
    doc.append('items',dict(item_details,qty=qty,s_warehouse=mra.return_warehouse,t_warehouse=target))
    return doc.as_dict()
