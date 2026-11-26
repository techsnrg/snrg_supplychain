"""Idempotent native configuration and non-destructive legacy migration."""
import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from .setup import TERMS

MRA='Material Return Authorization'
MRA_WORKFLOW='SNRG Return Case Workflow'
RECEIPT_WORKFLOW='SNRG Return Custody Workflow'


def ensure_fields():
    fields={
        'Supplier':[dict(fieldname='custom_is_customer',label='Is Also a Customer',fieldtype='Check',insert_after='supplier_name'),
            dict(fieldname='custom_linked_customer',label='Linked Customer',fieldtype='Link',options='Customer',insert_after='custom_is_customer',
                 depends_on='eval:doc.custom_is_customer',mandatory_depends_on='eval:doc.custom_is_customer')],
        'Quality Inspection':[
            dict(fieldname='custom_return_section',fieldtype='Section Break',label='Return custody and commercial disposition',depends_on='eval:doc.reference_type == \"Return Receipt\"',insert_after='remarks'),
            dict(fieldname='custom_return_mra',fieldtype='Link',options=MRA,label='Material Return Authorization',read_only=1,insert_after='custom_return_section'),
            dict(fieldname='custom_return_receipt',fieldtype='Link',options='Return Receipt',label='Custody Receipt',read_only=1,insert_after='custom_return_mra'),
            dict(fieldname='custom_return_receipt_item',fieldtype='Data',label='Custody Item Row',read_only=1,insert_after='custom_return_receipt'),
            dict(fieldname='custom_return_allocations',fieldtype='Table',options='Return QC Allocation',label='Commercial quantity disposition',insert_after='custom_return_receipt_item'),
            dict(fieldname='custom_legacy_inspection',fieldtype='Link',options='Return Inspection',label='Legacy Inspection',read_only=1,insert_after='custom_return_allocations')],
    }
    for dt in ('Delivery Note','Sales Invoice','Purchase Receipt','Purchase Invoice','Journal Entry','Payment Entry','Shipment'):
        meta=frappe.get_meta(dt)
        first=next(x.fieldname for x in meta.fields if x.fieldtype not in ('Section Break','Column Break','Tab Break','HTML'))
        fields[dt]=[
            dict(fieldname='custom_return_mra',fieldtype='Link',options=MRA,label='Material Return Authorization',insert_after=first,allow_on_submit=1),
            dict(fieldname='custom_return_purpose',fieldtype='Select',options='Goods Return\nArrival\nDisposition\nCharge\nFreight\nOffset',label='Return Reference Purpose',default='Goods Return',
                 depends_on='eval:doc.custom_return_mra',insert_after='custom_return_mra',allow_on_submit=1)]
    fields['Shipment'] += [dict(fieldname='custom_return_receipt',fieldtype='Link',options='Return Receipt',label='Custody Receipt',insert_after='custom_return_purpose'),
        dict(fieldname='custom_return_transporter',fieldtype='Link',options='Supplier',label='Transporter Supplier',insert_after='custom_return_receipt'),
        dict(fieldname='custom_return_direction',fieldtype='Select',options='Inward\nRejected Goods Return',default='Inward',label='Return Transport Direction',insert_after='custom_return_transporter')]
    for dt in ('Delivery Note Item','Sales Invoice Item','Purchase Receipt Item','Purchase Invoice Item'):
        fields[dt]=[dict(fieldname='custom_return_qi',fieldtype='Link',options='Quality Inspection',label='Return QC Evidence',insert_after='item_code'),
            dict(fieldname='custom_return_allocation',fieldtype='Data',label='Accepted QC Allocation',insert_after='custom_return_qi')]
    for dt,rows in fields.items():
        meta=frappe.get_meta(dt)
        for row in rows:
            old=meta.get_field(row['fieldname'])
            compatible_expansion = old and row['fieldname']=='custom_return_purpose' and old.fieldtype=='Select' and set((old.options or '').split('\n')).issubset(set(row['options'].split('\n')))
            if old and not compatible_expansion and (old.fieldtype!=row['fieldtype'] or (row.get('options') and old.options!=row['options'])):
                frappe.throw(f'Incompatible existing {dt}.{row["fieldname"]}; review before migration.')
    create_custom_fields(fields,update=False)
    meta=frappe.get_meta('Quality Inspection')
    options=(meta.get_field('reference_type').options or '').split('\n')
    if 'Return Receipt' not in options:
        make_property_setter('Quality Inspection','reference_type','options','\n'.join(options+['Return Receipt']),'Text')
    # Return-only readers cannot list/open unrelated manufacturing/purchasing inspections.
    for role in ('Managing Director','Return Reviewer'):
        if not frappe.db.exists('Role',role):
            frappe.get_doc(dict(doctype='Role',role_name=role)).insert(ignore_permissions=True)
    from frappe.permissions import add_permission, update_permission_property
    if not frappe.db.exists('Custom DocPerm',{'parent':'Quality Inspection','role':'Return Reviewer','permlevel':0}):
        add_permission('Quality Inspection','Return Reviewer',0)
    for ptype in ('read','select','report','print'):
        update_permission_property('Quality Inspection','Return Reviewer',0,ptype,1)


