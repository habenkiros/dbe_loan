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
    def test_decsi_sample_customer_shape(self):
        """Maps docs/customer API.txt sample customer 2000050041."""
        from loans.services.customer import SAMPLE_CUSTOMER_ID, normalize_customer_profile

        profile = fetch_customer_by_number(SAMPLE_CUSTOMER_ID)
        self.assertIsNotNone(profile)
        self.assertEqual(profile['customer_number'], SAMPLE_CUSTOMER_ID)
        self.assertEqual(profile['name'], 'Tekeste Jigar Meles')
        self.assertEqual(profile['phone_number'], '0945517351')  # 945517351 → local 09
        self.assertIn('MEKELE', profile['home_address'])
        self.assertEqual(profile['status'], 'ACTIVE')
        self.assertIn('Private Client', profile.get('customer_status') or '')
        self.assertEqual(profile['gender'], 'MALE')
        self.assertEqual(profile['date_of_birth'], '19900920')

        # Live JSON shape → same normalizer
        live_like = {
            'header': {'status': 'success'},
            'body': [{
                'customerId': SAMPLE_CUSTOMER_ID,
                'code': SAMPLE_CUSTOMER_ID,
                'name': 'Tekeste Jigar Meles',
                'phoneNumber': '945517351',
                'sms': '945517351',
                'street': 'MEKELE Debubu ADIHKI',
                'suburbTown': 'Tigray',
                'customerType': 'ACTIVE',
                'customerStatus': 'Standard Rated - Private Client',
                'gender': 'MALE',
                'dateOfBirth': '19900920',
            }],
        }
        row = live_like['body'][0]
        norm = normalize_customer_profile(row, customer_number=SAMPLE_CUSTOMER_ID)
        self.assertEqual(norm['phone_number'], '0945517351')
        self.assertEqual(norm['customer_number'], SAMPLE_CUSTOMER_ID)

    @override_settings(DECSI_BASE_URL='', DECSI_CUSTOMER_FORCE_MOCK=True)
    def test_mock_catalog_samrawit_and_others(self):
        from loans.services.customer import SAMPLE_CUSTOMER_ID
        from loans.services.mock_customers import SAMRAWIT_CUSTOMER_ID, list_mock_customer_ids

        ids = list_mock_customer_ids()
        self.assertEqual(len(ids), 12)
        self.assertIn(SAMPLE_CUSTOMER_ID, ids)
        self.assertIn(SAMRAWIT_CUSTOMER_ID, ids)

        sam = fetch_customer_by_number(SAMRAWIT_CUSTOMER_ID)
        self.assertIsNotNone(sam)
        self.assertEqual(sam['name'], 'Samrawit Berhe Gebre')
        self.assertEqual(sam['phone_number'], '0914220481')
        self.assertEqual(sam['gender'], 'FEMALE')
        self.assertEqual(sam['status'], 'ACTIVE')

        hagos = fetch_customer_by_number('2000050043')
        self.assertEqual(hagos['name'], 'Hagos Weldekidan Abraha')
        meron = fetch_customer_by_number('2000050052')
        self.assertEqual(meron['name'], 'Meron Hailemariam Zewde')

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
