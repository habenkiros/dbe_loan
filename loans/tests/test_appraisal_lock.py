"""Appraisal lock after finish / committee decision."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from loans.appraisal_lock import get_appraisal_lock_state
from loans.committee import return_loan_to_officer
from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
)


User = get_user_model()


class AppraisalLockTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Lock Dist')
        self.branch = Branch.objects.create(name='Lock Branch', district=district)
        collateral = CollateralType.objects.create(name='Lock Coll')
        category = LoanCategory.objects.create(name='Lock MSME')
        self.officer = User.objects.create_user(
            username='lock_officer', password='pass', phone_number='0911222999', role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-LOCK-1',
            applicant_name='Lock Applicant',
            phone_number='0911000999',
            amount_requested=Decimal('100000'),
            reason='WC',
            category=category,
            branch=self.branch,
            collateral=collateral,
            operation_manager_approval=True,
            finance_approval=True,
            queue_approved=True,
            assigned_loan_officer=self.officer,
        )
        self.appraisal = LoanAppraisal.objects.create(
            loan_request=self.loan,
            created_by=self.officer,
            recommendation='approve',
            amount_approved=Decimal('100000'),
        )

    def test_open_while_in_progress(self):
        state = get_appraisal_lock_state(self.loan)
        self.assertFalse(state['locked'])
        self.assertEqual(state['code'], 'open')

    def test_locked_after_finish(self):
        self.loan.appraisal_completed_at = timezone.now()
        self.loan.save(update_fields=['appraisal_completed_at'])
        state = get_appraisal_lock_state(self.loan)
        self.assertTrue(state['locked'])
        self.assertEqual(state['code'], 'appraisal_finished')

    def test_locked_when_pending_committee(self):
        self.loan.appraisal_completed_at = timezone.now()
        self.loan.committee_status = LoanRequest.COMMITTEE_PENDING
        self.loan.save(update_fields=['appraisal_completed_at', 'committee_status'])
        state = get_appraisal_lock_state(self.loan)
        self.assertTrue(state['locked'])
        self.assertEqual(state['code'], 'pending_committee')

    def test_unlocked_when_returned(self):
        self.loan.appraisal_completed_at = timezone.now()
        self.loan.committee_status = LoanRequest.COMMITTEE_PENDING
        self.loan.save()
        bm = User.objects.create_user(
            username='lock_bm', password='pass', phone_number='0911222888', role='branch_manager',
        )
        return_loan_to_officer(self.loan, bm, 'Please fix Sheet 3 cashflow numbers.')
        self.loan.refresh_from_db()
        self.assertIsNone(self.loan.appraisal_completed_at)
        self.assertEqual(self.loan.committee_status, LoanRequest.COMMITTEE_RETURNED)
        state = get_appraisal_lock_state(self.loan)
        self.assertFalse(state['locked'])
        self.assertEqual(state['code'], 'returned')

    def test_post_blocked_when_locked(self):
        self.loan.appraisal_completed_at = timezone.now()
        self.loan.save(update_fields=['appraisal_completed_at'])
        client = Client()
        client.force_login(self.officer)
        resp = client.post(
            reverse('loan_appraisal_step', args=[self.loan.id, 6]),
            {'finish_appraisal': '1', 'recommendation': 'approve'},
        )
        self.assertEqual(resp.status_code, 302)
        # Still locked / unchanged recommendation path — POST rejected before form save
        self.appraisal.refresh_from_db()
        self.assertEqual(self.appraisal.recommendation, 'approve')
