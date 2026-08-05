"""Committee tie-breaker: equal approve/decline → chair role decides by level."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from loans.committee import (
    resolve_level_vote_decision,
    start_approval_workflow,
    try_finalize_level_decision,
)
from loans.models import (
    ApprovalCommitteeLevel,
    ApprovalCommitteeMemberRule,
    Branch,
    CollateralType,
    District,
    LoanCategory,
    LoanCommitteeVote,
    LoanRequest,
)

User = get_user_model()


class CommitteeTiebreakerTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='TB District')
        self.branch = Branch.objects.create(name='TB Branch', district=self.district)
        self.category = LoanCategory.objects.create(name='TB Cat')
        self.collateral = CollateralType.objects.create(name='TB Coll')

        self.level, _ = ApprovalCommitteeLevel.objects.update_or_create(
            key='branch',
            defaults={
                'name': 'Branch Committee',
                'voter_scope': ApprovalCommitteeLevel.SCOPE_BRANCH,
                'sequence_order': 1,
                'is_active': True,
                'min_approvals_required': 2,
                'min_declines_required': 2,
                'tiebreaker_role': 'branch_manager',
                'min_loan_amount': None,
                'max_loan_amount': None,
            },
        )
        ApprovalCommitteeMemberRule.objects.filter(level=self.level).delete()
        for role in ('branch_manager', 'accountant', 'loan_officer'):
            ApprovalCommitteeMemberRule.objects.create(
                level=self.level,
                participant_type=ApprovalCommitteeMemberRule.PARTICIPANT_ROLE,
                role=role,
                is_active=True,
            )
        # Isolate this loan to branch-only chain
        ApprovalCommitteeLevel.objects.exclude(pk=self.level.pk).update(is_active=False)

        self.bm = User.objects.create_user(
            username='tb_bm', password='pass', phone_number='0911000101',
            role='branch_manager', branch=self.branch, district=self.district,
        )
        self.acct = User.objects.create_user(
            username='tb_acct', password='pass', phone_number='0911000102',
            role='accountant', branch=self.branch, district=self.district,
        )
        self.lo = User.objects.create_user(
            username='tb_lo', password='pass', phone_number='0911000103',
            role='loan_officer', branch=self.branch, district=self.district,
        )

        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-TB-1',
            applicant_name='Tie Applicant',
            phone_number='0911222000',
            category=self.category,
            collateral=self.collateral,
            amount_requested=Decimal('100000'),
            reason='tie test',
            branch=self.branch,
            district=self.district,
            operation_manager_approval=True,
            assigned_loan_officer=self.lo,
            committee_status=LoanRequest.COMMITTEE_PENDING,
        )
        start_approval_workflow(self.loan)
        self.loan.refresh_from_db()

    def _vote(self, user, vote):
        LoanCommitteeVote.objects.create(
            loan_request=self.loan,
            approval_level=self.level,
            member=user,
            vote=vote,
        )

    def test_tie_broken_by_branch_manager_approve(self):
        self._vote(self.acct, LoanCommitteeVote.VOTE_APPROVE)
        self._vote(self.lo, LoanCommitteeVote.VOTE_DECLINE)
        # 1–1 not enough for thresholds yet; add BM approve → still 2–1 not tie
        # Force 2–2: BM approve, then need another decline — use two pairs
        LoanCommitteeVote.objects.all().delete()
        # Reset and use min 1 so 1–1 is both thresholds
        self.level.min_approvals_required = 1
        self.level.min_declines_required = 1
        self.level.save(update_fields=['min_approvals_required', 'min_declines_required'])

        self._vote(self.acct, LoanCommitteeVote.VOTE_DECLINE)
        self._vote(self.bm, LoanCommitteeVote.VOTE_APPROVE)

        from loans.committee import get_level_tally
        tally = get_level_tally(self.loan, self.level)
        decision, reason = resolve_level_vote_decision(self.loan, self.level, tally)
        self.assertEqual(decision, 'approve')
        self.assertIn('Tie', reason)

        self.assertTrue(try_finalize_level_decision(self.loan, self.level))
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.committee_status, LoanRequest.COMMITTEE_APPROVED)

    def test_tie_broken_by_branch_manager_decline(self):
        self.level.min_approvals_required = 1
        self.level.min_declines_required = 1
        self.level.save(update_fields=['min_approvals_required', 'min_declines_required'])

        self._vote(self.acct, LoanCommitteeVote.VOTE_APPROVE)
        self._vote(self.bm, LoanCommitteeVote.VOTE_DECLINE)

        from loans.committee import get_level_tally
        tally = get_level_tally(self.loan, self.level)
        decision, _ = resolve_level_vote_decision(self.loan, self.level, tally)
        self.assertEqual(decision, 'decline')

    def test_tie_waits_without_chair_vote(self):
        self.level.min_approvals_required = 1
        self.level.min_declines_required = 1
        self.level.save(update_fields=['min_approvals_required', 'min_declines_required'])

        self._vote(self.acct, LoanCommitteeVote.VOTE_APPROVE)
        self._vote(self.lo, LoanCommitteeVote.VOTE_DECLINE)

        from loans.committee import get_level_tally
        tally = get_level_tally(self.loan, self.level)
        decision, reason = resolve_level_vote_decision(self.loan, self.level, tally)
        self.assertIsNone(decision)
        self.assertIn('waiting', reason.lower())
        self.assertFalse(try_finalize_level_decision(self.loan, self.level))

    def test_management_prefers_board_over_ceo(self):
        mgmt = ApprovalCommitteeLevel.objects.filter(key='management').first()
        if mgmt is None:
            mgmt = ApprovalCommitteeLevel(
                key='management',
                name='Management',
                voter_scope=ApprovalCommitteeLevel.SCOPE_ORGANIZATION,
                sequence_order=4,
            )
        mgmt.name = 'Management'
        mgmt.voter_scope = ApprovalCommitteeLevel.SCOPE_ORGANIZATION
        mgmt.is_active = True
        mgmt.min_approvals_required = 1
        mgmt.min_declines_required = 1
        mgmt.tiebreaker_role = ''  # default board then ceo
        mgmt.save()
        ceo = User.objects.create_user(
            username='tb_ceo', password='pass', phone_number='0911000104', role='ceo',
        )
        board = User.objects.create_user(
            username='tb_board', password='pass', phone_number='0911000105', role='board_member',
        )
        loan = LoanRequest.objects.create(
            loan_request_id='LR-TB-M',
            applicant_name='Mgmt Tie',
            phone_number='0911222001',
            category=self.category,
            collateral=self.collateral,
            amount_requested=Decimal('20000000'),
            reason='mgmt tie',
            branch=self.branch,
            district=self.district,
            operation_manager_approval=True,
            committee_status=LoanRequest.COMMITTEE_PENDING,
            current_approval_level=mgmt,
        )
        LoanCommitteeVote.objects.create(
            loan_request=loan, approval_level=mgmt, member=ceo,
            vote=LoanCommitteeVote.VOTE_APPROVE,
        )
        LoanCommitteeVote.objects.create(
            loan_request=loan, approval_level=mgmt, member=board,
            vote=LoanCommitteeVote.VOTE_DECLINE,
        )
        from loans.committee import get_level_tally
        tally = get_level_tally(loan, mgmt)
        # 1–1 tie; board has priority over CEO
        decision, reason = resolve_level_vote_decision(loan, mgmt, tally)
        self.assertEqual(decision, 'decline')
        self.assertIn('Board', reason)
