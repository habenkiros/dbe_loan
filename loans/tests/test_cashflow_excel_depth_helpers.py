"""Pure unit tests for Sheet 3 ratio / grid helpers (no DB)."""

from decimal import Decimal
import unittest

from loans.cashflow_utils import compute_balance_sheet_ratios, parse_monthly_cashflow_grid_from_post, seed_monthly_grid_from_averages


class CashflowExcelDepthHelpersTests(unittest.TestCase):
    def test_balance_sheet_ratios(self):
        ratios = compute_balance_sheet_ratios(
            current_assets=200, current_liabilities=100, inventory=50,
            total_liabilities=300, equity=150,
        )
        self.assertEqual(ratios['ratio_current'], Decimal('2.00'))
        self.assertEqual(ratios['ratio_acid_test'], Decimal('1.50'))
        self.assertEqual(ratios['ratio_debt_equity'], Decimal('2.00'))

    def test_seed_grid(self):
        rows = seed_monthly_grid_from_averages(Decimal('1000'), Decimal('400'))
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[0]['sales'], '1000')
        self.assertEqual(rows[0]['net'], '600.00')

    def test_parse_grid_post(self):
        post = {'grid_sales_1': '10', 'grid_expenses_1': '4', 'grid_sales_2': '', 'grid_expenses_2': ''}
        rows = parse_monthly_cashflow_grid_from_post(post)
        self.assertEqual(rows[0]['net'], '6.00')
        self.assertIsNone(rows[1]['sales'])


if __name__ == '__main__':
    unittest.main()
