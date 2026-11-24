"""Permission-checked disassembly service. Stock Entries remain the ledger authority."""
import json
import hashlib
from collections import defaultdict
import frappe
from frappe.utils import flt

DT = 'Bulk Disassembly'


def save_internal(doc):
    previous = frappe.flags.get('in_bulk_disassembly_service')
    frappe.flags.in_bulk_disassembly_service = True
    try:
        doc.save()
    finally:
        frappe.flags.in_bulk_disassembly_service = previous


def allowed(doc, submit=False):
    doc.check_permission('write')
    if submit and not frappe.has_permission('Stock Entry', 'submit'):
        frappe.throw('Stock Entry submit permission is required.', frappe.PermissionError)


def locked(name):
    frappe.db.sql('select name from `tabBulk Disassembly` where name=%s for update', (name,))
    return frappe.get_doc(DT, name)


def settings(doc):
    station = frappe.get_doc('Production Station', doc.station)
    station.check_permission('read')
    if not station.enabled:
        frappe.throw('This disassembly station is disabled.')
    if station.consumption_method != 'Stocked components':
        frappe.throw('Bulk disassembly recovers stocked components. Choose a station using Stocked components; expanded raw-material recovery requires the detailed Stock Entry workflow.')
    config = {k: station.get(k) for k in ('company','source_warehouse','target_warehouse','consumption_method','cost_center')}
    for field in ('source_warehouse','target_warehouse'):
        config[field] = doc.get(field) or station.get('target_warehouse' if field == 'source_warehouse' else 'source_warehouse')
        if not config[field]:
            frappe.throw('Select both source and target warehouses.')
        wh = frappe.get_doc('Warehouse', config[field])
        wh.check_permission('read')
        if wh.company != station.company or wh.is_group or wh.disabled:
            frappe.throw('Select active, non-group warehouses belonging to the station company.')
    return config


def validate_recipe(bom, expanded, seen):
    if bom.name in seen:
        return
    seen.add(bom.name)
    if bom.docstatus != 1 or not bom.is_active:
        frappe.throw(f'{bom.name}: the recipe must be active and submitted.')
    if bom.get('custom_mould_configuration') or bom.with_operations or bom.get('secondary_items') or bom.get('scrap_items') or bom.get('process_loss_percentage') or bom.get('inspection_required'):
        frappe.throw(f'{bom.name}: use the detailed manufacturing workflow for moulding, operations, quality, scrap or process loss.')
    if expanded:
        for component in bom.items:
            if component.bom_no and not component.get('do_not_explode'):
                child = frappe.get_doc('BOM',component.bom_no)
                child.check_permission('read')
                if child.company != bom.company:
                    frappe.throw('Subassembly BOMs must belong to the production company.')
                validate_recipe(child,expanded,seen)


def make_entry(doc, row, config, pin=False):
    item = frappe.get_doc('Item', row.item_code)
    item.check_permission('read')
    if item.disabled or not item.is_stock_item or item.has_variants:
        frappe.throw(f'{row.item_code}: choose an active stock item, not a template.')
    if frappe.get_cached_value('UOM', item.stock_uom, 'must_be_whole_number') and flt(row.qty) % 1:
        frappe.throw(f'{row.item_code}: quantity must be a whole number.')
    boms = frappe.get_list('BOM', filters=dict(item=row.item_code,company=config['company'],is_default=1,is_active=1,docstatus=1), pluck='name', limit_page_length=2)
    if len(boms) != 1:
        frappe.throw(f'{row.item_code}: exactly one active submitted default BOM is required.')
    if row.bom_no and row.bom_no != boms[0]:
        frappe.throw(f'{row.item_code}: default BOM changed. Create a new draft for review.')
    bom = frappe.get_doc('BOM', boms[0])
    bom.check_permission('read')
    if bom.uom != item.stock_uom:
        frappe.throw(f'{row.item_code}: BOM UOM must match the stock UOM for bulk disassembly.')
    validate_recipe(bom,False,set())
    entry = frappe.new_doc('Stock Entry')
    entry.update(dict(stock_entry_type='Disassemble',purpose='Disassemble',company=config['company'],from_bom=1,bom_no=bom.name,fg_completed_qty=row.qty,use_multi_level_bom=0,from_warehouse=config['source_warehouse'],to_warehouse=config['target_warehouse'],cost_center=config['cost_center'],posting_date=doc.posting_date,posting_time=doc.posting_time,set_posting_time=1,custom_bulk_disassembly=doc.name,custom_bulk_disassembly_row=row.name,remarks=f'Bulk disassembly {doc.name}, row {row.idx}'))
    entry.get_items()
    for detail in entry.items:
        detail.s_warehouse = config['source_warehouse'] if detail.s_warehouse else None
        detail.t_warehouse = config['target_warehouse'] if detail.t_warehouse else None
        flags = frappe.get_cached_value('Item', detail.item_code, ['has_batch_no','has_serial_no','inspection_required_before_purchase'], as_dict=True)
        if flags.has_batch_no or flags.has_serial_no or flags.inspection_required_before_purchase or entry.inspection_required:
            frappe.throw(f'{detail.item_code}: batch, serial or quality details require the detailed Stock Entry screen.')
    if entry.get('process_loss_qty') or entry.get('process_loss_percentage'):
        frappe.throw('Process loss requires the detailed manufacturing workflow.')
    if any(d.get('secondary_item_type') or d.get('is_scrap_item') for d in entry.items):
        frappe.throw('This BOM has secondary outputs; use the detailed manufacturing workflow.')
    if pin:
        row.bom_no, row.uom, row.item_name = bom.name, item.stock_uom, item.item_name
    return entry


