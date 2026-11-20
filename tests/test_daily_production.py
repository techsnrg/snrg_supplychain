"""Service regressions without a bench; ERP ledger acceptance is separate."""
import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
frappe = types.ModuleType('frappe')
frappe.whitelist = lambda *a, **k: lambda fn: fn
frappe.PermissionError = PermissionError
frappe.throw = lambda message, *args: (_ for _ in ()).throw(ValueError(message))
frappe.request = None
utils = types.ModuleType('frappe.utils')
utils.cint = int
utils.flt = lambda value: float(value or 0)
utils.nowtime = lambda: '10:00:00'
sys.modules.setdefault('frappe',frappe)
sys.modules.setdefault('frappe.utils',utils)
service = importlib.import_module('snrg_supplychain.supply_chain.daily_production')
class Obj(types.SimpleNamespace):
    def get(self,key,default=None): return getattr(self,key,default)
frappe.flags = Obj()

class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.rates = patch.object(service,'valuation_issues',return_value=[]);self.rates.start();self.addCleanup(self.rates.stop)
        self.config = dict(company='SNRG',source_warehouse='Raw',target_warehouse='Finished',consumption_method='Stocked components',cost_center=None)
        self.doc = Obj(name='DPROD-1',modified='2026-11-17 10:00:00',posting_date='2026-11-17',posting_time='10:00:00',items=[Obj(name='r1',item_code='A',qty=20,uom='Nos',status='Pending'),Obj(name='r2',item_code='B',qty=40,uom='Nos',status='Pending')])
        self.stock = types.ModuleType('erpnext.stock.utils');self.stock.get_stock_balance = Mock(return_value=50)
        self.mods = patch.dict(sys.modules,{'erpnext':types.ModuleType('erpnext'),'erpnext.stock':types.ModuleType('erpnext.stock'),'erpnext.stock.utils':self.stock});self.mods.start();self.addCleanup(self.mods.stop)
    def entry(self,qty,item='POLYMER'):
        return Obj(bom_no='BOM-A',items=[Obj(item_code=item,item_name=item,s_warehouse='Raw',transfer_qty=qty,stock_uom='Kg')])
    def test_combined_shortage(self):
        with patch.object(service,'make_entry',side_effect=[self.entry(30),self.entry(40)]):result=service.review_doc(self.doc,self.config)
        self.assertEqual(result['shortages'][0]['required'],70)
        self.stock.get_stock_balance.assert_called_once_with('POLYMER','Raw','2026-11-17','10:00:00')
    def test_posted_rows_excluded_from_retry_demand(self):
        self.doc.items[0].status='Posted'
        with patch.object(service,'make_entry',return_value=self.entry(40)) as make:result=service.review_doc(self.doc,self.config)
        self.assertEqual(len(result['rows']),1);self.assertFalse(result['shortages']);self.assertEqual(make.call_count,1)
    def test_dependent_stages_blocked(self):
        with patch.object(service,'make_entry',return_value=self.entry(20,'B')):
            with self.assertRaisesRegex(ValueError,'dependent production stages'):service.review_doc(self.doc,self.config)
    def test_review_invalidated_by_settings_or_bom_changes(self):
        result={'rows':[dict(item_code='A',qty=20,bom_no='BOM-A',materials=[])]};before=service.review_token(self.doc,self.config,result)
        self.assertNotEqual(before,service.review_token(self.doc,dict(self.config,consumption_method='Expanded raw materials'),result))
        result['rows'][0]['bom_no']='BOM-A-NEW';self.assertNotEqual(before,service.review_token(self.doc,self.config,result))
    def test_posted_row_never_submits_again(self):
        doc=Obj(items=[Obj(name='r1',status='Posted')],flags=Obj(),save=Mock());db=Obj(commit=Mock(),rollback=Mock())
        with patch.multiple(service.frappe,set_user=Mock(),get_doc=Mock(return_value=doc),db=db,create=True),patch.object(service,'locked',return_value=doc),patch.object(service,'allowed'),patch.object(service,'make_entry') as make:service.process('DPROD-1','operator@example.com')
        make.assert_not_called();self.assertEqual(doc.status,'Posted')
    def test_submission_failure_rolls_back_and_other_row_continues(self):
        doc=self.doc
        doc.flags=Obj();doc.save=Mock();doc.settings_snapshot=__import__('json').dumps(self.config)
        db=Obj(commit=Mock(),rollback=Mock())
        entry=Obj(name='MAT-STE-1',insert=Mock(),submit=Mock())
        with patch.multiple(service.frappe,set_user=Mock(),get_doc=Mock(return_value=doc),db=db,create=True),patch.object(service,'locked',return_value=doc),patch.object(service,'allowed'),patch.object(service,'settings',return_value=self.config),patch.object(service,'check_entry_stock',return_value=[]),patch.object(service,'make_entry',side_effect=[ValueError('Insufficient stock'),entry]):
            service.process('DPROD-1','operator@example.com')
        db.rollback.assert_called_once()
        self.assertEqual(doc.items[0].status,'Failed')
        self.assertEqual(doc.items[1].stock_entry,'MAT-STE-1')
        self.assertEqual(doc.status,'Partially Posted')
        entry.submit.assert_called_once()
    def test_worker_reports_shortage_warning_without_blocking(self):
        entry=self.entry(70);entry.posting_date='2026-11-17';entry.posting_time='10:00:00'
        with patch.object(service.frappe,'db',Obj(sql=Mock()),create=True):
            warnings=service.check_entry_stock(entry)
        self.assertEqual(warnings[0]['required'],70)
        self.assertEqual(warnings[0]['available'],50)

if __name__=='__main__':unittest.main()
