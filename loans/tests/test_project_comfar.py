"""COMFAR-style feasibility on the project desk — payback, break-even, sensitivity."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
    ProjectCashflowYear,
    ProjectProfile,
    ProjectSourceUseLine,
    ProjectTechnicalReview,
)
from loans.product_family import FAMILY_PROJECT
from loans.project_overlay import (
    compute_project_metrics,
    compute_sensitivity,
    ensure_plant_desks,
    project_committee_blockers,
)


User = get_user_model()


class ProjectComfarTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='CF Dist')
        self.branch = Branch.objects.create(name='CF Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='CF Coll')
        self.officer = User.objects.create_user(
            username='cf_lo', password='pass', phone_number='0911222666', role='loan_officer',
        )
        self.project_cat = LoanCategory.objects.create(
            name='CF Project', appraisal_mode='corporate', product_family=FAMILY_PROJECT,
        )

    def _loan(self, lid='LR-CF-1'):
        loan = LoanRequest.objects.create(
            loan_request_id=lid,
            applicant_name='Plant Co',
            phone_number='0911000888',
            amount_requested=Decimal('75000'),
            reason='Factory',
            category=self.project_cat,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
            appraisal_completed_at=timezone.now(),
        )
        LoanAppraisal.objects.create(
            loan_request=loan, created_by=self.officer,
            recommendation='approve', amount_approved=Decimal('75000'),
            term_approved_months=30, rate_approved=Decimal('12'),
        )
        return loan

    def _profile(self, loan, **extra):
        kwargs = dict(
            loan_request=loan,
            project_title='Mill',
            sector=ProjectProfile.SECTOR_INDUSTRY,
            total_project_cost=Decimal('100000'),
            promoter_equity=Decimal('25000'),
            requested_debt=Decimal('75000'),
            discount_rate_pct=Decimal('10'),
            current_account_opened=True,
        )
        kwargs.update(extra)
        profile = ProjectProfile.objects.create(**kwargs)
        ProjectSourceUseLine.objects.create(
            profile=profile, side='source', purpose='promoter_cash', amount=Decimal('25000'),
        )
        ProjectSourceUseLine.objects.create(
            profile=profile, side='source', purpose='dbe_loan', amount=Decimal('75000'),
        )
        ProjectSourceUseLine.objects.create(
            profile=profile, side='use', purpose='civil', amount=Decimal('100000'),
        )
        ensure_plant_desks(profile)
        profile.technical_reviews.update(
            status=ProjectTechnicalReview.STATUS_CLEARED,
            note='Plant pack ok',
            reviewed_at=timezone.now(),
            reviewed_by=self.officer,
        )
        return profile

    def test_payback_and_break_even_from_operating_statement(self):
        loan = self._loan('LR-CF-BE')
        profile = self._profile(loan)
        for year, cap, rev, opex, ds in (
            (1, Decimal('100'), Decimal('80000'), Decimal('40000'), Decimal('20000')),
            (2, Decimal('100'), Decimal('80000'), Decimal('40000'), Decimal('20000')),
            (3, Decimal('100'), Decimal('80000'), Decimal('40000'), Decimal('20000')),
        ):
            ProjectCashflowYear.objects.create(
                profile=profile, year_number=year,
                revenue=rev, operating_cost=opex, capacity_pct=cap,
                operating_cf=rev - opex, debt_service=ds,
            )
        metrics = compute_project_metrics(profile)
        self.assertEqual(metrics['payback_years'], Decimal('2.50'))
        self.assertEqual(metrics['break_even_capacity_pct'], Decimal('75.0'))
        self.assertIsNotNone(metrics['equity_irr_pct'])
        self.assertGreater(metrics['equity_irr_pct'], metrics['irr_pct'])
        self.assertEqual(metrics['dscr'], Decimal('2.00'))
        self.assertEqual(metrics['min_dscr'], Decimal('2.00'))
        self.assertTrue(metrics['has_operating_split'])
        self.assertGreater(metrics['bcr'], Decimal('0'))

    def test_net_cf_only_still_computes_npv_without_break_even(self):
        loan = self._loan('LR-CF-NET')
        profile = self._profile(loan)
        ProjectCashflowYear.objects.create(
            profile=profile, year_number=1, operating_cf=Decimal('40000'), debt_service=Decimal('20000'),
        )
        ProjectCashflowYear.objects.create(
            profile=profile, year_number=2, operating_cf=Decimal('50000'), debt_service=Decimal('20000'),
        )
        metrics = compute_project_metrics(profile)
        self.assertIsNotNone(metrics['npv'])
        self.assertIsNotNone(metrics['dscr'])
        self.assertIsNone(metrics['break_even_capacity_pct'])
        self.assertFalse(metrics['has_operating_split'])
        self.assertEqual(project_committee_blockers(loan), [])

    def test_sales_down_sensitivity_lowers_npv(self):
        loan = self._loan('LR-CF-SEN')
        profile = self._profile(loan)
        for year in (1, 2, 3):
            ProjectCashflowYear.objects.create(
                profile=profile, year_number=year,
                revenue=Decimal('80000'), operating_cost=Decimal('40000'),
                capacity_pct=Decimal('100'), operating_cf=Decimal('40000'),
                debt_service=Decimal('20000'),
            )
        cases = {c['key']: c for c in compute_sensitivity(profile)}
        self.assertIn('base', cases)
        self.assertIn('sales_down', cases)
        self.assertIn('delay', cases)
        self.assertLess(cases['sales_down']['npv'], cases['base']['npv'])
        self.assertLess(cases['opex_up']['npv'], cases['base']['npv'])
        self.assertLess(cases['capex_up']['npv'], cases['base']['npv'])
        self.assertLess(cases['delay']['npv'], cases['base']['npv'])
        self.assertGreater(cases['sales_up']['npv'], cases['base']['npv'])

    def test_officer_saves_sales_opex_year_and_sees_sensitivity(self):
        loan = self._loan('LR-CF-UI')
        self._profile(loan)
        self.client.force_login(self.officer)
        resp = self.client.post(reverse('project_add_cashflow', args=[loan.id]), {
            'year_number': '1',
            'capacity_pct': '80',
            'revenue': '80000',
            'operating_cost': '40000',
            'debt_service': '20000',
        })
        self.assertEqual(resp.status_code, 302)
        year = loan.project_profile.cashflows.get(year_number=1)
        self.assertEqual(year.operating_cf, Decimal('40000'))
        self.assertEqual(year.revenue, Decimal('80000'))
        resp = self.client.get(reverse('project_file', args=[loan.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Sensitivity')
        self.assertContains(resp, 'Break-even')
        self.assertContains(resp, 'Equity IRR')
        self.assertContains(resp, 'Sales −10%')
