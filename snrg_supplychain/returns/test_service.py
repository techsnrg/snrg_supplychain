"""Small invariant tests; real Workflow/QC/ledger acceptance runs on Docker."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch
from types import SimpleNamespace


class Doc(dict):
    def __getattr__(self,key):return self.get(key)
    def as_dict(self):return dict(self)


class NativeGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake=types.ModuleType('frappe');fake._=lambda x:x;fake.PermissionError=PermissionError
        fake.throw=lambda msg,exc=ValueError:(_ for _ in ()).throw(exc(msg))
        fake.utils=types.ModuleType('frappe.utils');fake.utils.getdate=lambda value:value
        fake.utils.today=lambda:'2026-11-19';fake.utils.now_datetime=lambda:'2026-11-19 10:00:00'
        fake.utils.flt=lambda value:float(value or 0)
        cls.modules=patch.dict(sys.modules,{'frappe':fake,'frappe.utils':fake.utils});cls.modules.start()
        cls.service=importlib.import_module('snrg_supplychain.returns.native_service')
        cls.permissions=importlib.import_module('snrg_supplychain.returns.permissions');cls.fake=fake

    @classmethod
    def tearDownClass(cls):
        for name in ('native_service','legacy_service','permissions'):
            sys.modules.pop('snrg_supplychain.returns.'+name,None)
        cls.modules.stop()

    def test_md_cannot_approve_final_settlement_even_with_finance_role(self):
        self.fake.get_roles=lambda *_:['Managing Director','Accounts Manager']
        self.fake.session=SimpleNamespace(user='md')
        with patch.object(self.service,'settings',return_value=Doc(settlement_approver_role='Accounts Manager',waiver_approver='md')):
            with self.assertRaisesRegex(ValueError,'delegated'):
                self.service.require_finance_approver()

    def test_finance_approver_role_required(self):
        self.fake.get_roles=lambda *_:['Accounts User'];self.fake.session=SimpleNamespace(user='finance')
        with patch.object(self.service,'settings',return_value=Doc(settlement_approver_role='Accounts Manager',waiver_approver='md')):
            with self.assertRaises(PermissionError):self.service.require_finance_approver()

    def test_finance_manager_allowed(self):
        self.fake.get_roles=lambda *_:['Accounts Manager'];self.fake.session=SimpleNamespace(user='finance')
        with patch.object(self.service,'settings',return_value=Doc(settlement_approver_role='Accounts Manager',waiver_approver='md')):
            self.service.require_finance_approver()

    def test_qc_permission_hook_preserves_existing_reader(self):
        self.fake.get_roles=lambda *_:['Quality Manager'];self.fake.session=SimpleNamespace(user='qc')
        self.fake.get_meta=lambda _:SimpleNamespace(permissions=[Doc(role='Quality Manager',read=1,permlevel=0)])
        self.assertTrue(self.permissions.qi_permission(Doc()))
        self.assertEqual(self.permissions.qi_query(),'')

    def test_return_reviewer_denied_unrelated_qc(self):
        self.fake.get_roles=lambda *_:['Return Reviewer'];self.fake.session=SimpleNamespace(user='finance')
        self.fake.get_meta=lambda _:SimpleNamespace(permissions=[Doc(role='Return Reviewer',read=1,permlevel=0)])
        self.assertFalse(self.permissions.qi_permission(Doc()))
        self.assertTrue(self.permissions.qi_permission(Doc(custom_return_mra='MRA-1')))
        self.assertIn('custom_return_mra',self.permissions.qi_query())

    def test_preexisting_custom_reader_is_not_restricted(self):
        self.fake.get_roles=lambda *_:['Existing QC Reader','Return Reviewer'];self.fake.session=SimpleNamespace(user='auditor')
        self.fake.get_meta=lambda _:SimpleNamespace(permissions=[Doc(role='Existing QC Reader',read=1,permlevel=0)])
        self.assertTrue(self.permissions.qi_permission(Doc()))
        self.assertEqual(self.permissions.qi_query(),'')

    def test_approved_snapshot_detects_quantity_change(self):
        before=Doc(items=[Doc(item_code='A',qty=2)]);after=Doc(items=[Doc(item_code='A',qty=3)])
        with self.assertRaises(ValueError):self.service.immutable(after,before,['items'])

    def test_concession_digest_changes_when_amount_or_evidence_changes(self):
        before=Doc(settlement_items=[Doc(qty=2,net_rate=100)],restocking_charge=50,waiver_amount=0)
        after=Doc(before);after['restocking_charge']=25
        self.assertNotEqual(self.service.concession_digest(before),self.service.concession_digest(after))

    def test_rejected_only_case_requires_finalized_freight(self):
        context=dict(receipts=[Doc(freight_finalized=0)],allocations=[],incomplete=False)
        with self.assertRaisesRegex(ValueError,'actual freight'):
            self.service.verify_closure(Doc(),context)

    def test_rejected_only_case_requires_charge_accounting(self):
        context=dict(receipts=[Doc(name='R1',freight_finalized=1,customer_freight=50)],allocations=[])
        with patch.object(self.service,'require_complete_qc'), patch.object(self.service,'calculate_settlement') as calculate, patch.object(self.service,'verify_accounting') as verify:
            doc=Doc();self.service.verify_closure(doc,context)
            calculate.assert_called_once_with(doc,context);verify.assert_called_once_with(doc)
