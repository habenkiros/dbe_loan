"""Committee vote-screen evidence panel: docs + appraisal + collateral."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from collateral.views import _user_can_access_loan_collateral
from loans.committee import start_approval_workflow
from loans.committee_evidence import build_committee_vote_evidence
from loans.models import (
    ApprovalCommitteeLevel,
    ApprovalCommitteeMemberRule,
    Branch,
    CollateralType,
    District,
    LoanApplicationDocumentType,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
    LoanRequestDocument,
)

User = get_user_model()


class CommitteeEvidenceTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='EV District')
        self.branch = Branch.objects.create(name='EV Branch', district=self.district)
        self.category = LoanCategory.objects.create(name='EV Cat')
        self.collateral = CollateralType.objects.create(name='Building')
        self.doc_type = LoanApplicationDocumentType.objects.create(name='ID Card', order=1)

        self.level, _ = ApprovalCommitteeLevel.objects.update_or_create(
            key='branch',
            defaults={
                'name': 'Branch Committee',
                'voter_scope': ApprovalCommitteeLevel.SCOPE_BRANCH,
                'sequence_order': 1,
                'is_active': True,
                'min_approvals_required': 1,
                'min_declines_required': 1,
                'min_loan_amount': None,
                'max_loan_amount': None,
            },
        )
        ApprovalCommitteeMemberRule.objects.filter(level=self.level).delete()
        for role in ('branch_manager', 'accountant'):
            ApprovalCommitteeMemberRule.objects.create(
                level=self.level,
                participant_type=ApprovalCommitteeMemberRule.PARTICIPANT_ROLE,
                role=role,
                is_active=True,
            )
        ApprovalCommitteeLevel.objects.exclude(pk=self.level.pk).update(is_active=False)

        self.bm = User.objects.create_user(
            username='ev_bm', password='pass', phone_number='0911000201',
            role='branch_manager', branch=self.branch, district=self.district,
        )
        self.acct = User.objects.create_user(
            username='ev_acct', password='pass', phone_number='0911000202',
            role='accountant', branch=self.branch, district=self.district,
        )
        self.lo = User.objects.create_user(
            username='ev_lo', password='pass', phone_number='0911000203',
            role='loan_officer', branch=self.branch, district=self.district,
        )

        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-EV-1',
            applicant_name='Evidence Applicant',
            phone_number='0911222333',
            category=self.category,
            collateral=self.collateral,
            amount_requested=Decimal('250000'),
            reason='evidence panel test',
            branch=self.branch,
            district=self.district,
            operation_manager_approval=True,
            queue_approved=True,
            assigned_loan_officer=self.lo,
            committee_status=LoanRequest.COMMITTEE_PENDING,
        )
        start_approval_workflow(self.loan)
        self.loan.refresh_from_db()

        self.appraisal = LoanAppraisal.objects.create(
            loan_request=self.loan,
            recommendation=LoanAppraisal.RECOMMEND_APPROVE,
            amount_approved=Decimal('200000'),
            term_approved_months=24,
            rate_approved=Decimal('14.5'),
            strengths='Strong cash flow.',
            weaknesses='Thin equity.',
            created_by=self.lo,
        )
        LoanRequestDocument.objects.create(
            loan_request=self.loan,
            document_type=self.doc_type,
            file=SimpleUploadedFile('id.pdf', b'%PDF-1.4 fake', content_type='application/pdf'),
            uploaded_by=self.lo,
            auth_status=LoanRequestDocument.AUTH_VERIFIED,
        )

    def test_build_evidence_includes_docs_and_appraisal(self):
        evidence = build_committee_vote_evidence(self.loan)
        self.assertTrue(evidence['has_documents'])
        self.assertTrue(evidence['has_appraisal'])
        self.assertEqual(evidence['document_count'], 1)
        self.assertEqual(evidence['document_verified'], 1)
        self.assertEqual(evidence['appraisal'].amount_approved, Decimal('200000'))
        self.assertIn('Strong cash flow', evidence['strengths_short'])

    def test_vote_screen_shows_evidence_panel(self):
        client = Client()
        self.assertTrue(client.login(username='ev_bm', password='pass'))
        res = client.get(reverse('loan_request_detail_manager', args=[self.loan.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Evidence before you vote')
        self.assertContains(res, 'Application documents')
        self.assertContains(res, 'ID Card')
        self.assertContains(res, 'Appraisal snapshot')
        self.assertContains(res, 'Collateral estimation')
        self.assertContains(res, 'id="evidence"')

    def test_accountant_can_open_collateral_summary(self):
        self.assertTrue(_user_can_access_loan_collateral(self.acct, self.loan))
        client = Client()
        self.assertTrue(client.login(username='ev_acct', password='pass'))
        res = client.get(reverse('collateral:summary', args=[self.loan.pk]))
        self.assertEqual(res.status_code, 200, res.content[:400])

    def test_accountant_can_open_collateral_evidence_pack(self):
        client = Client()
        self.assertTrue(client.login(username='ev_acct', password='pass'))
        res = client.get(reverse('collateral:evidence_pack', args=[self.loan.pk]))
        self.assertEqual(res.status_code, 200, res.content[:400])
