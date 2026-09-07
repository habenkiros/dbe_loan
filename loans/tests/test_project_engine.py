"""Phase B project engine — policy, viability, plant desks. DECSI general stays ungated."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from loans.committee import officer_can_submit_to_committee
from loans.engines import get_engine
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
from loans.product_family import FAMILY_GENERAL, FAMILY_PROJECT
from loans.project_overlay import (
    compute_project_metrics,
    ensure_plant_desks,
    project_committee_blockers,
    project_disbursement_blockers,
)


User = get_user_model()


class ProjectEnginePhaseBTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='PB Dist')
        self.branch = Branch.objects.create(name='PB Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='PB Coll')
        self.officer = User.objects.create_user(
            username='pb_lo', password='pass', phone_number='0911222555', role='loan_officer',
        )
        self.general = LoanCategory.objects.create(
            name='PB MSME', appraisal_mode='msme', product_family=FAMILY_GENERAL,
        )
        self.project_cat = LoanCategory.objects.create(
            name='PB Project', appraisal_mode='corporate', product_family=FAMILY_PROJECT,
        )

    def _loan(self, category, lid='LR-PB-1', **extra):
        defaults = dict(
            loan_request_id=lid,
            applicant_name='Plant Co',
            phone_number='0911000777',
            amount_requested=Decimal('75000'),
            reason='Factory',
            category=category,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
            appraisal_completed_at=timezone.now(),
        )
        defaults.update(extra)
        loan = LoanRequest.objects.create(**defaults)
        LoanAppraisal.objects.create(
            loan_request=loan, created_by=self.officer,
            recommendation='approve', amount_approved=Decimal('75000'),
        )
        return loan

    def _balanced(self, loan, **extra):
        kwargs = dict(
            loan_request=loan,
            project_title='Mill',
            sector=ProjectProfile.SECTOR_INDUSTRY,
            implementation_months=18,
            grace_months=12,
            debt_equity_policy=ProjectProfile.DE_75_25,
            total_project_cost=Decimal('100000'),
            promoter_equity=Decimal('25000'),
            requested_debt=Decimal('75000'),
            current_account_opened=True,
            npv=Decimal('12000'),
            irr_pct=Decimal('18'),
            project_dscr=Decimal('1.40'),
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

    def test_general_committee_has_no_project_policy(self):
        loan = self._loan(self.general, lid='LR-PB-G')
        self.assertEqual(get_engine(loan).committee_blockers(), [])
        check = officer_can_submit_to_committee(loan)
        self.assertFalse(any('NPV' in e or 'Plant' in e or 'Debt is' in e for e in check['errors']))

    def test_project_blocked_from_committee_without_viability(self):
        loan = self._loan(self.project_cat, lid='LR-PB-NV')
        self._balanced(loan, npv=None, irr_pct=None, project_dscr=None)
        blockers = project_committee_blockers(loan)
        self.assertTrue(any('NPV' in b or 'IRR' in b or 'DSCR' in b for b in blockers))
        check = officer_can_submit_to_committee(loan)
        self.assertFalse(check['ok'])

    def test_debt_share_over_band_blocks_committee(self):
        loan = self._loan(self.project_cat, lid='LR-PB-DE')
        self._balanced(loan, requested_debt=Decimal('90000'), promoter_equity=Decimal('10000'))
        blockers = project_committee_blockers(loan)
        self.assertTrue(any('Debt is' in b for b in blockers))

    def test_grace_over_five_years_blocks(self):
        loan = self._loan(self.project_cat, lid='LR-PB-GR')
        self._balanced(loan, grace_months=72)
        self.assertTrue(any('Grace' in b for b in project_committee_blockers(loan)))

    def test_uncleared_plant_desk_blocks_committee(self):
        loan = self._loan(self.project_cat, lid='LR-PB-DS')
        profile = self._balanced(loan)
        profile.technical_reviews.filter(desk='civil').update(
            status=ProjectTechnicalReview.STATUS_PENDING,
        )
        self.assertTrue(any('Plant desks' in b for b in project_committee_blockers(loan)))

    def test_ready_project_can_go_to_committee(self):
        loan = self._loan(self.project_cat, lid='LR-PB-OK')
        self._balanced(loan)
        self.assertEqual(project_committee_blockers(loan), [])

    def test_dscr_below_one_blocks(self):
        loan = self._loan(self.project_cat, lid='LR-PB-DSCR')
        self._balanced(loan, project_dscr=Decimal('0.80'))
        self.assertTrue(any('DSCR' in b for b in project_committee_blockers(loan)))

    def test_cashflow_years_compute_metrics(self):
        loan = self._loan(self.project_cat, lid='LR-PB-CF')
        profile = self._balanced(loan, npv=None, irr_pct=None, project_dscr=None, discount_rate_pct=Decimal('10'))
        ProjectCashflowYear.objects.create(
            profile=profile, year_number=1, operating_cf=Decimal('40000'), debt_service=Decimal('20000'),
        )
        ProjectCashflowYear.objects.create(
            profile=profile, year_number=2, operating_cf=Decimal('50000'), debt_service=Decimal('20000'),
        )
        metrics = compute_project_metrics(profile)
        self.assertIsNotNone(metrics['npv'])
        self.assertIsNotNone(metrics['dscr'])
        self.assertGreaterEqual(metrics['dscr'], Decimal('1.00'))
        self.assertEqual(project_committee_blockers(loan), [])

    def test_staggered_equity_blocks_first_draw(self):
        loan = self._loan(self.project_cat, lid='LR-PB-EQ')
        profile = self._balanced(loan, equity_plan=ProjectProfile.EQUITY_STAGGERED, equity_stage=0)
        loan.own_contribution_verified_at = timezone.now()
        loan.save(update_fields=['own_contribution_verified_at'])
        blockers = project_disbursement_blockers(loan)
        self.assertTrue(any('Staggered equity' in b for b in blockers))
        profile.equity_stage = 1
        profile.save(update_fields=['equity_stage'])
        self.assertFalse(any('Staggered equity' in b for b in project_disbursement_blockers(loan)))
