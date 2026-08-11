"""Document checklist by loan category."""

from decimal import Decimal

from django.test import TestCase

from loans.document_checklist import checklist_for_category, required_items
from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanApplicationDocumentType,
    LoanCategory,
    LoanCategoryDocumentRequirement,
    LoanRequest,
)
from loans.services.document_auth import loan_documents_collateral_readiness


class LoanCategoryDocumentChecklistTests(TestCase):
    def setUp(self):
        self.cat_msme = LoanCategory.objects.create(
            name='MSME WC Pack Test', appraisal_mode=LoanCategory.MODE_MSME,
        )
        self.cat_salary = LoanCategory.objects.create(
            name='Salary Pack Test', appraisal_mode=LoanCategory.MODE_MSME,
        )
        self.dt_id = LoanApplicationDocumentType.objects.create(
            name='National ID Pack Test', order=10, is_required=True,
        )
        self.dt_tin = LoanApplicationDocumentType.objects.create(
            name='TIN Pack Test', order=20, is_required=True,
        )
        self.dt_payslip = LoanApplicationDocumentType.objects.create(
            name='Payslip Pack Test', order=30, is_required=True,
        )
        self.dt_opt = LoanApplicationDocumentType.objects.create(
            name='Optional Letter Pack Test', order=40, is_required=False,
        )
        LoanCategoryDocumentRequirement.objects.create(
            category=self.cat_msme, document_type=self.dt_id, is_required=True, order=1,
        )
        LoanCategoryDocumentRequirement.objects.create(
            category=self.cat_msme, document_type=self.dt_tin, is_required=True, order=2,
        )
        LoanCategoryDocumentRequirement.objects.create(
            category=self.cat_msme, document_type=self.dt_opt, is_required=False, order=3,
        )
        LoanCategoryDocumentRequirement.objects.create(
            category=self.cat_salary, document_type=self.dt_id, is_required=True, order=1,
        )
        LoanCategoryDocumentRequirement.objects.create(
            category=self.cat_salary, document_type=self.dt_payslip, is_required=True, order=2,
        )

    def test_msme_pack_excludes_payslip(self):
        items = checklist_for_category(self.cat_msme)
        names = [i.name for i in items]
        self.assertIn('National ID Pack Test', names)
        self.assertIn('TIN Pack Test', names)
        self.assertNotIn('Payslip Pack Test', names)
        self.assertEqual(len(required_items(items)), 2)

    def test_salary_pack_uses_payslip_not_tin(self):
        items = checklist_for_category(self.cat_salary)
        names = [i.name for i in items]
        self.assertIn('Payslip Pack Test', names)
        self.assertNotIn('TIN Pack Test', names)

    def test_fallback_when_no_pack(self):
        empty = LoanCategory.objects.create(name='Empty Pack Cat', appraisal_mode=LoanCategory.MODE_MSME)
        items = checklist_for_category(empty)
        # Global catalog includes all types seeded in setUp
        self.assertGreaterEqual(len(items), 4)

    def test_loan_readiness_uses_category_required_only(self):
        district = District.objects.create(name='DDoc')
        branch = Branch.objects.create(name='BDoc', district=district)
        coll = CollateralType.objects.create(name='CDoc')
        loan = LoanRequest.objects.create(
            loan_request_id='LR-DOC-PACK-001',
            applicant_name='Doc Tester',
            phone_number='0911222333',
            category=self.cat_salary,
            collateral=coll,
            amount_requested=Decimal('10000'),
            reason='test',
            branch=branch,
        )
        readiness = loan_documents_collateral_readiness(loan)
        self.assertIn('National ID Pack Test', readiness['missing_required'])
        self.assertIn('Payslip Pack Test', readiness['missing_required'])
        self.assertNotIn('TIN Pack Test', readiness['missing_required'])
