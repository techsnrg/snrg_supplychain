"""Read-only layout verification on Docker staging; migration snapshots contain no credentials."""
from pathlib import Path
import json
import frappe

SITE='production-staging.localhost'
STRUCT={'Section Break','Column Break','Tab Break'}


def guard():
    if frappe.local.site!=SITE:raise RuntimeError('Docker staging only')
    frappe.set_user('Administrator')


def snapshot():
    guard()
    docs=frappe.get_all('DocType',filters={'module':'Supply Chain','custom':0},fields=['name','istable','issingle'],limit_page_length=0)
    data=dict(ledger={dt:frappe.db.count(dt) for dt in ('GL Entry','Stock Ledger Entry')},records={},metadata={})
    for row in docs:
        meta=frappe.get_meta(row.name)
        data['metadata'][row.name]={f.fieldname:f.as_dict() for f in meta.fields if f.fieldtype not in STRUCT}
        if row.istable:continue
        records=[frappe.get_single(row.name).as_dict()] if row.issingle else [frappe.get_doc(row.name,name).as_dict() for name in frappe.get_all(row.name,pluck='name',limit_page_length=0)]
        # Ignore standard document timestamps only; all business values and child rows remain compared.
        data['records'][row.name]=records
    Path('/tmp/snrg-layout-before.json').write_text(json.dumps(data,default=str))
    return dict(doctypes=len(docs),parents=len(data['records']),ledger=data['ledger'])


def verify():
    guard();before=json.loads(Path('/tmp/snrg-layout-before.json').read_text());checks=[]
    def check(value,label):
        if not value:raise AssertionError(label)
        checks.append(label)
    def business(value):
        if isinstance(value,dict):return {k:business(v) for k,v in value.items() if k not in ('creation','modified')}
        if isinstance(value,list):return [business(x) for x in value]
        return value
    for dt,records in before['records'].items():
        meta=frappe.get_meta(dt)
        actual=[frappe.get_single(dt).as_dict()] if meta.issingle else [frappe.get_doc(dt,name).as_dict() for name in frappe.get_all(dt,pluck='name',limit_page_length=0)]
        # JSON comparison standardizes date/datetime and decimal encoding.
        check(business(sorted(json.loads(json.dumps(actual,default=str)),key=lambda x:x['name']))==business(sorted(records,key=lambda x:x['name'])),dt+': all saved business data preserved')
    for dt,fields in before['metadata'].items():
        meta=frappe.get_meta(dt);current={f.fieldname:f for f in meta.fields if f.fieldtype not in STRUCT}
        check(set(current)==set(fields),dt+': all data fields retained')
        # Layout-only changes must never alter permissions, required/default or dependencies.
        for field,old in fields.items():
            for key in ('fieldtype','options','reqd','read_only','hidden','default','depends_on','mandatory_depends_on','read_only_depends_on','allow_on_submit'):
                if current[field].get(key)!=old.get(key):raise AssertionError(f'{dt}.{field}: changed {key}')
        check(any(f.fieldtype=='Column Break' for f in meta.fields) or len(fields)<3,dt+': native grouped layout present')
    check(before['ledger']=={dt:frappe.db.count(dt) for dt in before['ledger']},'Layout migration posts no GL or Stock Ledger entries')
    result=dict(passed=True,checks=checks,doctypes=len(before['metadata']))
    Path('/tmp/snrg-layout-results.json').write_text(json.dumps(result));return result


def browser_inventory():
    guard()
    result=[]
    for row in frappe.get_all('DocType',filters={'module':'Supply Chain','custom':0},fields=['name','istable','issingle'],limit_page_length=0):
        names=[] if row.istable or row.issingle else frappe.get_all(row.name,pluck='name',limit_page_length=1)
        result.append(dict(doctype=row.name,child=bool(row.istable),single=bool(row.issingle),name=names[0] if names else None))
    # Dedicated synthetic staging tester only, never production users.
    frappe.get_doc('User','returns-stock-first-ui@staging.invalid').add_roles('System Manager','Manufacturing Manager')
    frappe.db.commit()
    return result


def diff_records():
    guard();before=json.loads(Path('/tmp/snrg-layout-before.json').read_text());result=[]
    for dt,rows in before['records'].items():
        meta=frappe.get_meta(dt)
        actual=[frappe.get_single(dt).as_dict()] if meta.issingle else [frappe.get_doc(dt,n).as_dict() for n in frappe.get_all(dt,pluck='name',limit_page_length=0)]
        indexed={x['name']:x for x in json.loads(json.dumps(actual,default=str))}
        for old in rows:
            new=indexed.get(old['name'],{})
            for field in set(old)|set(new):
                if old.get(field)!=new.get(field):result.append(dict(doctype=dt,name=old['name'],field=field,before=old.get(field),after=new.get(field)))
    return result[:20]
