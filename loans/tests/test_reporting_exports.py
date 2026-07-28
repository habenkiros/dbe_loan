"""Reporting / Excel export / branch dashboard smoke tests."""

from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from openpyxl import load_workbook

from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
)
from loans.reporting import build_pipeline_workbook, filtered_reporting_queryset


User = get_user_model()


class ReportingExportTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Report Dist')
        self.branch = Branch.objects.create(name='Report Branch', district=district)
        collateral = CollateralType.objects.create(name='Report Coll')
        category = LoanCategory.objects.create(name='Report MSME')
        self.bm = User.objects.create_user(
            username='rep_bm', password='pass', phone_number='0911999001',
            role='branch_manager', branch=self.branch,
        )
        self.officer = User.objects.create_user(
            username='rep_lo', password='pass', phone_number='0911999002',
            role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-REP-1',
            applicant_name='Report Applicant',
            phone_number='0911999003',
            amount_requested=Decimal('50000'),
            reason='WC',
            category=category,
            branch=self.branch,
            collateral=collateral,
            status='Approved',
            operation_manager_approval=True,
            finance_approval=True,
            queue_approved=True,
            assigned_loan_officer=self.officer,
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            committee_final_amount=Decimal('45000'),
            disbursement_status=LoanRequest.DISBURSE_AWAITING_CONDITIONS,
        )
        LoanAppraisal.objects.create(
            loan_request=self.loan,
            created_by=self.officer,
            recommendation='approve',
            amount_approved=Decimal('45000'),
            credit_score_total=Decimal('78.5'),
            credit_score_band='acceptable',
        )

    def test_pipeline_workbook_has_sheets(self):
        qs = filtered_reporting_queryset(self.bm, {})
        bio = build_pipeline_workbook(qs)
        wb = load_workbook(BytesIO(bio.getvalue()))
        self.assertIn('Pipeline', wb.sheetnames)
        self.assertIn('By branch', wb.sheetnames)
        rows = list(wb['Pipeline'].iter_rows(values_only=True))
        self.assertTrue(any(r[0] == 'LR-REP-1' for r in rows[1:]))

    def test_generate_report_xlsx(self):
        client = Client()
        client.force_login(self.bm)
        resp = client.get(reverse('generate_report'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            'spreadsheetml.sheet',
            resp['Content-Type'],
        )
        wb = load_workbook(BytesIO(resp.content))
        self.assertIn('Pipeline', wb.sheetnames)

    def test_branch_dashboard_and_hub(self):
        client = Client()
        client.force_login(self.bm)
        self.assertEqual(client.get(reverse('view_report_options')).status_code, 200)
        dash = client.get(reverse('branch_report_dashboard'))
        self.assertEqual(dash.status_code, 200)
        self.assertContains(dash, 'Branch reporting dashboard')
        self.assertContains(dash, 'LR-REP-1')

    def test_appraisal_pack_excel(self):
        client = Client()
        client.force_login(self.officer)
        resp = client.get(reverse('export_appraisal_pack_excel', args=[self.loan.pk]))
        self.assertEqual(resp.status_code, 200)
        wb = load_workbook(BytesIO(resp.content))
        self.assertIn('Summary', wb.sheetnames)

    def test_appraisal_pack_pdf_attachment(self):
        from loans.appraisal_pack_pdf import build_appraisal_pack_pdf, pdf_engine_name

        pdf_bytes, engine = build_appraisal_pack_pdf(self.loan)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
        self.assertIn(engine, ('weasyprint', 'reportlab'))

        client = Client()
        client.force_login(self.officer)
        resp = client.get(reverse('export_appraisal_pack_pdf', args=[self.loan.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertIn('attachment', resp['Content-Disposition'])
        self.assertTrue(resp.content.startswith(b'%PDF'))
        # Engine should at least be resolvable in this environment
        self.assertTrue(pdf_engine_name())