def save_owned(doctype,name,values):
    if frappe.db.exists(doctype,name):
        doc=frappe.get_doc(doctype,name);doc.update(values);doc.save(ignore_permissions=True)
    else:
        doc=frappe.get_doc(dict(doctype=doctype,**values));doc.insert(ignore_permissions=True,set_name=name)
    return doc


def configure_workflow(name,doctype,states,transitions):
    other=frappe.db.get_value('Workflow',{'document_type':doctype,'is_active':1,'name':['!=',name]},'name')
    if other:
        frappe.throw(f'{doctype} already uses workflow {other}; do not replace it silently.')
    for value in states:
        if not frappe.db.exists('Workflow State',value):
            frappe.get_doc(dict(doctype='Workflow State',workflow_state_name=value,style='Primary')).insert(ignore_permissions=True)
    for _,action,_,_,_ in transitions:
        if not frappe.db.exists('Workflow Action Master',action):
            frappe.get_doc(dict(doctype='Workflow Action Master',workflow_action_name=action)).insert(ignore_permissions=True)
    save_owned('Workflow',name,dict(workflow_name=name,document_type=doctype,is_active=1,send_email_alert=0,
        override_status=0,workflow_state_field='workflow_state',enable_action_confirmation=1,
        states=[dict(state=x,doc_status='0',allow_edit='All') for x in states],
        transitions=[dict(state=a,action=b,next_state=c,allowed=d,condition=e,allow_self_approval=1) for a,b,c,d,e in transitions]))


