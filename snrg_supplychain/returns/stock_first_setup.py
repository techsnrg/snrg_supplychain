"""Native stock-first receipt extensions. No ledger or historical data migration."""
import json
from pathlib import Path
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ARRIVALS = ('Delivery Note', 'Purchase Receipt', 'Stock Entry')
CHILDREN = {'Delivery Note':'Delivery Note Item', 'Purchase Receipt':'Purchase Receipt Item', 'Stock Entry':'Stock Entry Detail'}
LOGISTICS = ('documents_complete','responsible_user','arranged_by','paid_by','transporter','consignment_note','freight_estimate',
    'actual_freight','customer_freight','freight_responsibility','allocation_reason','freight_bill','freight_finalized',
    'rejection_notice_date','findings_notice','dispute_status','dispute_details','resolved_on','resolution',
    'dispute_deadline','collection_deadline','disposition','customer_disposal_instruction','disposition_evidence',
    'disposal_approved_by','disposal_approved_on','due_date','revised_due_date','delay_reason')


def configure():
    source = json.loads((Path(__file__).parents[1]/'supply_chain/doctype/return_receipt/return_receipt.json').read_text())
    definitions = {f['fieldname']:f for f in source['fields']}
    fields = {'Warehouse':[dict(fieldname='custom_returns_quarantine',label='Returns Quarantine — Block Dispatch',fieldtype='Check',insert_after='warehouse_name')]}
    for dt in ARRIVALS:
        fields[dt]=[dict(fieldname='custom_return_mra',fieldtype='Link',options='Material Return Authorization',label='Material Return Authorization',insert_after='company'),
            dict(fieldname='custom_return_purpose',fieldtype='Select',options='Goods Return\nArrival\nDisposition\nCharge\nFreight\nOffset',label='Return Reference Purpose',insert_after='custom_return_mra'),
            dict(fieldname='custom_return_logistics',fieldtype='Section Break',label='Return arrival, freight and disposition',depends_on="eval:doc.custom_return_purpose == 'Arrival'",insert_after='custom_return_purpose')]
        fields[dt].append(dict(fieldname='custom_return_quality_complete',fieldtype='Check',label='Return QC Complete',read_only=1,insert_after='custom_return_logistics'))
        after='custom_return_quality_complete'
        for name in LOGISTICS:
            f=definitions.get(name,dict(fieldname=name,fieldtype='Data',label=name.replace('_',' ').title()))
            f={k:v for k,v in f.items() if k in ('fieldtype','label','options','default','description')}
            f.update(fieldname='custom_return_'+name,insert_after=after,allow_on_submit=1,depends_on="eval:doc.custom_return_purpose == 'Arrival'")
            if name in ('dispute_deadline','collection_deadline','disposal_approved_by','disposal_approved_on','due_date'):f['read_only']=1
            fields[dt].append(f);after=f['fieldname']
    for dt in (*CHILDREN.values(),'Sales Invoice Item','Purchase Invoice Item'):
        fields[dt]=[dict(fieldname='custom_return_mra_item',fieldtype='Data',label='Authorized MRA Row',insert_after='item_code'),
            dict(fieldname='custom_return_source_invoice',fieldtype='Link',options='Sales Invoice',label='Original Sales Invoice',insert_after='custom_return_mra_item'),
            dict(fieldname='custom_return_source_invoice_item',fieldtype='Data',label='Original Sales Invoice Row',insert_after='custom_return_source_invoice'),
            dict(fieldname='custom_return_qi',fieldtype='Link',options='Quality Inspection',label='Return QC Evidence',insert_after='custom_return_source_invoice_item'),
            dict(fieldname='custom_return_allocation',fieldtype='Data',label='Commercial QC Allocation',insert_after='custom_return_qi')]
    fields['Stock Entry Detail'] += [dict(fieldname='custom_return_stock_cost',fieldtype='Currency',label='Original stock cost',read_only=1,insert_after='custom_return_allocation')]
    create_custom_fields(fields,update=True)
    # Native billing docs already have these fields; extend only our owned select options.
    for dt in ('Sales Invoice','Purchase Invoice','Journal Entry','Payment Entry'):
        name=frappe.db.get_value('Custom Field',{'dt':dt,'fieldname':'custom_return_purpose'},'name')
        if name:frappe.db.set_value('Custom Field',name,'options','Goods Return\nArrival\nDisposition\nCharge\nFreight\nOffset')
    frappe.db.set_value('Custom Field',{'dt':'Quality Inspection','fieldname':'custom_return_section'},'depends_on','eval:doc.custom_return_mra')
    from frappe.permissions import add_permission,update_permission_property
    for dt in ARRIVALS:
        if not frappe.db.exists('Custom DocPerm',{'parent':dt,'role':'Return Reviewer','permlevel':0}):add_permission(dt,'Return Reviewer',0)
        for ptype in ('read','select','report','print'):update_permission_property(dt,'Return Reviewer',0,ptype,1)
    # Native receipt SLAs reuse native assignment/notification machinery.
    from .native_setup import save_owned
    for dt in ARRIVALS:
        save_owned('Assignment Rule','SNRG Returns QC - '+dt,dict(document_type=dt,description='Inspect return: {{ name }}',
            due_date_based_on='custom_return_due_date',priority=20,disabled=0,
            assign_condition="docstatus == 1 and custom_return_purpose == 'Arrival' and not custom_return_quality_complete",close_condition="docstatus == 2 or custom_return_quality_complete",
            rule='Based on Field',field='custom_return_responsible_user',assignment_days=[dict(day=x) for x in ('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')]))
        for label,field,condition in [('QC','custom_return_due_date',"doc.docstatus == 1 and doc.custom_return_purpose == 'Arrival' and not doc.custom_return_quality_complete"),
            ('Collection','custom_return_collection_deadline',"doc.docstatus == 1 and doc.custom_return_purpose == 'Arrival' and doc.custom_return_disposition == 'Pending'")]:
            save_owned('Notification',f'SNRG Return {label} - {dt}',dict(enabled=1,channel='System Notification',subject='Return action due: {{ doc.name }}',
                event='Days After',document_type=dt,date_changed=field,days_in_advance=0,condition=condition,message='Review {{ doc.name }}.',
                recipients=[dict(receiver_by_document_field='custom_return_responsible_user')]))
    for dt in ARRIVALS:
        for name in frappe.get_all(dt,filters={'custom_return_purpose':'Arrival','docstatus':1},pluck='name'):
            parent=frappe.get_doc(dt,name)
            complete=bool(parent.items) and all(frappe.db.exists('Quality Inspection',dict(reference_type=dt,reference_name=name,child_row_reference=row.name,docstatus=1)) for row in parent.items)
            frappe.db.set_value(dt,name,'custom_return_quality_complete',int(complete),update_modified=False)
            if complete:
                frappe.db.set_value(dt,name,'custom_return_due_date',None,update_modified=False)
                for task in frappe.get_all('ToDo',filters={'reference_type':dt,'reference_name':name,'status':'Open','description':['like','Inspect return:%']},pluck='name'):
                    todo=frappe.get_doc('ToDo',task);todo.status='Closed';todo.save(ignore_permissions=True)
    if frappe.db.exists('Workspace','Supply Chain'):
        workspace=frappe.get_doc('Workspace','Supply Chain')
        changed=False
        for field in ('links','shortcuts'):
            rows=workspace.get(field) or []
            if any(x.get('link_to')=='Return Receipt' for x in rows):
                workspace.set(field,[x for x in rows if x.get('link_to')!='Return Receipt']);changed=True
        content=json.loads(workspace.content or '[]')
        filtered=[x for x in content if x.get('data',{}).get('shortcut_name')!='Return Receipt']
        if filtered!=content:workspace.content=json.dumps(filtered);changed=True
        if changed:workspace.save(ignore_permissions=True)
    for dt in ('Sidebar','Workspace Sidebar'):
        if frappe.db.exists('DocType',dt) and frappe.db.exists(dt,'Supply Chain'):
            doc=frappe.get_doc(dt,'Supply Chain')
            if dt=='Workspace Sidebar' and doc.get('for_user'):continue
            if any(x.link_to=='Return Receipt' for x in doc.items):
                doc.set('items',[x for x in doc.items if x.link_to!='Return Receipt']);doc.save(ignore_permissions=True)
    frappe.clear_cache()
