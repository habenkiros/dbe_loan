"""Approval routing amount bands and stuck-progress reconcile."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from loans.committee import get_levels_for_loan, reconcile_approval_routing
from loans.models import (
    ApprovalCommitteeLevel,
    Branch,
    CollateralType,
    District,
    LoanAppraisal,
    LoanApprovalLevelProgress,
    LoanCategory,
    LoanCommitteeVote,
    LoanRequest,
)


User = get_user_model()


class ApprovalRoutingReconcileTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Route Dist')
        self.branch = Branch.objects.create(name='Route Branch', district=district)
        collateral = CollateralType.objects.create(name='Route Collateral')
        category = LoanCategory.objects.create(name='Route Cat')
        self.officer = User.objects.create_user(
            username='route_lo', password='pass', phone_number='0911999001', role='loan_officer',
        )
        self.bm = User.objects.create_user(
            username='route_bm', password='pass', phone_number='0911999002',
            role='branch_manager', branch=self.branch,
        )
        ApprovalCommitteeLevel.objects.all().delete()
        self.branch_level = ApprovalCommitteeLevel.objects.create(
            key='branch',
            name='Branch',
            sequence_order=1,
            is_active=True,
            min_loan_amount=Decimal('0'),
            max_loan_amount=Decimal('1999000'),
            min_approvals_required=2,
            min_declines_required=2,
        )
        self.district_level = ApprovalCommitteeLevel.objects.create(
            key='district',
            name='District',
            sequence_order=2,
            is_active=True,
            min_loan_amount=Decimal('2000001'),
            max_loan_amount=Decimal('5000000'),
            min_approvals_required=2,
            min_declines_required=2,
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-ROUTE-1M',
            applicant_name='Route Test',
            phone_number='0911000999',
            amount_requested=Decimal('1000000'),
            reason='WC',
            category=category,
            branch=self.branch,
            collateral=collateral,
            queue_approved=True,
            assigned_loan_officer=self.officer,
            appraisal_completed_at=timezone.now(),
            submitted_to_committee_at=timezone.now(),
            committee_status=LoanRequest.COMMITTEE_PENDING,
            current_approval_level=self.district_level,
        )
        LoanAppraisal.objects.create(
            loan_request=self.loan,
            created_by=self.officer,
            recommendation='approve',
            amount_approved=Decimal('1000000'),
        )
        # Branch already approved; District pending from an older broader config.
        LoanApprovalLevelProgress.objects.create(
            loan_request=self.loan,
            level=self.branch_level,
            status=LoanApprovalLevelProgress.STATUS_APPROVED,
            started_at=timezone.now(),
            completed_at=timezone.now(),
        )
        LoanApprovalLevelProgress.objects.create(
            loan_request=self.loan,
            level=self.district_level,
            status=LoanApprovalLevelProgress.STATUS_PENDING,
            started_at=timezone.now(),
        )
        LoanCommitteeVote.objects.create(
            loan_request=self.loan,
            approval_level=self.branch_level,
            member=self.officer,
            vote=LoanCommitteeVote.VOTE_APPROVE,
        )
        LoanCommitteeVote.objects.create(
            loan_request=self.loan,
            approval_level=self.branch_level,
            member=self.bm,
            vote=LoanCommitteeVote.VOTE_APPROVE,
        )

    def test_one_million_only_hits_branch_band(self):
        levels = get_levels_for_loan(self.loan)
        self.assertEqual([l.key for l in levels], ['branch'])

    def test_reconcile_skips_inapplicable_district_and_finalizes(self):
        finished = reconcile_approval_routing(self.loan)
        self.assertTrue(finished)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.committee_status, LoanRequest.COMMITTEE_APPROVED)
        district = LoanApprovalLevelProgress.objects.get(
            loan_request=self.loan, level=self.district_level,
        )
        self.assertEqual(district.status, LoanApprovalLevelProgress.STATUS_SKIPPED)
        self.assertEqual(self.loan.disbursement_status, LoanRequest.DISBURSE_AWAITING_CONDITIONS)
