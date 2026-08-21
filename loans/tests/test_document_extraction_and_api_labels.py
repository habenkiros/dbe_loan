"""Document default extraction mappings + Mock vs Live API labeling."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanApplicationDocumentType,
    LoanCategory,
    LoanRequest,
    LoanRequestBasicInfo,
    LoanRequestDocument,
)
from loans.services.appraisal_prefill import extract_fields_from_text, parse_extraction_mappings
from loans.services.customer import fetch_customer_by_number, profile_data_source
from loans.services.document_extraction_defaults import (
    default_mappings_text_for_name,
    ensure_document_type_extraction_defaults,
    sync_sheet1_from_documents,
)


User = get_user_model()


class DocumentExtractionDefaultsTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Central Ext')
        self.branch = Branch.objects.create(name='Main Ext', district=district)
        collateral = CollateralType.objects.create(name='Building Ext')
        self.category = LoanCategory.objects.create(name='Trade Ext')
        self.officer = User.objects.create_user(
            username='ext_officer', password='pass', phone_number='0911222555', role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-EXT-001',
            applicant_name='Old Name',
            phone_number='0911000222',
            amount_requested=Decimal('40000'),
            reason='Working capital',
            category=self.category,
            branch=self.branch,
            collateral=collateral,
            operation_manager_approval=True,
            finance_approval=True,
            queue_approved=True,
            assigned_loan_officer=self.officer,
        )
        LoanRequestBasicInfo.objects.create(loan_request=self.loan)

    def test_default_mappings_for_tin_and_id(self):
        self.assertIn('tin_number=TIN', default_mappings_text_for_name('TIN Certificate'))
        self.assertIn('gender=Sex', default_mappings_text_for_name('National ID / Kebele ID'))

    def test_ensure_seeds_empty_document_type(self):
        dt = LoanApplicationDocumentType.objects.create(
            name='Business License',
            order=1,
            content_extraction_mappings='',
            enable_ocr_match=False,
        )
        self.assertTrue(ensure_document_type_extraction_defaults(dt))
        dt.refresh_from_db()
        self.assertTrue(dt.content_extraction_mappings.strip())
        self.assertTrue(dt.enable_ocr_match)
        self.assertFalse(ensure_document_type_extraction_defaults(dt))  # no overwrite

    def test_sync_sheet1_uses_defaults_and_fills_empty_fields(self):
        dt = LoanApplicationDocumentType.objects.create(
            name='TIN Certificate',
            order=1,
            content_extraction_mappings='',  # force defaults at runtime
        )
        text = 'TIN: 9988776655\nTaxpayer Name: Demo Biz\nAddress: Adigrat Road'
        LoanRequestDocument.objects.create(
            loan_request=self.loan,
            document_type=dt,
            uploaded_by=self.officer,
            file=SimpleUploadedFile('tin.txt', text.encode(), content_type='text/plain'),
            automated_checks={'extracted_text_preview': text},
        )
        report = sync_sheet1_from_documents(self.loan, only_empty=True)
        self.assertGreaterEqual(report.get('total_fields', 0), 1)
        basic = LoanRequestBasicInfo.objects.get(loan_request=self.loan)
        self.assertEqual(str(basic.tin_number), '9988776655')
        dt.refresh_from_db()
        self.assertTrue(dt.content_extraction_mappings.strip())

    def test_extract_fields_from_default_tin_mappings(self):
        raw = default_mappings_text_for_name('TIN Certificate')
        mappings = parse_extraction_mappings(raw)
        found = extract_fields_from_text(mappings, 'TIN: 1122334455\nAddress: Mekelle')
        self.assertEqual(found.get('tin_number'), '1122334455')
        self.assertEqual(found.get('home_address'), 'Mekelle')


class CustomerProviderLabelTests(TestCase):
    def test_profile_data_source_labels(self):
        self.assertEqual(profile_data_source({'provider': 'decsi_party'})['code'], 'live')
        self.assertEqual(profile_data_source({'provider': 'mock'})['code'], 'mock')
        self.assertEqual(profile_data_source({'provider': 'mock_fallback'})['code'], 'fallback')

    @override_settings(DECSI_BASE_URL='', DECSI_CUSTOMER_FORCE_MOCK=False)
    def test_fetch_without_base_is_mock(self):
        profile = fetch_customer_by_number('2000050041')
        self.assertIsNotNone(profile)
        self.assertEqual(profile.get('provider'), 'mock')
        self.assertEqual(profile.get('data_source', {}).get('code'), 'mock')

    @override_settings(
        DECSI_BASE_URL='https://example.invalid',
        DECSI_CUSTOMER_FORCE_MOCK=False,
        DECSI_CUSTOMER_FALLBACK_MOCK=False,
    )
    @patch('loans.services.customer.live_fetch_customer_by_number', return_value=None)
    def test_live_miss_no_silent_fallback(self, _mock_live):
        self.assertIsNone(fetch_customer_by_number('2000050041'))

    @override_settings(
        DECSI_BASE_URL='https://example.invalid',
        DECSI_CUSTOMER_FORCE_MOCK=False,
        DECSI_CUSTOMER_FALLBACK_MOCK=True,
    )
    @patch('loans.services.customer.live_fetch_customer_by_number', return_value=None)
    def test_live_miss_with_fallback_marks_mock_fallback(self, _mock_live):
        profile = fetch_customer_by_number('2000050041')
        self.assertIsNotNone(profile)
        self.assertEqual(profile.get('provider'), 'mock_fallback')
        self.assertEqual(profile.get('data_source', {}).get('code'), 'fallback')
