"""Committee P3: louder tiebreaker state, SLA digest, mobile vote CSS."""

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from loans.ci_alerts import send_committee_sla_digest
from loans.committee import get_level_tally, resolve_level_vote_decision, start_approval_workflow
from loans.models import (
    ApprovalCommitteeLevel,
    ApprovalCommitteeMemberRule,
    Branch,
    CollateralType,
    District,
    LoanCategory,
    LoanCommitteeVote,
    LoanNotification,
    LoanRequest,
)


User = get_user_model()


@override_settings(CI_COMMITTEE_SLA_DAYS=5, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class CommitteeP3Tests(TestCase):
    def setUp(self):
        ApprovalCommitteeLevel.objects.filter(is_active=True).update(is_active=False)
        self.district = District.objects.create(name='P3 Dist')
        self.branch = Branch.objects.create(name='P3 Branch', district=self.district)
        self.category = LoanCategory.objects.create(name='P3 Cat')
        self.collateral = CollateralType.objects.create(name='P3 Coll', kind='building')
        self.bm = User.objects.create_user(
            username='p3_bm', password='Demo@12345',
            role='branch_manager', phone_number='0911555401',
            branch=self.branch, district=self.district,
            email='p3bm@example.com',
        )
        self.lo = User.objects.create_user(
            username='p3_lo', password='Demo@12345',
            role='loan_officer', phone_number='0911555402',
            branch=self.branch, district=self.district,
            email='p3lo@example.com',
        )
        self.acct = User.objects.create_user(
            username='p3_acct', password='Demo@12345',
            role='accountant', phone_number='0911555403',
            branch=self.branch, district=self.district,
            email='p3acct@example.com',
        )
        self.level = ApprovalCommitteeLevel.objects.create(
            key='p3_branch',
            name='P3 Branch',
            voter_scope=ApprovalCommitteeLevel.SCOPE_BRANCH,
            sequence_order=1,
            is_active=True,
            min_approvals_required=1,
            min_declines_required=1,
            max_loan_amount=Decimal('500000'),
            tiebreaker_role='branch_manager',
        )
        for role in ('branch_manager', 'loan_officer', 'accountant'):
            ApprovalCommitteeMemberRule.objects.create(
                level=self.level,
                participant_type=ApprovalCommitteeMemberRule.PARTICIPANT_ROLE,
                role=role,
                is_active=True,
            )
        self.loan = LoanRequest.objects.create(
            loan_request_id='DCSI-P3-1',
            applicant_name='P3 Applicant',
            phone_number='0911555444',
            amount_requested=Decimal('200000'),
            reason='p3 test',
            category=self.category,
            collateral=self.collateral,
            branch=self.branch,
            district=self.district,
            status='Approved',
            queue_approved=True,
            operation_manager_approval=True,
            committee_status=LoanRequest.COMMITTEE_PENDING,
            current_approval_level=self.level,
            assigned_loan_officer=self.lo,
            submitted_to_committee_at=timezone.now() - timedelta(days=8),
        )
        start_approval_workflow(self.loan)
        self.loan.refresh_from_db()
        LoanRequest.objects.filter(pk=self.loan.pk).update(
            submitted_to_committee_at=timezone.now() - timedelta(days=8),
            committee_status=LoanRequest.COMMITTEE_PENDING,
        )
        self.loan.refresh_from_db()

    def test_tally_exposes_tiebreaker_waiting(self):
        LoanCommitteeVote.objects.create(
            loan_request=self.loan, approval_level=self.level,
            member=self.acct, vote=LoanCommitteeVote.VOTE_APPROVE,
        )
        LoanCommitteeVote.objects.create(
            loan_request=self.loan, approval_level=self.level,
            member=self.lo, vote=LoanCommitteeVote.VOTE_DECLINE,
        )
        tally = get_level_tally(self.loan, self.level)
        self.assertTrue(tally['is_tied'])
        self.assertTrue(tally['tiebreaker_waiting'])
        self.assertIsNone(tally['decision'])
        self.assertIn('waiting', (tally['decision_reason'] or '').lower())

    def test_manager_page_shows_tie_banner(self):
        LoanCommitteeVote.objects.create(
            loan_request=self.loan, approval_level=self.level,
            member=self.acct, vote=LoanCommitteeVote.VOTE_APPROVE,
        )
        LoanCommitteeVote.objects.create(
            loan_request=self.loan, approval_level=self.level,
            member=self.lo, vote=LoanCommitteeVote.VOTE_DECLINE,
        )
        client = Client()
        client.force_login(self.bm)
        resp = client.get(reverse('loan_request_detail_manager', args=[self.loan.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Tied — waiting for chair')
        self.assertContains(resp, 'tie-waiting-banner')
        self.assertContains(resp, 'max-width: 720px')  # mobile CSS present

    def test_sla_digest_notifies_and_dedupes(self):
        result = send_committee_sla_digest(dry_run=False, dedupe_hours=24)
        self.assertGreaterEqual(result['notified_loans'], 1)
        self.assertGreaterEqual(result['notifications'], 1)
        self.assertTrue(
            LoanNotification.objects.filter(
                loan_request=self.loan,
                kind=LoanNotification.KIND_COMMITTEE_SLA,
            ).exists()
        )
        again = send_committee_sla_digest(dry_run=False, dedupe_hours=24)
        self.assertGreaterEqual(again['skipped'], 1)

    def test_sla_digest_command_dry_run(self):
        out = StringIO()
        call_command('send_committee_sla_digest', '--dry-run', stdout=out)
        self.assertIn('DRY-RUN', out.getvalue())
        self.assertFalse(
            LoanNotification.objects.filter(kind=LoanNotification.KIND_COMMITTEE_SLA).exists()
        )
