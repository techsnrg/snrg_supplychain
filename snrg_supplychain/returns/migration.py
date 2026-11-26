"""Preserve legacy parents and import evidence into native QI / MRA sections.

No stock, accounting or party transaction is posted by this migration.
"""
import json
from collections import defaultdict

import frappe
from frappe.utils import flt


def migrate_legacy_records():
    from .native_service import (concession_digest, exception_digest, load_settlement_lines,
        calculate_settlement, qc_context, settlement_digest)
    names=frappe.get_all('Material Return Authorization',filters={'native_migration_complete':0},pluck='name')
    for name in names:
        mra=frappe.get_doc('Material Return Authorization',name)
        old_state=mra.status or 'Draft'
        old_inspections=frappe.get_all('Return Inspection',filters={'authorization':name},pluck='name')
        old_settlements=frappe.get_all('Return Settlement',filters={'authorization':name},pluck='name')
        receipts=frappe.get_all('Return Receipt',filters={'authorization':name},pluck='name')
        for receipt_name in receipts:
            receipt=frappe.get_doc('Return Receipt',receipt_name)
            frappe.db.set_value('Return Receipt',receipt_name,'workflow_state',receipt.status or 'Draft',update_modified=False)
        frappe.db.set_value('Material Return Authorization',name,'workflow_state',old_state,update_modified=False)
        for inspection_name in old_inspections:
            inspection=frappe.get_doc('Return Inspection',inspection_name)
            receipt=frappe.get_doc('Return Receipt',inspection.receipt)
            disposition_fields=('findings_notice','rejection_notice_date','dispute_deadline','collection_deadline',
                'dispute_status','dispute_details','resolved_on','resolution','disposition','disposition_date',
                'customer_disposal_instruction','disposal_approved_by','disposition_evidence')
            frappe.db.set_value('Return Receipt',receipt.name,{k:inspection.get(k) for k in disposition_fields},update_modified=False)
            grouped=defaultdict(list)
            for row in inspection.items:grouped[row.receipt_item].append(row)
            for source in receipt.items:
                legacy_rows=grouped.get(source.name)
                if not legacy_rows:continue
                exists=frappe.db.get_value('Quality Inspection',{'custom_legacy_inspection':inspection.name,
                    'custom_return_receipt_item':source.name,'docstatus':['<',2]},'name')
                if exists:continue
                failed=any(x.finding in ('Manufacturing Defect','Customer Damage','Unsellable') for x in legacy_rows)
                qi=frappe.new_doc('Quality Inspection')
                qi.update(dict(company=mra.company,report_date=inspection.completed_on or receipt.received_on,
                    status='Rejected' if failed else 'Accepted',inspection_type='Incoming',reference_type='Return Receipt',
                    reference_name=receipt.name,child_row_reference=source.name,custom_return_receipt_item=source.name,
                    custom_return_mra=mra.name,custom_return_receipt=receipt.name,custom_legacy_inspection=inspection.name,
                    item_code=source.item_code,batch_no=source.batch_no,sample_size=source.received_qty,
                    manual_inspection=1,inspected_by=inspection.responsible_user or inspection.owner,
                    remarks='Imported legacy inspection '+inspection.name+'. Original evidence and approval history retained.'))
                for row in legacy_rows:
                    qi.append('custom_return_allocations',{k:row.get(k) for k in ('qty','finding','decision','notes','photo','exception_reason')})
                    qi.custom_return_allocations[-1].legacy_row=row.name
                qi.flags.returns_migration=True
                qi.insert(ignore_permissions=True)
                if inspection.status=='Completed':
                    qi.flags.returns_migration=True
                    qi.submit()
                frappe.db.set_value('Return Receipt Item',source.name,'quality_inspection',qi.name,update_modified=False)
        mra=frappe.get_doc('Material Return Authorization',name)
        mra.workflow_state=old_state
        mra.legacy_inspections=json.dumps(old_inspections)
        mra.legacy_settlements=json.dumps(old_settlements)
        mra.legacy_migrated=int(bool(old_settlements))
        mra.native_returns_version=2
        mra.native_migration_complete=1
        mra.designated_md_user=frappe.db.get_single_value('Return Settings','waiver_approver')
        context=qc_context(mra)
        if context['exceptions']:
            # Only inherit actual recorded legacy approvals; never invent one.
            accepted_exception_rows=[r for i in old_inspections for r in frappe.get_doc('Return Inspection',i).items
                if r.decision=='Accept' and (r.finding in ('Fresh / Saleable','Customer Damage','Unsellable')
                or next((x.unauthorized for x in frappe.get_doc('Return Receipt',frappe.get_doc('Return Inspection',i).receipt).items if x.name==r.receipt_item),False))]
            if accepted_exception_rows and all(x.exception_approved_by for x in accepted_exception_rows):
                mra.exception_approved_by=accepted_exception_rows[0].exception_approved_by
                mra.exception_fingerprint=exception_digest(context)
                mra.exception_reason='Inherited recorded legacy acceptance approvals; see linked legacy records.'
                mra.exceptions_approved=1
        if old_settlements:
            legacy=[frappe.get_doc('Return Settlement',x) for x in old_settlements]
            if len(legacy)>1 or context['incomplete']:
                mra.workflow_state=mra.status='Legacy Review'
                mra.legacy_review_required=1
            else:
                source=legacy[0]
                for key in ('route','supplier','restocking_charge','handling_charge','waiver_amount','waiver_reason',
                    'customer_invoice_number','customer_invoice_date','customer_invoice_attachment','stock_reconciled',
                    'charges_reconciled','ledger_reconciled','reconciliation_notes','difference_reason','waiver_approved_by',
                    'waiver_approved_on'):
                    mra.set(key,source.get(key))
                load_settlement_lines(mra,context)
                # Preserve the actual historical concession after rebuilding the native-QC links.
                mra.restocking_charge=source.restocking_charge
                calculate_settlement(mra,context)
                for table in ('accounting_documents','stock_references'):
                    mra.set(table,[])
                    for row in source.get(table) or []:
                        mra.append(table,{k:v for k,v in row.as_dict().items()
                            if k not in ('name','doctype','parent','parenttype','parentfield','creation','modified','modified_by','owner','idx','docstatus')})
                if source.waiver_approved_by:
                    mra.waiver_fingerprint=concession_digest(mra)
                mra.settlement_approved_by=source.approved_by
                mra.settlement_approved_on=source.approved_on
                mra.workflow_state=mra.status='Closed' if old_state=='Closed' else {'Draft':'Finance Review','Approved':'Settlement Approved','Settled':'Settled'}.get(source.status,'Legacy Review')
                mra.legacy_review_required=int(mra.workflow_state=='Legacy Review')
        else:
            mra.status=mra.workflow_state=old_state
        # This is an evidence migration, not a business approval. Bypass workflow/ledger
        # operations explicitly and retain original parent records and all their children.
        mra.set_parent_in_children();mra.set_name_in_children()
        mra.db_update();mra.update_children()
        if mra.waiver_approved_by:mra.waiver_fingerprint=concession_digest(mra)
        if mra.settlement_approved_by:mra.settlement_fingerprint=settlement_digest(mra)
        mra.db_update()
        mra.add_comment('Comment',text='Native returns refactor: legacy evidence retained read-only; native QC and MRA settlement references imported. No stock/GL entries posted.')
