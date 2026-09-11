"""Document checklist by loan category."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from loans.document_checklist import checklist_for_category, required_items
from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanApplicationDocumentType,
    LoanCategory,
    LoanCategoryDocumentRequirement,
    LoanDocumentRequest,
    LoanRequest,
)
from loans.services.document_auth import loan_documents_collateral_readiness

User = get_user_model()


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


class RequestLoanDocumentFormTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Req Dist')
        self.branch = Branch.objects.create(name='Req Branch', district=district)
        coll = CollateralType.objects.create(name='Req Coll')
        self.cat = LoanCategory.objects.create(name='Req Cat')
        self.dt_a = LoanApplicationDocumentType.objects.create(
            name='Req ID', order=1, is_required=True,
        )
        self.dt_b = LoanApplicationDocumentType.objects.create(
            name='Req TIN', order=2, is_required=True,
        )
        LoanCategoryDocumentRequirement.objects.create(
            category=self.cat, document_type=self.dt_a, is_required=True, order=1,
        )
        LoanCategoryDocumentRequirement.objects.create(
            category=self.cat, document_type=self.dt_b, is_required=True, order=2,
        )
        self.officer = User.objects.create_user(
            username='req_lo', password='pass', phone_number='0911888008',
            role='loan_officer', branch=self.branch,
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-REQ-DOC',
            applicant_name='Req Applicant',
            phone_number='0911222444',
            category=self.cat,
            collateral=coll,
            amount_requested=Decimal('10000'),
            reason='test',
            branch=self.branch,
            assigned_loan_officer=self.officer,
        )

    def test_detail_uses_one_checklist_form(self):
        client = Client()
        client.force_login(self.officer)
        resp = client.get(reverse('loan_request_detail', args=[self.loan.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Request documents')
        self.assertContains(resp, 'Request selected')
        self.assertContains(resp, 'lw-check-form')
        self.assertContains(resp, 'Required only')
        self.assertEqual(resp.content.decode().count('name="document_type_id"'), 2)
        self.assertNotIn('>Request</button>', resp.content.decode())

    def test_post_requests_multiple_types(self):
        client = Client()
        client.force_login(self.officer)
        resp = client.post(
            reverse('request_loan_document', args=[self.loan.id]),
            {'document_type_id': [str(self.dt_a.id), str(self.dt_b.id)]},
        )
        self.assertEqual(resp.status_code, 302)
        names = set(
            LoanDocumentRequest.objects.filter(loan_request=self.loan)
            .values_list('document_type__name', flat=True)
        )
        self.assertEqual(names, {'Req ID', 'Req TIN'})
