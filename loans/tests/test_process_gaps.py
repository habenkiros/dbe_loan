"""DECSI process-gap extras: collateral kind, risk gate, legal, equity/tranches, book ops."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from collateral.models import Building, BuildingValuation, LandValuation, SubWork, MainWork
from loans.collateral_kind import KIND_BUILDING, KIND_LAND, KIND_MIXED, compute_engine_totals
from loans.committee import officer_can_submit_to_committee
from loans.disbursement import (
    add_disbursement_tranche,
    disbursement_readiness,
    mark_disbursed,
    next_pending_tranche,
    start_disbursement_track,
    verify_own_contribution,
)
from loans.models import (
    AppraisalAmortizationEntry,
    AppraisalCondition,
    Branch,
    CollateralType,
    District,
    LoanAnalysisPolicyConfig,
    LoanAppraisal,
    LoanCategory,
    LoanCollectionAction,
    LoanCollateralLegalDocument,
    LoanRequest,
    LoanRequestBasicInfo,
)


User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='Gap Dist')
        self.branch = Branch.objects.create(name='Gap Branch', district=self.district)
        self.category = LoanCategory.objects.create(name='Gap Cat')
        self.officer = User.objects.create_user(
            username='gap_lo', password='pass', phone_number='0911000401', role='loan_officer',
        )
        self.risk = User.objects.create_user(
            username='gap_risk', password='pass', phone_number='0911000402', role='risk_compliance',
        )
        self.credit_head = User.objects.create_user(
            username='gap_ch', password='pass', phone_number='0911000403', role='credit_head',
        )


class CollateralKindTotalsTests(_Base):
    def test_mixed_sums_building_and_land(self):
        mixed = CollateralType.objects.create(name='Building + Land', kind=KIND_MIXED)
        loan = LoanRequest.objects.create(
            applicant_name='Mix', phone_number='0911000410', category=self.category,
            collateral=mixed, amount_requested=Decimal('100000'), reason='x',
            branch=self.branch, district=self.district, assigned_loan_officer=self.officer,
        )
        building = Building.objects.create(loan_request=loan, name='House A')
        mw = MainWork.objects.create(name='Civil')
        sw = SubWork.objects.create(main_work=mw, name='Wall')
        BuildingValuation.objects.create(
            building=building, sub_work=sw, quantity=Decimal('10'), unit_price=Decimal('100'),
        )
        LandValuation.objects.create(
            loan_request=loan, land_size_sqm=Decimal('50'), unit_price_per_sqm=Decimal('20'),
        )
        totals = compute_engine_totals(loan)
        self.assertEqual(totals['kind'], KIND_MIXED)
        self.assertEqual(totals['total_buildings'], Decimal('1000'))
        self.assertEqual(totals['land_value'], Decimal('1000'))
        self.assertEqual(totals['grand_total'], Decimal('2000'))

    def test_building_kind_drops_land_from_grand_total(self):
        btype = CollateralType.objects.create(name='House only', kind=KIND_BUILDING)
        loan = LoanRequest.objects.create(
            applicant_name='Bonly', phone_number='0911000411', category=self.category,
            collateral=btype, amount_requested=Decimal('100000'), reason='x',
            branch=self.branch, district=self.district, assigned_loan_officer=self.officer,
        )
        building = Building.objects.create(loan_request=loan, name='House B')
        mw = MainWork.objects.create(name='Civil2')
        sw = SubWork.objects.create(main_work=mw, name='Slab')
        BuildingValuation.objects.create(
            building=building, sub_work=sw, quantity=Decimal('2'), unit_price=Decimal('50'),
        )
        LandValuation.objects.create(
            loan_request=loan, land_size_sqm=Decimal('10'), unit_price_per_sqm=Decimal('100'),
        )
        totals = compute_engine_totals(loan)
        self.assertEqual(totals['grand_total'], Decimal('100'))
        self.assertEqual(totals['land_value'], Decimal('1000'))

    def test_name_inference_for_blank_kind(self):
        land = CollateralType.objects.create(name='Urban Land')
        self.assertEqual(land.resolved_kind(), KIND_LAND)
        self.assertTrue(land.uses_land())
        self.assertFalse(land.uses_building())


class RiskGateTests(_Base):
    def test_committee_blocked_until_risk_clears(self):
        LoanAnalysisPolicyConfig.objects.create(require_risk_review_before_committee=True)
        coll = CollateralType.objects.create(name='Risk Coll', kind=KIND_BUILDING)
        loan = LoanRequest.objects.create(
            applicant_name='R', phone_number='0911000412', category=self.category,
            collateral=coll, amount_requested=Decimal('50000'), reason='x',
            branch=self.branch, district=self.district, assigned_loan_officer=self.officer,
            appraisal_completed_at=timezone.now(),
        )
        LoanAppraisal.objects.create(
            loan_request=loan, created_by=self.officer,
            recommendation='approve', amount_approved=Decimal('50000'),
        )
        check = officer_can_submit_to_committee(loan)
        self.assertFalse(check['ok'])
        self.assertTrue(any('Risk' in e for e in check['errors']))
        client = Client()
        client.login(username='gap_risk', password='pass')
        resp = client.post(reverse('save_risk_review', args=[loan.id]), {
            'risk_review_note': 'Coverage acceptable',
            'action': 'clear',
        })
        self.assertEqual(resp.status_code, 302)
        loan.refresh_from_db()
        self.assertTrue(loan.risk_reviewed_at)


class ClosingAndTrancheTests(_Base):
    def _approved_loan(self, **extra):
        coll = CollateralType.objects.create(name='Close Coll', kind=KIND_BUILDING)
        loan = LoanRequest.objects.create(
            loan_request_id='LR-GAP-1',
            applicant_name='Close', phone_number='0911000413', category=self.category,
            collateral=coll, amount_requested=Decimal('80000'), reason='x',
            branch=self.branch, district=self.district, assigned_loan_officer=self.officer,
            appraisal_completed_at=timezone.now(),
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            committee_final_amount=Decimal('80000'),
            require_collateral_restriction=False,
            require_agreement_signatures=False,
            customer_number='1001',
            **extra,
        )
        appraisal = LoanAppraisal.objects.create(
            loan_request=loan, created_by=self.officer,
            recommendation='approve', amount_approved=Decimal('80000'),
            term_approved_months=12, rate_approved=Decimal('12'),
        )
        LoanRequestBasicInfo.objects.create(loan_request=loan, term_months=12, interest_rate=Decimal('12'))
        AppraisalAmortizationEntry.objects.create(
            appraisal=appraisal, period_number=1, payment_amount=Decimal('80000'),
            principal=Decimal('80000'), interest=Decimal('0'), balance_after=Decimal('0'),
        )
        start_disbursement_track(loan)
        loan.schedule_confirmed_at = timezone.now()
        loan.save(update_fields=['schedule_confirmed_at'])
        return loan

    def test_title_search_blocks_when_required(self):
        loan = self._approved_loan(require_title_search=True)
        readiness = disbursement_readiness(loan)
        self.assertTrue(any('Title' in b for b in readiness['blockers']))
        LoanCollateralLegalDocument.objects.create(
            loan_request=loan,
            kind=LoanCollateralLegalDocument.KIND_TITLE_SEARCH,
            status=LoanCollateralLegalDocument.STATUS_VERIFIED,
            reference_number='TS-1',
            issuing_office='Land office',
        )
        readiness = disbursement_readiness(loan)
        self.assertFalse(any('Title' in b for b in readiness['blockers']))

    def test_own_contribution_blocks_then_clears(self):
        loan = self._approved_loan(own_contribution_required=True)
        readiness = disbursement_readiness(loan)
        self.assertTrue(any('own-contribution' in b.lower() or 'Own' in b for b in readiness['blockers']))
        verify_own_contribution(loan, self.officer, amount=Decimal('10000'), note='Cash at branch')
        readiness = disbursement_readiness(loan)
        self.assertFalse(any('own-contribution' in b.lower() or 'Own' in b for b in readiness['blockers']))

    def test_tranches_partial_then_complete(self):
        loan = self._approved_loan()
        add_disbursement_tranche(loan, Decimal('30000'), note='first')
        add_disbursement_tranche(loan, Decimal('50000'), note='second')
        loan.disbursement_status = loan.DISBURSE_READY
        loan.finance_disbursement_approval = True
        loan.save(update_fields=['disbursement_status', 'finance_disbursement_approval'])
        ok, errors = mark_disbursed(loan, self.officer, notes='draw 1')
        self.assertTrue(ok, errors)
        loan.refresh_from_db()
        self.assertEqual(loan.disbursement_status, loan.DISBURSE_PARTIAL)
        self.assertIsNotNone(next_pending_tranche(loan))
        ok, errors = mark_disbursed(loan, self.officer, notes='draw 2')
        self.assertTrue(ok, errors)
        loan.refresh_from_db()
        self.assertEqual(loan.disbursement_status, loan.DISBURSE_DISBURSED)


class BookOpsTests(_Base):
    def setUp(self):
        super().setUp()
        coll = CollateralType.objects.create(name='Book Coll', kind=KIND_BUILDING)
        self.loan = LoanRequest.objects.create(
            applicant_name='Booked', phone_number='0911000414', category=self.category,
            collateral=coll, amount_requested=Decimal('40000'), reason='x',
            branch=self.branch, district=self.district, assigned_loan_officer=self.officer,
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            disbursement_status=LoanRequest.DISBURSE_DISBURSED,
            disbursed_at=timezone.now(),
        )
        self.appraisal = LoanAppraisal.objects.create(
            loan_request=self.loan, created_by=self.officer, recommendation='approve',
            amount_approved=Decimal('40000'),
        )
        AppraisalCondition.objects.create(
            appraisal=self.appraisal,
            condition_type=AppraisalCondition.TYPE_COVENANT,
            description='Keep insurance',
            required_before_disbursement=False,
        )

    def test_monitoring_and_collections_pages(self):
        client = Client()
        client.login(username='gap_lo', password='pass')
        self.assertEqual(client.get(reverse('monitoring_desk')).status_code, 200)
        self.assertEqual(client.get(reverse('monitoring_loan', args=[self.loan.id])).status_code, 200)
        self.assertEqual(client.get(reverse('collections_desk') + '?all=1').status_code, 200)
        resp = client.post(reverse('monitoring_add_visit', args=[self.loan.id]), {
            'visited_at': timezone.localdate().isoformat(),
            'notes': 'Site visit completed today.',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.loan.monitoring_visits.count(), 1)
        client.post(reverse('collections_add_action', args=[self.loan.id]), {
            'kind': LoanCollectionAction.KIND_REMINDER,
            'notes': 'Called borrower about instalment.',
        })
        self.assertEqual(self.loan.collection_actions.count(), 1)
        client.post(reverse('collections_workout', args=[self.loan.id]), {
            'action': 'request',
            'workout_note': 'Reschedule remaining 8 months at lower instalment.',
            'workout_proposed_term_months': '8',
        })
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.workout_status, LoanRequest.WORKOUT_REQUESTED)
        client.logout()
        client.login(username='gap_ch', password='pass')
        client.post(reverse('collections_workout', args=[self.loan.id]), {'action': 'approve'})
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.workout_status, LoanRequest.WORKOUT_APPROVED)
