"""Run only against isolated production-staging.localhost; all fixtures roll back."""
import json
import os
from pathlib import Path
import frappe
from frappe.utils import add_days, nowdate


def run():
    assert frappe.local.site == 'production-staging.localhost'
    assert frappe.conf.get('mute_emails'), 'Local email must remain muted'
    from snrg_supplychain.supply_chain.purchasing import compare_purchase_rates, overdue_deliveries
    from snrg_supplychain.supply_chain.report.overdue_supplier_deliveries.overdue_supplier_deliveries import execute
    results=[]
    def check(label,condition):
        assert condition,label
        results.append(label)
    today=nowdate();company='SNRG Production Staging';other='Other Company Staging'
    def po(rate, when, qty=10, factor=1, currency='INR', fx=1, company=company):
        d=frappe.get_doc(dict(doctype='Purchase Order',supplier=supplier.name,company=company,
            transaction_date=when,schedule_date=max(when,add_days(today,-1)),currency=currency,conversion_rate=fx,
            buying_price_list='',items=[dict(item_code=item.name,qty=qty,uom='Nos',stock_uom='Nos',
            conversion_factor=factor,rate=rate,schedule_date=max(when,add_days(today,-1)))]))
        d.insert();return d
    try:
        frappe.set_user('Administrator')
        supplier=frappe.get_doc(dict(doctype='Supplier',supplier_name='PURCHASING-DOCKER-ONLY',supplier_group='Local',supplier_type='Company')).insert()
        source=frappe.db.get_value('Item',{'disabled':0,'stock_uom':'Nos'},['item_group','custom_item_type'],as_dict=True)
        item=frappe.get_doc(dict(doctype='Item',item_code='PURCHASING-DOCKER-ONLY',item_name='Purchasing Docker Only',
            item_group=source.item_group,stock_uom='Nos',custom_item_type=source.custom_item_type,is_stock_item=0)).insert()
        historical=po(100,add_days(today,-5));historical.submit()
        cancelled=po(999,add_days(today,-4));cancelled.submit();cancelled.cancel()
        current=po(110,today)
        rows=compare_purchase_rates(current.as_dict())
        check('real query selects submitted history and excludes cancelled/current',rows[0]['previous_po']==historical.name)
        check('rate increase is 10 percent',round(rows[0]['variance'],6)==10)
        # Check unsaved edits and UOM normalization using the real API input contract.
        snapshot=current.as_dict();snapshot['items'][0]['base_net_rate']=220;snapshot['items'][0]['conversion_factor']=2
        check('unsaved UOM-normalized rate comparison',compare_purchase_rates(snapshot)[0]['current_rate']==110)
        snapshot['transaction_date']=add_days(today,-10)
        check('backdated PO excludes later history',compare_purchase_rates(snapshot)[0]['previous_po'] is None)
        other_po=po(40,add_days(today,-3),company=other);other_po.submit()
        user=frappe.get_doc(dict(doctype='User',email='purchase-test@example.invalid',first_name='Purchasing test',send_welcome_email=0,
            roles=[{'role':'Purchase User'}])).insert()
        frappe.get_doc(dict(doctype='User Permission',user=user.name,allow='Company',for_value=company,apply_to_all_doctypes=1)).insert()
        frappe.set_user(user.name)
        check('restricted buyer can query permitted history',compare_purchase_rates(current.as_dict())[0]['previous_po']==historical.name)
        allowed=overdue_deliveries({'company':company})
        check('restricted buyer gets permitted overdue rows',any(r['purchase_order']==historical.name for r in allowed))
        check('company permissions exclude other company',overdue_deliveries({'company':other})==[])
        frappe.set_user('Guest')
        try: overdue_deliveries({'company':company})
        except frappe.PermissionError: results.append('unprivileged report user rejected')
        else: raise AssertionError('Guest was permitted')
        frappe.set_user('Administrator')
        row=historical.items[0]
        frappe.db.set_value('Purchase Order Item',row.name,'received_qty',4)
        data=overdue_deliveries({'company':company,'supplier':supplier.name})
        match=next(r for r in data if r['purchase_order']==historical.name)
        check('partial receipt leaves six pending at correct value',match['pending_qty']==6 and match['pending_value']==600)
        frappe.db.set_value('Purchase Order Item',row.name,'schedule_date',today)
        check('due today is not overdue',not any(r['purchase_order']==historical.name for r in overdue_deliveries({'company':company,'supplier':supplier.name})))
        frappe.db.set_value('Purchase Order Item',row.name,{'schedule_date':add_days(today,-2),'received_qty':10})
        check('fully received row excluded',not any(r['purchase_order']==historical.name for r in overdue_deliveries({'company':company,'supplier':supplier.name})))
        frappe.db.set_value('Purchase Order Item',row.name,{'received_qty':0,'delivered_by_supplier':1})
        check('direct-to-customer row excluded',not any(r['purchase_order']==historical.name for r in overdue_deliveries({'company':company,'supplier':supplier.name})))
        cols, data, message, chart, summary=execute({'company':company})
        check('report executes with columns and company-filtered results',len(cols)==14)
        check('report registered by migrate',frappe.db.exists('Report','Overdue Supplier Deliveries'))
        # Exercise real Purchase Receipt and return updates, not synthetic receipt balances.
        frappe.db.set_value('Purchase Order Item',row.name,{'received_qty':0,'delivered_by_supplier':0})
        from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
        receipt=make_purchase_receipt(historical.name)
        receipt.items[0].qty=4
        receipt.insert();receipt.submit();historical.reload()
        check('real purchase receipt updates PO received quantity',historical.items[0].received_qty==4)
        match=next(r for r in overdue_deliveries({'company':company,'supplier':supplier.name}) if r['purchase_order']==historical.name)
        check('report follows real purchase receipt',match['pending_qty']==6)
        from erpnext.controllers.sales_and_purchase_return import make_return_doc
        returned=make_return_doc('Purchase Receipt',receipt.name)
        returned.items[0].qty=-2
        returned.insert();returned.submit();historical.reload()
        match=next(r for r in overdue_deliveries({'company':company,'supplier':supplier.name}) if r['purchase_order']==historical.name)
        check('report follows ERPNext authoritative quantity after return',match['pending_qty']==10-historical.items[0].received_qty)
        results.append('return quantities: received='+str(historical.items[0].received_qty)+', returned='+str(historical.items[0].returned_qty))
        fx=po(2,add_days(today,-2),currency='USD',fx=80);fx.submit()
        snapshot=current.as_dict();snapshot.pop('creation',None);snapshot.pop('name',None)
        comparison=compare_purchase_rates(snapshot)[0]
        check('foreign currency normalized to company currency',comparison['previous_po']==fx.name and comparison['previous_rate']==160)
        weighted=po(10,add_days(today,-1),qty=2)
        weighted.append('items',dict(item_code=item.name,qty=8,uom='Nos',rate=20,schedule_date=add_days(today,-1)))
        weighted.additional_discount_percentage=10
        weighted.apply_discount_on='Net Total'
        weighted.submit()
        comparison=compare_purchase_rates(snapshot)[0]
        check('duplicate lines use discounted quantity-weighted history',comparison['previous_po']==weighted.name and round(comparison['previous_rate'],6)==16.2)
        uom=frappe.get_doc(dict(doctype='UOM',uom_name='PURCHASING-TEST-PACK',must_be_whole_number=1)).insert()
        item.append('uoms',dict(uom=uom.name,conversion_factor=12));item.save()
        packed=po(120,add_days(today,-1))
        packed.items[0].uom=uom.name
        packed.items[0].conversion_factor=12
        packed.submit()
        comparison=compare_purchase_rates(snapshot)[0]
        check('actual alternate-UOM PO normalized to stock UOM',comparison['previous_po']==packed.name and comparison['previous_rate']==10)
        frappe.db.set_value('Purchase Order',packed.name,'status','Closed')
        check('closed order excluded from overdue report',not any(r['purchase_order']==packed.name for r in overdue_deliveries({'company':company,'supplier':supplier.name})))
        result={'passed':results,'count':len(results),'site':frappe.local.site,'fixtures_rolled_back':True}
        Path('/tmp/purchasing-docker-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        frappe.set_user('Administrator');frappe.db.rollback()


if __name__=='__main__':
    os.chdir('/home/frappe/frappe-bench/sites')
    frappe.init(site='production-staging.localhost',sites_path='/home/frappe/frappe-bench/sites');frappe.connect()
    try: run()
    finally: frappe.destroy()
