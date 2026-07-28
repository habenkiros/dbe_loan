"""Phase 1 Credit Intelligence overview — metrics + role scoping."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from loans.credit_intelligence import build_overview, scoped_loans
from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
)

User = get_user_model()


class CreditIntelligencePhase1Tests(TestCase):
    def setUp(self):
        district = District.objects.create(name='CI Dist')
        self.branch_a = Branch.objects.create(name='CI Branch A', district=district)
        self.branch_b = Branch.objects.create(name='CI Branch B', district=district)
        collateral = CollateralType.objects.create(name='CI Coll')
        category = LoanCategory.objects.create(name='CI MSME')

        self.bm = User.objects.create_user(
            username='ci_bm', password='pass', phone_number='0911888001',
            role='branch_manager', branch=self.branch_a,
        )
        self.officer = User.objects.create_user(
            username='ci_lo', password='pass', phone_number='0911888002',
            role='loan_officer',
        )
        self.admin = User.objects.create_user(
            username='ci_admin', password='pass', phone_number='0911888003',
            role='admin',
        )

        self.loan_a = LoanRequest.objects.create(
            loan_request_id='LR-CI-A',
            applicant_name='CI Applicant A',
            phone_number='0911888010',
            amount_requested=Decimal('100000'),
            reason='WC',
            category=category,
            branch=self.branch_a,
            collateral=collateral,
            status='Approved',
            queue_approved=True,
            assigned_loan_officer=self.officer,
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            committee_final_amount=Decimal('90000'),
            disbursement_status=LoanRequest.DISBURSE_AWAITING_CONDITIONS,
        )
        LoanAppraisal.objects.create(
            loan_request=self.loan_a,
            created_by=self.officer,
            recommendation='approve',
            amount_approved=Decimal('90000'),
            credit_score_total=Decimal('48.0'),
            credit_score_band='weak',
            bureau_total_outstanding=Decimal('12000'),
        )

        self.loan_b = LoanRequest.objects.create(
            loan_request_id='LR-CI-B',
            applicant_name='CI Applicant B',
            phone_number='0911888011',
            amount_requested=Decimal('50000'),
            reason='WC',
            category=category,
            branch=self.branch_b,
            collateral=collateral,
            status='Pending',
            assigned_loan_officer=self.officer,
        )
        LoanAppraisal.objects.create(
            loan_request=self.loan_b,
            created_by=self.officer,
            recommendation='approve',
            amount_approved=Decimal('50000'),
            credit_score_total=Decimal('82.0'),
            credit_score_band='strong',
        )

    def test_branch_manager_scoped_out_of_other_branch(self):
        qs, label = scoped_loans(self.bm)
        ids = set(qs.values_list('loan_request_id', flat=True))
        self.assertIn('LR-CI-A', ids)
        self.assertNotIn('LR-CI-B', ids)
        self.assertEqual(label, 'CI Branch A')

    def test_build_overview_kpis_and_watchlist(self):
        data = build_overview(self.admin)
        keys = {k['key'] for k in data['kpis']}
        self.assertIn('approved_book', keys)
        self.assertIn('risk_flagged', keys)
        self.assertIn('high_risk_exposure', keys)
        self.assertEqual(data['pipeline']['total'], 2)
        self.assertGreaterEqual(data['pipeline']['approved_book'], 90000)
        # Weak scored approved loan should appear on watchlist
        wl_ids = {w['loan_request_id'] for w in data['watchlist']}
        self.assertIn('LR-CI-A', wl_ids)
        self.assertTrue(data['insights'])
        self.assertIn('Origination', data['disclaimer'])

    def test_officer_sees_assigned_only(self):
        data = build_overview(self.officer)
        self.assertEqual(data['scope_label'], 'Assigned to you')
        self.assertEqual(data['pipeline']['total'], 2)

    def test_overview_page_and_api(self):
        client = Client()
        client.force_login(self.bm)
        page = client.get(reverse('home'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Executive overview')
        self.assertContains(page, 'AI Credit Intelligence')

        ci = client.get(reverse('credit_intelligence_overview'))
        self.assertEqual(ci.status_code, 200)

        api = client.get(reverse('api_credit_intelligence_overview'))
        self.assertEqual(api.status_code, 200)
        payload = api.json()
        self.assertIn('kpis', payload)
        self.assertEqual(payload['scope_label'], 'CI Branch A')
        # Branch B loan must not inflate BM pipeline
        self.assertEqual(payload['pipeline']['total'], 1)

    def test_classic_home_still_available(self):
        client = Client()
        client.force_login(self.bm)
        resp = client.get(reverse('classic_home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Loan Dashboard')
