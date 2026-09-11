"""Committee P0: step-up re-auth + append-only vote events."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from loans.committee import get_levels_for_loan, record_committee_vote
from loans.models import (
    ApprovalCommitteeLevel,
    ApprovalCommitteeMemberRule,
    Branch,
    CollateralType,
    District,
    LoanCategory,
    LoanCommitteeVote,
    LoanCommitteeVoteEvent,
    LoanRequest,
    SecurityAuditLog,
)
from loans.security import verify_committee_stepup


User = get_user_model()


@override_settings(COMMITTEE_STEPUP_REQUIRED=True, MFA_REQUIRED=False)
class CommitteeStepupAndAuditTests(TestCase):
    def setUp(self):
        # Migrations seed branch/district/HO/management; deactivate so reconcile
        # does not re-route this loan off our isolated test level.
        ApprovalCommitteeLevel.objects.filter(is_active=True).update(is_active=False)
        self.district = District.objects.create(name='Step Dist')
        self.branch = Branch.objects.create(name='Step Branch', district=self.district)
        self.category = LoanCategory.objects.create(name='Step Cat')
        self.collateral = CollateralType.objects.create(name='Step Coll', kind='building')
        self.bm = User.objects.create_user(
            username='step_bm', password='Demo@12345',
            role='branch_manager', phone_number='0911555001',
            branch=self.branch, district=self.district,
        )
        self.level = ApprovalCommitteeLevel.objects.create(
            key='step_branch',
            name='Step Branch Committee',
            voter_scope=ApprovalCommitteeLevel.SCOPE_BRANCH,
            sequence_order=1,
            is_active=True,
            min_approvals_required=2,
            min_declines_required=2,
            max_loan_amount=Decimal('500000'),
        )
        ApprovalCommitteeMemberRule.objects.create(
            level=self.level,
            participant_type=ApprovalCommitteeMemberRule.PARTICIPANT_ROLE,
            role='branch_manager',
            is_active=True,
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='DCSI-STEP-1',
            applicant_name='Step Applicant',
            phone_number='0911555111',
            amount_requested=Decimal('450000'),
            reason='step-up test',
            category=self.category,
            collateral=self.collateral,
            branch=self.branch,
            district=self.district,
            status='Approved',
            queue_approved=True,
            operation_manager_approval=True,
            committee_status=LoanRequest.COMMITTEE_PENDING,
            current_approval_level=self.level,
        )
        self.client = Client()
        self.client.force_login(self.bm)

    def test_verify_stepup_password(self):
        ok, err = verify_committee_stepup(self.bm, password='wrong', mfa_code='')
        self.assertFalse(ok)
        ok2, _ = verify_committee_stepup(self.bm, password='Demo@12345', mfa_code='')
        self.assertTrue(ok2)

    def test_vote_requires_password(self):
        url = reverse('cast_committee_vote', args=[self.loan.id])
        resp = self.client.post(url, {
            'vote': 'approve',
            'comments': '',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(LoanCommitteeVote.objects.filter(loan_request=self.loan).exists())
        self.assertTrue(
            SecurityAuditLog.objects.filter(
                event_type=SecurityAuditLog.EVT_COMMITTEE_STEPUP_FAILED,
            ).exists()
        )

    def test_vote_with_password_appends_event(self):
        url = reverse('cast_committee_vote', args=[self.loan.id])
        # Pend first (editable), then change to approve — append-only events.
        resp = self.client.post(url, {
            'vote': 'pend',
            'comments': 'Need more bank statements',
            'confirm_password': 'Demo@12345',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(LoanCommitteeVote.objects.filter(loan_request=self.loan).count(), 1)
        self.assertEqual(LoanCommitteeVoteEvent.objects.filter(loan_request=self.loan).count(), 1)
        self.client.post(url, {
            'vote': 'approve',
            'amount_supported': '450000',
            'comments': 'ok',
            'confirm_password': 'Demo@12345',
        })
        self.assertEqual(LoanCommitteeVote.objects.filter(loan_request=self.loan).count(), 1)
        self.assertEqual(LoanCommitteeVoteEvent.objects.filter(loan_request=self.loan).count(), 2)
        event = LoanCommitteeVoteEvent.objects.filter(loan_request=self.loan).order_by('id').last()
        self.assertEqual(event.previous_vote, 'pend')
        self.assertEqual(event.vote, 'approve')
        self.assertTrue(
            SecurityAuditLog.objects.filter(event_type=SecurityAuditLog.EVT_COMMITTEE_VOTE).exists()
        )

    def test_record_helper_preserves_history(self):
        record_committee_vote(
            loan_request=self.loan,
            level=self.level,
            member=self.bm,
            vote='approve',
            amount_supported=Decimal('450000'),
            comments='first',
        )
        record_committee_vote(
            loan_request=self.loan,
            level=self.level,
            member=self.bm,
            vote='decline',
            comments='changed mind',
        )
        self.assertEqual(LoanCommitteeVote.objects.get(loan_request=self.loan).vote, 'decline')
        self.assertEqual(LoanCommitteeVoteEvent.objects.filter(loan_request=self.loan).count(), 2)

    def test_seed_amount_routes_to_branch(self):
        """CN 1009-style amount (450k) must hit branch band when configured like seed."""
        branch, _ = ApprovalCommitteeLevel.objects.update_or_create(
            key='branch',
            defaults={
                'name': 'Branch Committee',
                'voter_scope': ApprovalCommitteeLevel.SCOPE_BRANCH,
                'sequence_order': 1,
                'is_active': True,
                'min_approvals_required': 2,
                'min_declines_required': 2,
                'min_loan_amount': None,
                'max_loan_amount': Decimal('500000'),
            },
        )
        ApprovalCommitteeLevel.objects.update_or_create(
            key='district',
            defaults={
                'name': 'District Committee',
                'voter_scope': ApprovalCommitteeLevel.SCOPE_DISTRICT,
                'sequence_order': 2,
                'is_active': True,
                'min_approvals_required': 2,
                'min_declines_required': 2,
                'min_loan_amount': Decimal('500000.01'),
                'max_loan_amount': Decimal('2000000'),
            },
        )
        # Isolate from other active levels (HO/management/step_branch).
        ApprovalCommitteeLevel.objects.exclude(key__in=('branch', 'district')).update(is_active=False)
        levels = get_levels_for_loan(self.loan)
        self.assertEqual([lv.key for lv in levels], ['branch'])
        self.assertEqual(levels[0].id, branch.id)
