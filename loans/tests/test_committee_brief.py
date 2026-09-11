"""Committee P1: voter-desk AI brief + draft comments + agent tool."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from loans.agent_tools import TOOL_SPECS, dispatch_tool
from loans.committee_brief import brief_for_agent, build_committee_brief, draft_vote_comments
from loans.models import (
    ApprovalCommitteeLevel,
    ApprovalCommitteeMemberRule,
    Branch,
    CollateralType,
    District,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
)


User = get_user_model()


@override_settings(COMMITTEE_STEPUP_REQUIRED=False, MFA_REQUIRED=False, OPENAI_API_KEY='')
class CommitteeBriefTests(TestCase):
    def setUp(self):
        ApprovalCommitteeLevel.objects.filter(is_active=True).update(is_active=False)
        self.district = District.objects.create(name='Brief Dist')
        self.branch = Branch.objects.create(name='Brief Branch', district=self.district)
        self.category = LoanCategory.objects.create(name='Brief Cat')
        self.collateral = CollateralType.objects.create(name='Brief Coll', kind='building')
        self.bm = User.objects.create_user(
            username='brief_bm', password='Demo@12345',
            role='branch_manager', phone_number='0911555201',
            branch=self.branch, district=self.district,
        )
        self.level = ApprovalCommitteeLevel.objects.create(
            key='brief_branch',
            name='Brief Branch Committee',
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
            loan_request_id='DCSI-BRIEF-1',
            applicant_name='Brief Applicant',
            phone_number='0911555222',
            amount_requested=Decimal('450000'),
            reason='committee brief test',
            category=self.category,
            collateral=self.collateral,
            branch=self.branch,
            district=self.district,
            status='Approved',
            queue_approved=True,
            operation_manager_approval=True,
            committee_status=LoanRequest.COMMITTEE_PENDING,
            current_approval_level=self.level,
            submitted_to_committee_at=timezone.now() - timedelta(days=1),
        )
        self.appraisal = LoanAppraisal.objects.create(
            loan_request=self.loan,
            amount_approved=Decimal('450000'),
            recommendation='approve',
            strengths='Stable cashflow and strong local demand.',
            weaknesses='Seasonal inventory risk.',
        )
        self.client = Client()
        self.client.force_login(self.bm)

    def test_build_committee_brief_has_chips_and_sla(self):
        brief = build_committee_brief(self.loan, user=self.bm)
        self.assertEqual(brief['loan_request_id'], 'DCSI-BRIEF-1')
        self.assertEqual(brief['current_level']['key'], 'brief_branch')
        self.assertTrue(brief['chips'])
        self.assertIsNotNone(brief['sla'].get('days'))
        self.assertIn('Assistive only', brief['disclaimer'])

    def test_rule_draft_comments_without_llm(self):
        out = draft_vote_comments(self.loan, vote_intent='approve', use_llm=False)
        self.assertTrue(out['ok'])
        self.assertEqual(out['source'], 'rules')
        self.assertIn('support approval', out['comments'].lower())

    def test_manager_page_includes_ai_brief(self):
        url = reverse('loan_request_detail_manager', args=[self.loan.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="ai-brief"')
        self.assertContains(resp, 'Suggest comments')
        self.assertContains(resp, 'committee-chip')

    def test_draft_endpoint_fills_comments(self):
        url = reverse('draft_committee_vote_comments', args=[self.loan.id])
        resp = self.client.post(url, {'vote': 'decline', 'use_llm': '0'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['source'], 'rules')
        self.assertIn('decline', data['comments'].lower())

    def test_committee_brief_tool_registered_and_read_only(self):
        names = [t['function']['name'] for t in TOOL_SPECS]
        self.assertIn('committee_brief', names)
        out = dispatch_tool(
            self.bm,
            'committee_brief',
            {'loan_id': self.loan.pk},
            conversation=None,
        )
        self.assertTrue(out.get('ok'))
        self.assertIn('READ ONLY', out.get('guidance', ''))
        self.assertEqual(out.get('loan_request_id'), 'DCSI-BRIEF-1')
        self.assertNotIn('cast_vote', out)
        # Forbidden vote tool still blocked
        blocked = dispatch_tool(self.bm, 'committee_vote', {'loan_id': self.loan.pk})
        self.assertFalse(blocked.get('ok'))

    def test_brief_for_agent_omits_heavy_cards(self):
        slim = brief_for_agent(self.loan, user=self.bm)
        self.assertNotIn('decision_card', slim)
        self.assertNotIn('desk_intel', slim)
        self.assertIn('links', slim)