def production_error_message(error):
    """Operator guidance must never suggest bypassing material valuation."""
    import re
    message = re.sub(r'<[^>]*>', ' ', str(error))
    message = re.sub(r'\s+', ' ', message).strip()
    if any(term in message.lower() for term in ('allow zero valuation', 'allow_zero_valuation', 'valuation rate for', 'valuation rate missing')):
        return 'Material valuation is missing. Ask the inventory or accounts team to record the correct incoming material cost, then review disassembly again. Posting remains blocked until a valid cost is available.'
    return message[:1000]


def valuation_issues(entry):
    """Use the same outgoing-rate resolver as Stock Entry without writing stock."""
    from erpnext.stock.utils import _get_incoming_rate
    issues = []
    muted = getattr(frappe.flags, 'mute_messages', False)
    try:
        frappe.flags.mute_messages = True
        for detail in entry.items:
            if not detail.s_warehouse:
                continue
            try:
                rate = _get_incoming_rate(entry.get_args_for_incoming_rate(detail), raise_error_if_no_rate=True)
                if flt(rate) <= 0:
                    frappe.throw('Material valuation rate missing.')
            except frappe.ValidationError as exc:
                issues.append(dict(item_code=detail.item_code,item_name=detail.item_name,
                    warehouse=detail.s_warehouse,message=production_error_message(exc)))
    finally:
        frappe.flags.mute_messages = muted
    return issues


def review_doc(doc, config, pin=False):
    from erpnext.stock.utils import get_stock_balance
    demand = defaultdict(float)
    results = []
    missing_rates = {}
    for row in doc.items:
        if row.status == 'Posted':
            continue
        entry = make_entry(doc, row, config, pin=pin)
        for issue in valuation_issues(entry):
            key = (issue['item_code'],issue['warehouse'])
            missing_rates.setdefault(key,issue)
        materials = []
        for detail in entry.items:
            if detail.s_warehouse:
                if not detail.is_finished_item:
                    frappe.throw('Only the finished item can be consumed in bulk disassembly.')
                qty = flt(detail.transfer_qty) or flt(detail.qty)*flt(detail.conversion_factor)
                demand[(detail.item_code,detail.s_warehouse)] += qty
                materials.append(dict(item_code=detail.item_code,item_name=detail.item_name,qty=qty,uom=detail.stock_uom))
        recovered = [dict(item_code=d.item_code,item_name=d.item_name,qty=flt(d.transfer_qty) or flt(d.qty)*flt(d.conversion_factor),uom=d.stock_uom) for d in entry.items if d.t_warehouse]
        results.append(dict(item_code=row.item_code,qty=row.qty,uom=row.uom,bom_no=entry.bom_no,materials=recovered,consumed=materials))
    shortages = []
    for (item, warehouse), required in demand.items():
        available = flt(get_stock_balance(item,warehouse,doc.posting_date,doc.posting_time))
        if required > available + 0.000001:
            shortages.append(dict(item_code=item,warehouse=warehouse,required=required,available=available))
    return dict(rows=results,shortages=shortages,valuation_issues=list(missing_rates.values()))


