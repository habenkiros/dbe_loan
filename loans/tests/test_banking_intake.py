"""Core banking → Sheet 1 intake and conflict handling."""

from decimal import Decimal

from django.test import TestCase, override_settings

from django.contrib.auth import get_user_model

from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanCategory,
    LoanRequest,
    LoanRequestBasicInfo,
)
from loans.services.appraisal_prefill import apply_banking_profile, lookup_and_apply_banking
from loans.services.customer import fetch_customer_by_number, mock_fetch_customer_by_number


User = get_user_model()


class BankingIntakeTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Central Bank')
        self.branch = Branch.objects.create(name='Main Bank', district=district)
        collateral = CollateralType.objects.create(name='Building Bank')
        category = LoanCategory.objects.create(name='MSME Bank')
        self.officer = User.objects.create_user(
            username='bank_officer', password='pass', phone_number='0911222555', role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-BANK-001',
            applicant_name='Old Name',
            phone_number='0911000000',
            amount_requested=Decimal('50000'),
            reason='Working capital',
            category=category,
            branch=self.branch,
            collateral=collateral,
            operation_manager_approval=True,
            finance_approval=True,
            queue_approved=True,
            assigned_loan_officer=self.officer,
        )
        self.basic = LoanRequestBasicInfo.objects.create(
            loan_request=self.loan,
            business_name='Old Biz',
        )

    @override_settings(DECSI_BASE_URL='', DECSI_CUSTOMER_FORCE_MOCK=True)
    def test_mock_customer_lookup(self):
        profile = fetch_customer_by_number('1001')
        self.assertIsNotNone(profile)
        self.assertEqual(profile['customer_number'], '1001')
        self.assertIn('DEMO', profile['name'])
        self.assertEqual(profile['provider'], 'mock')

    def test_mock_missing_returns_none(self):
        self.assertIsNone(mock_fetch_customer_by_number('MISSING'))

    @override_settings(DECSI_BASE_URL='', DECSI_CUSTOMER_FORCE_MOCK=True)
    def test_banking_fills_empty_basic_fields(self):
        self.basic.business_name = ''
        self.basic.tin_number = ''
        self.basic.save()
        result = lookup_and_apply_banking(self.loan, customer_number='1001', only_empty=True)
        self.basic.refresh_from_db()
        self.loan.refresh_from_db()
        self.assertTrue(result['applied'])
        self.assertEqual(self.loan.customer_number, '1001')
        self.assertTrue(self.basic.tin_number)
        self.assertEqual(self.basic.field_sources['tin_number']['source'], 'banking')

    @override_settings(DECSI_BASE_URL='', DECSI_CUSTOMER_FORCE_MOCK=True)
    def test_banking_conflict_does_not_overwrite(self):
        result = lookup_and_apply_banking(self.loan, customer_number='1001', only_empty=True)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.applicant_name, 'Old Name')
        conflict_fields = {c['field'] for c in result['conflicts']}
        self.assertIn('applicant_name', conflict_fields)

    @override_settings(DECSI_BASE_URL='', DECSI_CUSTOMER_FORCE_MOCK=True)
    def test_accept_banking_overwrites_conflict(self):
        result = lookup_and_apply_banking(
            self.loan,
            customer_number='1001',
            only_empty=True,
            accept_fields=['applicant_name', 'business_name'],
        )
        self.loan.refresh_from_db()
        self.basic.refresh_from_db()
        self.assertIn('DEMO', self.loan.applicant_name)
        self.assertEqual(self.basic.field_sources['business_name']['source'], 'banking')
        self.assertTrue(any('applicant_name' in a for a in result['applied']))

    def test_apply_profile_direct(self):
        profile = {
            'customer_number': '99',
            'name': 'Bank Person',
            'phone_number': '0911999888',
            'tin_number': '1234567890',
            'home_address': 'Axum',
            'gender': 'Female',
            'provider': 'test',
        }
        self.basic.business_name = ''
        self.basic.save()
        result = apply_banking_profile(self.loan, self.basic, profile, only_empty=True)
        self.basic.refresh_from_db()
        self.assertIn('tin_number ← banking', result['applied'])
        self.assertEqual(self.basic.tin_number, '1234567890')
