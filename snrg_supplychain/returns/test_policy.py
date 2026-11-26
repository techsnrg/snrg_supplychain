import unittest
from datetime import date
from decimal import Decimal
from snrg_supplychain.returns.policy import freight_split, number, rejection_deadlines, working_due


class ReturnPolicyTests(unittest.TestCase):
    def test_direct_vendor_payment_does_not_change_responsibility(self):
        self.assertEqual(freight_split(2000, 'Customer', 0), Decimal('2000.00'))
        self.assertEqual(freight_split(2000, 'SNRG', 2000), 0)
        self.assertEqual(freight_split(2000, 'Shared', 750), Decimal('750.00'))

    def test_pending_or_excess_allocation_rejected(self):
        for responsibility, amount in [('Pending QC', 0), ('Shared', 2001)]:
            with self.assertRaises(ValueError):
                freight_split(2000, responsibility, amount)

    def test_nonfinite_negative_inputs_rejected(self):
        for value in ['NaN', 'Infinity', '-1', '-Infinity', 'invalid']:
            with self.assertRaises(ValueError):
                number(value)

    def test_dispute_extends_collection_only_when_later(self):
        self.assertEqual(rejection_deadlines('2026-11-01'), (date(2026, 11, 16), date(2026, 12, 1)))
        self.assertEqual(rejection_deadlines('2026-11-01', '2026-11-25')[1], date(2026, 12, 10))
        self.assertEqual(rejection_deadlines('2026-11-01', '2026-11-03')[1], date(2026, 12, 1))

    def test_sla_uses_company_holiday_calendar(self):
        self.assertEqual(working_due('2026-11-20', 3, ['2026-11-21', '2026-11-22', '2026-11-23']), date(2026, 11, 26))


if __name__ == '__main__':
    unittest.main()