def configure():
    finance=frappe.db.get_single_value('Return Settings','settlement_approver_role') or 'Accounts Manager'
    transitions=[]
    def add(a,b,c,roles,condition=None):
        for role in roles:transitions.append((a,b,c,role,condition))
    add('Draft','Request Approval','Pending Approval',('Sales User','Sales Manager','Managing Director'))
    add('Pending Approval','Authorize','Authorized',('Managing Director',))
    add('Pending Approval','Reject','Rejected',('Managing Director',))
    add('Pending Approval','Request Changes','Draft',('Managing Director',))
    add('Authorized','Approve Return Exceptions','Exceptions Approved',('Managing Director',))
    add('Exceptions Approved','Continue Receipt','Authorized',('Stock Manager','Managing Director'))
    for s in ('Authorized','Exceptions Approved'):
        add(s,'Prepare Settlement','Finance Review',('Accounts User',finance))
        add(s,'Close Without Accepted Goods','Closed',(finance,))
    add('Finance Review','Request Concession','Pending Concession',('Accounts User',finance),'doc.concession_required > 0')
    add('Pending Concession','Approve Concession','Concession Approved',('Managing Director',),'doc.designated_md_user == frappe.session.user')
    add('Pending Concession','Revise Settlement','Finance Review',('Accounts User',finance))
    for s in ('Finance Review','Concession Approved'):
        add(s,'Approve Settlement','Settlement Approved',(finance,),'doc.concession_required == 0 or doc.concession_approved')
        add(s,'Return to QC','Authorized',(finance,))
    add('Concession Approved','Revise Settlement','Finance Review',(finance,))
    add('Settlement Approved','Mark Settled','Settled',(finance,))
    add('Settlement Approved','Revise Settlement','Finance Review',(finance,))
    add('Settled','Close Return','Closed',(finance,))
    add('Settled','Revise Settlement','Finance Review',(finance,))
    add('Closed','Reopen for Reconciliation','Finance Review',(finance,))
    add('Legacy Review','Complete Legacy Review','Finance Review',(finance,))
    states=['Draft','Pending Approval','Authorized','Exceptions Approved','Finance Review','Pending Concession',
        'Concession Approved','Settlement Approved','Settled','Closed','Rejected','Legacy Review']
    configure_workflow(MRA_WORKFLOW,MRA,states,transitions)
    configure_workflow(RECEIPT_WORKFLOW,'Return Receipt',['Draft','Received','Disposal Approved'],[
        ('Draft','Confirm Receipt','Received','Stock User',None),('Draft','Confirm Receipt','Received','Stock Manager',None),
        ('Received','Approve Disposal','Disposal Approved','Managing Director','doc.customer_disposal_instruction'),
        ('Disposal Approved','Complete Disposition','Received','Stock Manager',None)])
    # Native assignment creates/closes ToDos; no custom reminder scheduler remains.
    for dt,condition,close in [(MRA,"workflow_state not in ('Closed','Rejected')","workflow_state in ('Closed','Rejected')"),
        ('Return Receipt',"workflow_state != 'Draft' and not quality_complete","quality_complete == 1")]:
        save_owned('Assignment Rule','SNRG Returns - '+dt,dict(document_type=dt,description='Return action: {{ name }}',
            due_date_based_on='due_date',priority=20,disabled=0,assign_condition=condition,close_condition=close,
            rule='Based on Field',field='responsible_user',assignment_days=[dict(day=x) for x in ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']]))
    for label,dt,date_field,condition in [
        ('Case Due',MRA,'due_date',"doc.workflow_state not in ('Closed','Rejected','Settled')"),
        ('QC Due','Return Receipt','due_date',"not doc.quality_complete and doc.workflow_state != 'Draft'"),
        ('Collection Due','Return Receipt','collection_deadline',"doc.disposition == 'Pending' and doc.rejection_notice_date")]:
        save_owned('Notification','SNRG Returns - '+label,dict(enabled=1,channel='System Notification',
            subject='Return action due: {{ doc.name }}',event='Days After',document_type=dt,date_changed=date_field,
            days_in_advance=0,condition=condition,message='Review {{ doc.name }} and its return action queue.',
            recipients=[dict(receiver_by_document_field='responsible_user')],send_to_all_assignees=0))


def migrate_legacy():
    from .migration import migrate_legacy_records
    migrate_legacy_records()


def after_migrate():
    ensure_fields()
    config=frappe.get_single('Return Settings')
    if not config.policy_terms:
        config.policy_terms=TERMS;config.save(ignore_permissions=True)
    migrate_legacy()
    configure()
    configure_navigation()
    from .stock_first_setup import configure as configure_stock_first
    configure_stock_first()


def configure_navigation():
    """Update only returns links in the existing Supply Chain sidebar."""
    for doctype in ('Sidebar', 'Workspace Sidebar'):
        if not frappe.db.exists('DocType', doctype) or not frappe.db.exists(doctype, 'Supply Chain'):
            continue
        sidebar = frappe.get_doc(doctype, 'Supply Chain')
        if doctype == 'Workspace Sidebar' and sidebar.get('for_user'):
            continue
        old = [r.link_to for r in sidebar.items]
        sidebar.set('items', [r for r in sidebar.items if r.link_to not in ('Return Inspection', 'Return Settlement')])
        if not any(r.link_to == 'Quality Inspection' for r in sidebar.items):
            sidebar.append('items', dict(type='Link', link_type='DocType', link_to='Quality Inspection', label='Quality Inspection'))
        if old != [r.link_to for r in sidebar.items]:
            sidebar.save(ignore_permissions=True)
