"""Post-approval / disbursement track: CPs, schedule, status transitions."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from loans.disbursement import (
    can_mark_disbursed,
    confirm_schedule,
    disbursement_readiness,
    mark_disbursed,
    mark_ready_for_disbursement,
    open_required_cps,
    start_disbursement_track,
)
from loans.models import (
    AppraisalAmortizationEntry,
    AppraisalCondition,
    Branch,
    CollateralType,
    District,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
    LoanRequestBasicInfo,
)
from loans.views import _generate_amortization_schedule


User = get_user_model()


class DisbursementTrackTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Disb Dist')
        self.branch = Branch.objects.create(name='Disb Branch', district=district)
        collateral = CollateralType.objects.create(name='Disb Coll')
        category = LoanCategory.objects.create(name='Disb MSME')
        self.officer = User.objects.create_user(
            username='disb_officer', password='pass', phone_number='0911000111', role='loan_officer',
        )
        self.accountant = User.objects.create_user(
            username='disb_acct', password='pass', phone_number='0911000222', role='accountant',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-DISB-1',
            applicant_name='Disb Applicant',
            phone_number='0911000333',
            amount_requested=Decimal('120000'),
            reason='WC',
            category=category,
            branch=self.branch,
            collateral=collateral,
            operation_manager_approval=True,
            finance_approval=True,
            queue_approved=True,
            assigned_loan_officer=self.officer,
            appraisal_completed_at=timezone.now(),
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            committee_final_decision='approve',
            committee_final_amount=Decimal('100000'),
            committee_decided_at=timezone.now(),
        )
        self.appraisal = LoanAppraisal.objects.create(
            loan_request=self.loan,
            created_by=self.officer,
            recommendation='approve',
            amount_approved=Decimal('100000'),
            term_approved_months=12,
            rate_approved=Decimal('15'),
        )
        self.basic = LoanRequestBasicInfo.objects.create(
            loan_request=self.loan,
            term_months=12,
            interest_rate=Decimal('15'),
        )
        self.cp = AppraisalCondition.objects.create(
            appraisal=self.appraisal,
            condition_type=AppraisalCondition.TYPE_CP,
            description='Provide tax clearance.',
            required_before_disbursement=True,
            fulfilled=False,
            display_order=1,
        )
        AppraisalCondition.objects.create(
            appraisal=self.appraisal,
            condition_type=AppraisalCondition.TYPE_COVENANT,
            description='Keep insurance current.',
            required_before_disbursement=False,
            fulfilled=False,
            display_order=2,
        )
        start_disbursement_track(self.loan)
        self.loan.refresh_from_db()

    def test_start_sets_awaiting_conditions(self):
        self.assertEqual(self.loan.disbursement_status, LoanRequest.DISBURSE_AWAITING_CONDITIONS)

    def test_open_cp_blocks_readiness(self):
        readiness = disbursement_readiness(self.loan)
        self.assertFalse(readiness['ok'])
        self.assertEqual(len(open_required_cps(self.loan)), 1)
        self.assertTrue(any('condition' in b.lower() for b in readiness['blockers']))

    def test_covenant_not_required_for_gate(self):
        self.cp.fulfilled = True
        self.cp.save(update_fields=['fulfilled'])
        self.assertEqual(len(open_required_cps(self.loan)), 0)

    def test_schedule_must_match_final_amount(self):
        self.cp.fulfilled = True
        self.cp.save(update_fields=['fulfilled'])
        # Stale schedule based on requested amount
        AppraisalAmortizationEntry.objects.create(
            appraisal=self.appraisal,
            period_number=1,
            payment_amount=Decimal('10000'),
            principal=Decimal('120000'),
            interest=Decimal('0'),
            balance_after=Decimal('0'),
        )
        readiness = disbursement_readiness(self.loan)
        self.assertFalse(readiness['schedule']['amount_matches'])
        self.assertTrue(any('match' in b.lower() for b in readiness['blockers']))

        _generate_amortization_schedule(self.appraisal, self.basic, self.loan)
        readiness = disbursement_readiness(self.loan)
        self.assertTrue(readiness['schedule']['amount_matches'])
        self.assertEqual(readiness['schedule']['amount'], Decimal('100000'))

    def test_confirm_ready_disburse_flow(self):
        self.cp.fulfilled = True
        self.cp.save(update_fields=['fulfilled'])
        _generate_amortization_schedule(self.appraisal, self.basic, self.loan)

        ok, blockers = confirm_schedule(self.loan, self.officer)
        self.assertTrue(ok, blockers)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.disbursement_status, LoanRequest.DISBURSE_SCHEDULE_CONFIRMED)

        ok, blockers = mark_ready_for_disbursement(self.loan, self.officer)
        self.assertTrue(ok, blockers)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.disbursement_status, LoanRequest.DISBURSE_READY)

        self.assertTrue(can_mark_disbursed(self.officer, self.loan))
        self.assertFalse(can_mark_disbursed(self.accountant, self.loan))

        ok, blockers = mark_disbursed(self.loan, self.officer, notes='CBS ref 99')
        self.assertTrue(ok, blockers)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.disbursement_status, LoanRequest.DISBURSE_DISBURSED)
        self.assertEqual(self.loan.disbursed_by_id, self.officer.id)
        self.assertIn('CBS ref 99', self.loan.disbursement_notes)

    def test_admin_cannot_mark_disbursed(self):
        self.cp.fulfilled = True
        self.cp.save(update_fields=['fulfilled'])
        _generate_amortization_schedule(self.appraisal, self.basic, self.loan)
        confirm_schedule(self.loan, self.officer)
        mark_ready_for_disbursement(self.loan, self.officer)
        self.loan.refresh_from_db()

        admin = User.objects.create_user(
            username='disb_admin', password='pass', phone_number='0911000444', role='admin',
        )
        self.assertFalse(can_mark_disbursed(admin, self.loan))
        client = Client()
        client.force_login(admin)
        resp = client.post(reverse('post_approval_mark_disbursed', args=[self.loan.pk]))
        self.assertIn(resp.status_code, (302, 403))
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.disbursement_status, LoanRequest.DISBURSE_READY)

    def test_cannot_confirm_with_open_cp(self):
        _generate_amortization_schedule(self.appraisal, self.basic, self.loan)
        ok, blockers = confirm_schedule(self.loan, self.officer)
        self.assertFalse(ok)
        self.assertTrue(blockers)

    def test_officer_post_approval_pages(self):
        client = Client()
        client.force_login(self.officer)
        queue = client.get(reverse('post_approval_queue'))
        self.assertEqual(queue.status_code, 200)
        self.assertContains(queue, 'LR-DISB-1')
        detail = client.get(reverse('post_approval_detail', args=[self.loan.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'Conditions precedent')
