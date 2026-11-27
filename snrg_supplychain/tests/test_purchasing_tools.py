"""Local boundary tests without requiring an ERPNext bench."""
import importlib.util
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


class AttrDict(dict):
    __getattr__ = dict.get


class PurchasingTests(unittest.TestCase):
    def setUp(self):
        self.frappe = MagicMock()
        self.frappe._dict = AttrDict
        self.frappe.whitelist = lambda: lambda fn: fn
        self.frappe.parse_json = lambda value: value
        self.frappe._ = lambda value: value
        self.frappe.throw.side_effect = ValueError
        self.frappe.PermissionError = PermissionError
        utils = SimpleNamespace(flt=lambda value: float(value or 0),
            getdate=lambda value: value if isinstance(value, date) else date.fromisoformat(str(value)[:10]),
            nowdate=lambda: '2026-11-18')
        path = Path(__file__).parents[1] / 'supply_chain' / 'purchasing.py'
        spec = importlib.util.spec_from_file_location('purchasing_under_test', path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'frappe': self.frappe, 'frappe.utils': utils}):
            spec.loader.exec_module(self.module)

    def test_uom_and_currency_rate(self):
        self.assertEqual(self.module.normalized_rate(840, 12), 70)
        self.assertIsNone(self.module.normalized_rate(100, 0))
        self.assertEqual(self.module.variance_percent(110, 100), 10)
        self.assertIsNone(self.module.variance_percent(100, 0))

    def test_partial_receipt_and_overdelivery(self):
        self.assertEqual(self.module.pending_delivery(10, 4, 20), (6, 120))
        self.assertEqual(self.module.pending_delivery(10, 12, 20), (0, 0))
        self.assertEqual(self.module.pending_delivery(10, 2, 0), (8, 0))

    def test_weighted_history_and_exclusion_filters(self):
        source = MagicMock(name='source')
        source.name = 'OLD-PO'
        source.transaction_date = '2026-11-01'
        source.items = [SimpleNamespace(item_code='A', stock_uom='Nos', stock_qty=2,
            conversion_factor=1, base_net_amount=20), SimpleNamespace(item_code='A',
            stock_uom='Nos', stock_qty=8, conversion_factor=2, base_net_amount=160)]
        self.frappe.get_doc.return_value = source
        self.frappe.get_list.return_value = [AttrDict(name='OLD-PO')]
        self.frappe.db.exists.return_value = True
        doc = dict(doctype='Purchase Order', name='CURRENT', company='C', supplier='S',
            transaction_date='2026-11-10', creation='2026-11-10 12:00:00',
            items=[dict(idx=1, item_code='A', stock_uom='Nos', base_net_rate=40, conversion_factor=2)])
        result = self.module.compare_purchase_rates(doc)[0]
        self.assertEqual(result['previous_rate'], 18)
        self.assertEqual(result['current_rate'], 20)
        self.assertEqual(result['previous_po'], 'OLD-PO')
        filters = self.frappe.get_list.call_args.kwargs['filters']
        self.assertIn(['Purchase Order', 'docstatus', '=', 1], filters)
        self.assertIn(['Purchase Order', 'name', '!=', 'CURRENT'], filters)
        self.assertIn(['Purchase Order Item', 'stock_uom', '=', 'Nos'], filters)
        source.check_permission.assert_called_with('read')

    def test_missing_history_and_new_document_permissions(self):
        self.frappe.get_list.return_value = []
        doc = dict(doctype='Purchase Order', company='C', supplier='S', transaction_date='2026-11-18',
            items=[dict(item_code='A', stock_uom='Nos', base_net_rate=10, conversion_factor=1)])
        self.assertIsNone(self.module.compare_purchase_rates(doc)[0]['previous_rate'])
        self.frappe.has_permission.return_value = False
        with self.assertRaises(ValueError):
            self.module.compare_purchase_rates(doc)

    def test_report_date_receipt_and_drop_ship_boundaries(self):
        self.frappe.get_list.return_value = [AttrDict(name='P')]
        self.frappe.get_cached_value.return_value = 'INR'
        def row(due, received=0, direct=0):
            return SimpleNamespace(item_code='A', item_name='Item', schedule_date=due,
                qty=10, received_qty=received, base_net_rate=2, uom='Nos', delivered_by_supplier=direct)
        po = MagicMock()
        po.name='P'; po.supplier='S'; po.supplier_name='Supplier'; po.company='C'; po.owner='buyer'
        po.items=[row('2026-11-17', 3), row('2026-11-18'), row('2026-11-20'),
                  row('2026-11-01', 10), row('2026-11-01', 0, 1)]
        self.frappe.get_doc.return_value = po
        result=self.module.overdue_deliveries({'company':'C'})
        self.assertEqual(len(result),1)
        self.assertEqual((result[0]['pending_qty'],result[0]['pending_value'],result[0]['days_overdue']), (7,14,1))
        filters=self.frappe.get_list.call_args.kwargs['filters']
        self.assertEqual(filters['docstatus'],1)
        self.assertIn('Closed',filters['status'][1])
        po.check_permission.assert_called_with('read')

    def test_report_requires_company_and_read_permission(self):
        with self.assertRaises(ValueError): self.module.overdue_deliveries({})
        self.frappe.has_permission.return_value=False
        with self.assertRaises(ValueError): self.module.overdue_deliveries({'company':'C'})


if __name__ == '__main__': unittest.main()
