"""Sheet 1 field provenance badges and document re-import."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from loans.forms import LoanRequestBasicInfoForm
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
from loans.services.appraisal_prefill import (
    prefill_basic_info_from_registration,
    reimport_sheet1_from_documents,
    sync_appraisal_from_sources,
)


User = get_user_model()


class Sheet1FieldSourcesTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Central')
        self.branch = Branch.objects.create(name='Main Src', district=district)
        collateral = CollateralType.objects.create(name='Building Src')
        self.category = LoanCategory.objects.create(name='Trade')
        self.officer = User.objects.create_user(
            username='src_officer', password='pass', phone_number='0911222444', role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-SRC-001',
            applicant_name='Source Applicant',
            phone_number='0911000111',
            amount_requested=Decimal('50000'),
            reason='Inventory purchase',
            category=self.category,
            branch=self.branch,
            collateral=collateral,
            operation_manager_approval=True,
            finance_approval=True,
            queue_approved=True,
            assigned_loan_officer=self.officer,
        )
        self.basic = LoanRequestBasicInfo.objects.create(loan_request=self.loan)
        self.doc_type = LoanApplicationDocumentType.objects.create(
            name='TIN Certificate',
            order=1,
            content_extraction_mappings='tin_number=TIN\nhome_address=Address',
        )

    def _add_doc_with_fields(self, fields):
        doc = LoanRequestDocument.objects.create(
            loan_request=self.loan,
            document_type=self.doc_type,
            uploaded_by=self.officer,
            file=SimpleUploadedFile('tin.txt', b'TIN: 123456789\nAddress: Mekelle', content_type='text/plain'),
            automated_checks={'extracted_fields': fields, 'extracted_text_preview': 'TIN: 123456789\nAddress: Mekelle'},
        )
        return doc

    def test_registration_records_sources(self):
        filled = prefill_basic_info_from_registration(self.loan, self.basic, only_empty=True)
        self.basic.refresh_from_db()
        self.assertTrue(filled)
        self.assertEqual(self.basic.business_name, 'Source Applicant')
        self.assertEqual(self.basic.field_sources['business_name']['source'], 'registration')
        self.assertEqual(self.basic.field_sources['form_of_ownership']['source'], 'default')

    def test_document_reimport_sets_document_badges(self):
        self._add_doc_with_fields({'tin_number': '123456789', 'home_address': 'Mekelle'})
        with patch('loans.services.appraisal_prefill.extract_fields_for_document') as mock_extract:
            mock_extract.return_value = {'tin_number': '123456789', 'home_address': 'Mekelle'}
            report = reimport_sheet1_from_documents(self.loan, only_empty=True)
        self.basic.refresh_from_db()
        self.assertEqual(report['total_fields'], 2)
        self.assertEqual(self.basic.tin_number, '123456789')
        self.assertEqual(self.basic.field_sources['tin_number']['source'], 'document')
        self.assertEqual(self.basic.field_sources['tin_number']['label'], 'TIN Certificate')
        self.assertEqual(self.basic.field_sources['home_address']['source'], 'document')

    def test_reimport_does_not_overwrite_filled_fields(self):
        self.basic.tin_number = 'EXISTING'
        self.basic.field_sources = {'tin_number': {'source': 'manual', 'label': 'Officer'}}
        self.basic.save()
        self._add_doc_with_fields({'tin_number': '999'})
        with patch('loans.services.appraisal_prefill.extract_fields_for_document') as mock_extract:
            mock_extract.return_value = {'tin_number': '999'}
            report = reimport_sheet1_from_documents(self.loan, only_empty=True)
        self.basic.refresh_from_db()
        self.assertEqual(report['total_fields'], 0)
        self.assertEqual(self.basic.tin_number, 'EXISTING')
        self.assertEqual(self.basic.field_sources['tin_number']['source'], 'manual')

    def test_form_save_marks_changed_fields_manual(self):
        self.basic.tin_number = '111'
        self.basic.field_sources = {'tin_number': {'source': 'document', 'label': 'TIN Certificate'}}
        self.basic.save()
        form = LoanRequestBasicInfoForm(
            data={
                'tin_number': '222',
                'gender': '',
                'age': '',
                'marital_status': '',
                'education_level': '',
                'home_address': '',
                'spouse_name': '',
                'spouse_occupation': '',
                'father_name': '',
                'grandfather_name': '',
                'business_name': '',
                'business_description': '',
                'business_address': '',
                'date_business_started': '',
                'form_of_ownership': '',
                'economic_sector': '',
                'subsector_activity': '',
                'employees_full_time': '',
                'employees_part_time': '',
                'employees_seasonal': '',
                'employees_ft_equivalent': '',
                'family_members_employed': '',
                'peak_sales_months': '',
                'lowest_sales_months': '',
                'number_business_owners': '',
                'term_months': '',
                'repayment_frequency': '',
                'interest_rate': '',
                'interest_basis': '',
                'grace_period_months': '',
                'interest_only_months': '',
                'instalments_per_year': '',
                'cash_contribution': '',
            },
            instance=self.basic,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.basic.refresh_from_db()
        self.assertEqual(self.basic.tin_number, '222')
        self.assertEqual(self.basic.field_sources['tin_number']['source'], 'manual')

    def test_sync_includes_field_sources_in_report(self):
        report = sync_appraisal_from_sources(self.loan, only_empty=True, include_collateral=False)
        self.assertIn('field_sources', report)
        self.assertEqual(report['field_sources']['business_name']['source'], 'registration')
