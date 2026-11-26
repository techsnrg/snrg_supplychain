import frappe
from frappe.utils import getdate,today


def execute(filters=None):
    columns=[dict(label='Document Type',fieldname='document_type',fieldtype='Data',width=190),
        dict(label='Reference',fieldname='reference',fieldtype='Dynamic Link',options='document_type',width=200),
        dict(label='Status',fieldname='status',fieldtype='Data',width=160),
        dict(label='Owner',fieldname='responsible_user',fieldtype='Link',options='User',width=160),
        dict(label='Due Date',fieldname='due_date',fieldtype='Date',width=110),
        dict(label='Overdue Days',fieldname='overdue_days',fieldtype='Int',width=110),
        dict(label='Delay Reason',fieldname='delay_reason',fieldtype='Data',width=240)]
    data=[]
    for dt in ('Material Return Authorization','Return Receipt'):
        if not frappe.has_permission(dt,'read'):continue
        fields=['name','workflow_state','responsible_user','due_date','revised_due_date','delay_reason']
        if dt=='Return Receipt':fields+=['quality_complete','collection_deadline','disposition','authorization']
        for row in frappe.get_list(dt,fields=fields,page_length=0):
            if row.workflow_state in ('Closed','Rejected','Settled'):continue
            if dt=='Return Receipt':
                if frappe.db.get_value('Material Return Authorization',row.authorization,'workflow_state')=='Closed':continue
                if row.quality_complete:
                    if row.disposition!='Pending' or not row.collection_deadline:continue
                    deadline=row.collection_deadline
                else:deadline=row.revised_due_date or row.due_date
            else:deadline=row.revised_due_date or row.due_date
            if not deadline:continue
            data.append(dict(document_type=dt,reference=row.name,status=row.workflow_state,responsible_user=row.responsible_user,
                due_date=deadline,overdue_days=max(0,(getdate(today())-getdate(deadline)).days),delay_reason=row.delay_reason))
    for dt in ('Delivery Note','Purchase Receipt','Stock Entry'):
        if not frappe.has_permission(dt,'read'):continue
        for row in frappe.get_list(dt,filters={'docstatus':1,'custom_return_purpose':'Arrival'},
            fields=['name','custom_return_mra','custom_return_responsible_user','custom_return_due_date','custom_return_revised_due_date',
                'custom_return_collection_deadline','custom_return_disposition','custom_return_delay_reason'],page_length=0):
            if frappe.db.get_value('Material Return Authorization',row.custom_return_mra,'workflow_state')=='Closed':continue
            deadline=row.custom_return_revised_due_date or row.custom_return_due_date
            if row.custom_return_disposition=='Pending' and row.custom_return_collection_deadline:
                deadline=min([x for x in (deadline,row.custom_return_collection_deadline) if x],key=getdate)
            if deadline:data.append(dict(document_type=dt,reference=row.name,status='Returns — Pending QC / disposition',
                responsible_user=row.custom_return_responsible_user,due_date=deadline,
                overdue_days=max(0,(getdate(today())-getdate(deadline)).days),delay_reason=row.custom_return_delay_reason))
    return columns,sorted(data,key=lambda x:(-x['overdue_days'],x['reference']))
