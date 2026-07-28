"""Credit Intelligence Phases 2–4: workspaces, portfolio, collateral, assistant."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from loans.ci_assistant import run_assistant_query
from loans.ci_collateral import build_collateral_intelligence
from loans.ci_decision import build_application_decision
from loans.ci_portfolio import build_portfolio_analytics
from loans.ci_workspaces import build_manager_workspace, build_officer_workspace
from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
)
from loans.portfolio_ledger import StubPortfolioLedgerAdapter, get_ledger_adapter

User = get_user_model()


class CreditIntelligencePhases234Tests(TestCase):
    def setUp(self):
        district = District.objects.create(name='CI2 Dist')
        self.branch = Branch.objects.create(name='CI2 Branch', district=district)
        collateral = CollateralType.objects.create(name='Building')
        category = LoanCategory.objects.create(name='MSME WC')
        self.bm = User.objects.create_user(
            username='ci2_bm', password='pass', phone_number='0911777001',
            role='branch_manager', branch=self.branch,
        )
        self.officer = User.objects.create_user(
            username='ci2_lo', password='pass', phone_number='0911777002',
            role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-CI2-1',
            applicant_name='Phase Applicant',
            phone_number='0911777010',
            amount_requested=Decimal('80000'),
            reason='WC',
            category=category,
            branch=self.branch,
            collateral=collateral,
            status='Pending',
            assigned_loan_officer=self.officer,
            committee_status=LoanRequest.COMMITTEE_PENDING,
        )
        self.appraisal = LoanAppraisal.objects.create(
            loan_request=self.loan,
            created_by=self.officer,
            recommendation='approve',
            amount_approved=Decimal('70000'),
            credit_score_total=Decimal('52.0'),
            credit_score_band='weak',
            collateral_total_value=Decimal('50000'),
            collateral_immovable_value=Decimal('50000'),
            collateral_coverage_ratio=Decimal('0.625'),
            dscr_annual=Decimal('0.85'),
        )

    def test_decision_card(self):
        card = build_application_decision(self.loan, self.appraisal)
        self.assertIsNotNone(card)
        self.assertEqual(card['decision']['code'], 'manual_review')
        self.assertIn('disclaimer', card)

    def test_officer_and_manager_workspaces(self):
        officer_ws = build_officer_workspace(self.officer)
        self.assertEqual(officer_ws['counts']['assigned'], 1)
        self.assertTrue(officer_ws['alerts'] or officer_ws['queue'] is not None)

        mgr = build_manager_workspace(self.bm)
        self.assertGreaterEqual(mgr['pipeline']['pending_committee'], 1)
        self.assertTrue(any(b['name'] == 'CI2 Branch' for b in mgr['branches']))

    def test_portfolio_and_collateral(self):
        port = build_portfolio_analytics(self.bm, {})
        self.assertEqual(port['summary']['total'], 1)
        self.assertGreaterEqual(port['summary']['low_dscr_count'], 1)

        coll = build_collateral_intelligence(self.bm)
        self.assertGreaterEqual(coll['kpis']['below_policy_count'], 1)
        self.assertGreater(coll['kpis']['total_collateral_value'], 0)

    def test_assistant_and_ledger_stub(self):
        self.assertFalse(get_ledger_adapter().is_connected())
        self.assertIsInstance(get_ledger_adapter(), StubPortfolioLedgerAdapter)

        npl = run_assistant_query(self.bm, 'What is the NPL ratio?')
        self.assertTrue(npl['understood'])
        self.assertIn('not available', npl['answer'].lower())

        risky = run_assistant_query(self.bm, 'Show risky loans')
        self.assertTrue(risky['understood'])
        self.assertTrue(risky['links'])

    def test_phase_pages_render(self):
        client = Client()
        client.force_login(self.bm)
        for name in (
            'home',
            'ci_insights',
            'ci_officer',
            'ci_manager',
            'ci_portfolio',
            'ci_collateral',
            'ci_assistant',
        ):
            resp = client.get(reverse(name))
            self.assertEqual(resp.status_code, 200, msg=name)

        api = client.get(reverse('api_ci_assistant') + '?q=compare+branch+risk')
        self.assertEqual(api.status_code, 200)
        self.assertIn('answer', api.json())

        dec = client.get(reverse('api_ci_application_decision', args=[self.loan.pk]))
        self.assertEqual(dec.status_code, 200)
        self.assertIn('decision', dec.json())

    def test_home_is_ci_not_duplicate_nav_needed(self):
        client = Client()
        client.force_login(self.bm)
        home = client.get(reverse('home'))
        self.assertContains(home, 'Executive overview')
        self.assertContains(home, 'ci-subnav')
        # Classic counts still available
        self.assertEqual(client.get(reverse('classic_home')).status_code, 200)
