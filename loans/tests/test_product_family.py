"""Product family + funding window (DBE Phase 0) — DECSI defaults stay general."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from loans.appraisal_mode import MODE_MSME, resolve_appraisal_mode
from loans.models import (
    Branch,
    CollateralType,
    District,
    FinancingFund,
    LoanCategory,
    LoanRequest,
)
from loans.product_family import (
    FAMILY_GENERAL,
    FAMILY_PROJECT,
    parse_product_family,
    resolve_product_family,
    suggested_appraisal_mode,
)


User = get_user_model()


class ProductFamilyTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='PF Dist')
        self.branch = Branch.objects.create(name='PF Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='PF Collateral')
        self.officer = User.objects.create_user(
            username='pf_officer', password='pass', phone_number='0911222777', role='loan_officer',
        )

    def _loan(self, category, **kwargs):
        defaults = dict(
            loan_request_id='LR-PF-001',
            applicant_name='Test Co',
            phone_number='0911000444',
            amount_requested=Decimal('100000'),
            reason='WC',
            category=category,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
        )
        defaults.update(kwargs)
        return LoanRequest.objects.create(**defaults)

    def test_existing_category_defaults_to_general(self):
        cat = LoanCategory.objects.create(name='MSME Trade PF', appraisal_mode=MODE_MSME)
        self.assertEqual(cat.product_family, FAMILY_GENERAL)
        loan = self._loan(cat)
        self.assertEqual(resolve_product_family(loan), FAMILY_GENERAL)
        self.assertEqual(resolve_appraisal_mode(loan), MODE_MSME)

    def test_project_family_uses_project_desk(self):
        cat = LoanCategory.objects.create(
            name='Project Financing PF',
            appraisal_mode=FAMILY_PROJECT,
            product_family=FAMILY_PROJECT,
        )
        loan = self._loan(cat, loan_request_id='LR-PF-002')
        self.assertEqual(resolve_product_family(loan), FAMILY_PROJECT)
        self.assertEqual(resolve_appraisal_mode(loan), FAMILY_PROJECT)
        self.assertEqual(suggested_appraisal_mode(FAMILY_PROJECT), FAMILY_PROJECT)

    def test_parse_family_aliases(self):
        self.assertEqual(parse_product_family('Project Financing'), FAMILY_PROJECT)
        self.assertEqual(parse_product_family('ijarah'), 'ifb_ijarah')
        self.assertEqual(parse_product_family(''), FAMILY_GENERAL)

    def test_optional_funding_window(self):
        cat = LoanCategory.objects.create(name='WC PF', appraisal_mode=MODE_MSME)
        fund = FinancingFund.objects.create(
            code='kfw21826',
            name='EU/KfW MSME recovery',
            kind=FinancingFund.KIND_DONOR,
            source_name='KfW / EU',
        )
        self.assertEqual(fund.code, 'KFW21826')
        loan = self._loan(cat, loan_request_id='LR-PF-003', financing_fund=fund)
        self.assertEqual(loan.financing_fund_id, fund.id)
        untagged = self._loan(cat, loan_request_id='LR-PF-004')
        self.assertIsNone(untagged.financing_fund_id)

    def test_superuser_can_open_funding_windows(self):
        admin = User.objects.create_superuser(
            username='pf_admin', password='pass', phone_number='0911222888',
        )
        self.client.force_login(admin)
        resp = self.client.get(reverse('manage_financing_funds'))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(reverse('manage_financing_funds'), {
            'code': 'RUFIP3',
            'name': 'RUFIP III',
            'kind': FinancingFund.KIND_DONOR,
            'source_name': 'IFAD',
            'is_active': 'on',
            'notes': '',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(FinancingFund.objects.filter(code='RUFIP3').exists())
