"""Committee P2: routing mode, quorum, pend info-request, queue chips."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from loans.committee import (
    clear_committee_info_requests,
    get_level_tally,
    get_levels_for_loan,
    open_committee_info_request,
)
from loans.committee_brief import queue_chips_for_loan
from loans.models import (
    ApprovalCommitteeLevel,
    ApprovalCommitteeMemberRule,
    Branch,
    CollateralType,
    CommitteeInfoRequest,
    District,
    LoanAnalysisPolicyConfig,
    LoanAppraisal,
    LoanCategory,
    LoanNotification,
    LoanRequest,
)
from loans.process_policy import get_or_create_analysis_policy


User = get_user_model()


@override_settings(COMMITTEE_STEPUP_REQUIRED=False, MFA_REQUIRED=False, COMMITTEE_PEND_DUE_DAYS=5)
class CommitteeP2Tests(TestCase):
    def setUp(self):
        ApprovalCommitteeLevel.objects.filter(is_active=True).update(is_active=False)
        self.district = District.objects.create(name='P2 Dist')
        self.branch = Branch.objects.create(name='P2 Branch', district=self.district)
        self.category = LoanCategory.objects.create(name='P2 Cat')
        self.collateral = CollateralType.objects.create(name='P2 Coll', kind='building')
        self.bm = User.objects.create_user(
            username='p2_bm', password='Demo@12345',
            role='branch_manager', phone_number='0911555301',
            branch=self.branch, district=self.district,
        )
        self.lo = User.objects.create_user(
            username='p2_lo', password='Demo@12345',
            role='loan_officer', phone_number='0911555302',
            branch=self.branch, district=self.district,
        )
        self.branch_lvl = ApprovalCommitteeLevel.objects.create(
            key='p2_branch',
            name='P2 Branch',
            voter_scope=ApprovalCommitteeLevel.SCOPE_BRANCH,
            sequence_order=1,
            is_active=True,
            min_approvals_required=2,
            min_declines_required=2,
            max_loan_amount=Decimal('500000'),
        )
        self.district_lvl = ApprovalCommitteeLevel.objects.create(
            key='p2_district',
            name='P2 District',
            voter_scope=ApprovalCommitteeLevel.SCOPE_DISTRICT,
            sequence_order=2,
            is_active=True,
            min_approvals_required=2,
            min_declines_required=2,
            min_loan_amount=Decimal('500000.01'),
            max_loan_amount=Decimal('2000000'),
        )
        ApprovalCommitteeMemberRule.objects.create(
            level=self.branch_lvl,
            participant_type=ApprovalCommitteeMemberRule.PARTICIPANT_ROLE,
            role='branch_manager',
            is_active=True,
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='DCSI-P2-1',
            applicant_name='P2 Applicant',
            phone_number='0911555333',
            amount_requested=Decimal('1500000'),
            reason='p2 test',
            category=self.category,
            collateral=self.collateral,
            branch=self.branch,
            district=self.district,
            status='Approved',
            queue_approved=True,
            operation_manager_approval=True,
            committee_status=LoanRequest.COMMITTEE_PENDING,
            current_approval_level=self.branch_lvl,
            assigned_loan_officer=self.lo,
            submitted_to_committee_at=timezone.now() - timedelta(days=2),
        )
        LoanAppraisal.objects.create(
            loan_request=self.loan,
            amount_approved=Decimal('1500000'),
            recommendation='approve',
        )
        policy = get_or_create_analysis_policy()
        policy.committee_routing_mode = LoanAnalysisPolicyConfig.ROUTING_TIER
        policy.save(update_fields=['committee_routing_mode'])

    def test_tier_routing_exclusive_band(self):
        levels = get_levels_for_loan(self.loan)
        self.assertEqual([lv.key for lv in levels], ['p2_district'])

    def test_cumulative_routing_includes_lower_levels(self):
        policy = get_or_create_analysis_policy()
        policy.committee_routing_mode = LoanAnalysisPolicyConfig.ROUTING_CUMULATIVE
        policy.save(update_fields=['committee_routing_mode'])
        levels = get_levels_for_loan(self.loan)
        self.assertEqual([lv.key for lv in levels], ['p2_branch', 'p2_district'])

    def test_quorum_warning_when_eligible_below_min(self):
        # Only one eligible BM, min_approvals=2
        tally = get_level_tally(self.loan, self.branch_lvl)
        self.assertEqual(tally['eligible_count'], 1)
        self.assertFalse(tally['quorum_ok'])
        self.assertIn('eligible', tally['quorum_warning'].lower())

    def test_pend_opens_info_request_and_notifies_officer(self):
        info = open_committee_info_request(
            self.loan,
            level=self.branch_lvl,
            requested_by=self.bm,
            reason='Need updated bank statements please',
            due_date=date.today() + timedelta(days=5),
        )
        self.loan.refresh_from_db()
        self.assertEqual(info.status, CommitteeInfoRequest.STATUS_OPEN)
        self.assertEqual(self.loan.committee_status, LoanRequest.COMMITTEE_PENDED)
        self.assertTrue(
            LoanNotification.objects.filter(
                user=self.lo,
                kind=LoanNotification.KIND_COMMITTEE_INFO_REQUESTED,
            ).exists()
        )

    def test_clear_info_request_reopens_pending(self):
        open_committee_info_request(
            self.loan,
            level=self.branch_lvl,
            requested_by=self.bm,
            reason='Need updated bank statements please',
        )
        cleared = clear_committee_info_requests(
            self.loan, cleared_by=self.lo, notes='Uploaded Q2 bank statements.',
        )
        self.assertEqual(cleared, 1)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.committee_status, LoanRequest.COMMITTEE_PENDING)
        self.assertFalse(
            CommitteeInfoRequest.objects.filter(
                loan_request=self.loan, status=CommitteeInfoRequest.STATUS_OPEN,
            ).exists()
        )
        self.assertTrue(
            LoanNotification.objects.filter(
                kind=LoanNotification.KIND_COMMITTEE_INFO_CLEARED,
            ).exists()
        )

    def test_queue_chips_include_sla(self):
        meta = queue_chips_for_loan(self.loan)
        self.assertIn('sla', meta)
        self.assertIsNotNone(meta['sla'].get('days'))
        self.assertTrue(isinstance(meta['chips'], list))

    def test_clear_info_endpoint(self):
        open_committee_info_request(
            self.loan,
            level=self.branch_lvl,
            requested_by=self.bm,
            reason='Need tax clearance copy now',
        )
        client = Client()
        client.force_login(self.lo)
        url = reverse('clear_committee_info_request', args=[self.loan.id])
        resp = client.post(url, {'clear_notes': 'Uploaded tax clearance PDF.'})
        self.assertEqual(resp.status_code, 302)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.committee_status, LoanRequest.COMMITTEE_PENDING)

    def test_set_routing_mode_settings(self):
        admin = User.objects.create_superuser(
            username='p2_admin', password='Demo@12345', email='p2@example.com',
        )
        client = Client()
        client.force_login(admin)
        url = reverse('manage_approval_committees')
        resp = client.post(url, {
            'action': 'set_routing_mode',
            'committee_routing_mode': 'cumulative',
        })
        self.assertEqual(resp.status_code, 302)
        policy = get_or_create_analysis_policy()
        self.assertEqual(policy.committee_routing_mode, 'cumulative')