@frappe.whitelist()
def review(name):
    doc = frappe.get_doc(DT,name)
    allowed(doc)
    config = settings(doc)
    result = review_doc(doc,config)
    result['review_token'] = review_token(doc,config,result)
    return result


def review_token(doc, config, result):
    payload = dict(modified=str(doc.modified), config=config, rows=result['rows'])
    return hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()


@frappe.whitelist()
def post(name, token):
    if frappe.request and frappe.request.method != 'POST':
        frappe.throw('Use POST to post disassembly.')
    doc = locked(name)
    allowed(doc,submit=True)
    if doc.status == 'Posted':
        return dict(name=doc.name,status=doc.status)
    config = settings(doc)
    if doc.settings_snapshot and json.loads(doc.settings_snapshot) != config:
        frappe.throw('Disassembly settings changed. Warehouses and station settings must match the original posting when retrying.')
    preview = review_doc(doc,config,pin=True)
    if preview['shortages']:
        codes = ', '.join(issue['item_code'] for issue in preview['shortages'])
        frappe.throw(f'Insufficient materials for {codes}. Replenish the source warehouse or reduce the quantities, then review again.')
    if preview['valuation_issues']:
        codes = ', '.join(issue['item_code'] for issue in preview['valuation_issues'])
        frappe.throw(f'Material valuation is missing for {codes}. Resolve the material costs and review disassembly again before posting.')
    if token != review_token(doc,config,preview):
        frappe.throw('Disassembly changed since review. Review the sheet again before posting.')
    doc.source_warehouse = config['source_warehouse']
    doc.target_warehouse = config['target_warehouse']
    doc.company = config['company']
    doc.settings_snapshot = json.dumps(config,sort_keys=True)
    doc.status = 'Queued'
    save_internal(doc)
    frappe.enqueue('snrg_supplychain.supply_chain.bulk_disassembly.process',queue='long',enqueue_after_commit=True,name=doc.name,user=frappe.session.user)
    return dict(name=doc.name,status=doc.status)


def check_entry_stock(entry):
    from erpnext.stock.utils import get_stock_balance
    requirements = defaultdict(float)
    for row in entry.items:
        if row.s_warehouse:
            requirements[(row.item_code,row.s_warehouse)] += flt(row.transfer_qty) or flt(row.qty)*flt(row.conversion_factor)
    warnings = []
    # Serialize competing sheets on their material bins and reject shortages
    # even when an Item permits negative stock in other ERPNext workflows.
    for (item,warehouse), qty in sorted(requirements.items()):
        frappe.db.sql('select name from `tabBin` where item_code=%s and warehouse=%s for update',(item,warehouse))
        available = flt(get_stock_balance(item,warehouse,entry.posting_date,entry.posting_time))
        if qty > available + 0.000001:
            warnings.append(dict(item_code=item,warehouse=warehouse,required=qty,available=available))
    return warnings


def process(name, user):
    """One committed transaction per row, serialized by sheet lock. Safe to resume."""
    frappe.set_user(user)
    initial = frappe.get_doc(DT,name)
    for row_name in [r.name for r in initial.items]:
        try:
            doc = locked(name)
            allowed(doc,submit=True)
            row = next(r for r in doc.items if r.name == row_name)
            if row.status == 'Posted':
                frappe.db.commit()
                continue
            config = settings(doc)
            if json.loads(doc.settings_snapshot) != config:
                frappe.throw('Station settings changed after review.')
            entry = make_entry(doc,row,config)
            warnings = check_entry_stock(entry)
            if warnings:
                details = '; '.join(f"{w['item_code']}: need {w['required']}, available {w['available']} in {w['warehouse']}" for w in warnings)
                frappe.throw('Insufficient materials. ' + details)
            entry.insert()
            entry.submit()
            row.stock_entry,row.status,row.error = entry.name,'Posted',None
            save_internal(doc)
            frappe.db.commit()
        except Exception as exc:
            frappe.db.rollback()
            doc = locked(name)
            row = next(r for r in doc.items if r.name == row_name)
            if row.status != 'Posted':
                row.status,row.error = 'Failed',production_error_message(exc)
                save_internal(doc)
            frappe.db.commit()
    doc = locked(name)
    posted = sum(r.status == 'Posted' for r in doc.items)
    doc.status = 'Posted' if posted == len(doc.items) else 'Partially Posted' if posted else 'Failed'
    save_internal(doc)
    frappe.db.commit()
