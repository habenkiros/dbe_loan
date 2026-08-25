"""Legal Administration desk — clearance gate before disbursement."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from loans.collateral_legal import verify_legal_document
from loans.disbursement import disbursement_readiness, start_disbursement_track
from loans.legal_desk import clear_for_disbursement, return_to_branch
from loans.models import (
    AppraisalAmortizationEntry,
    Branch,
    CollateralType,
    District,
    LoanAppraisal,
    LoanCategory,
    LoanCollateralLegalDocument,
    LoanProcessPolicyConfig,
    LoanRequest,
    LoanRequestBasicInfo,
)
from loans.process_policy import get_or_create_process_policy

User = get_user_model()


class LegalDeskTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Legal Desk Dist')
        self.branch = Branch.objects.create(name='Legal Desk Branch', district=district)
        collateral = CollateralType.objects.create(name='Building')
        category = LoanCategory.objects.create(name='Legal Desk Cat')
        self.officer = User.objects.create_user(
            username='legal_desk_lo', password='pass', phone_number='0911888101',
            role='loan_officer',
        )
        self.legal = User.objects.create_user(
            username='legal.officer', password='pass', phone_number='0911888102',
            role='legal_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-LEGAL-DESK-1',
            applicant_name='Tigist Haile',
            phone_number='0911888103',
            amount_requested=Decimal('90000'),
            reason='WC',
            category=category,
            branch=self.branch,
            collateral=collateral,
            queue_approved=True,
            assigned_loan_officer=self.officer,
            appraisal_completed_at=timezone.now(),
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            committee_final_decision='approve',
            committee_final_amount=Decimal('85000'),
            committee_decided_at=timezone.now(),
            require_collateral_restriction=True,
            collateral_held_via_poa=False,
            require_agreement_signatures=False,
        )
        appraisal = LoanAppraisal.objects.create(
            loan_request=self.loan,
            created_by=self.officer,
            recommendation='approve',
            amount_approved=Decimal('85000'),
            term_approved_months=12,
            rate_approved=Decimal('14'),
        )
        LoanRequestBasicInfo.objects.create(
            loan_request=self.loan, term_months=12, interest_rate=Decimal('14'),
        )
        start_disbursement_track(self.loan)
        AppraisalAmortizationEntry.objects.create(
            appraisal=appraisal,
            period_number=1,
            payment_amount=Decimal('85000'),
            principal=Decimal('85000'),
            interest=Decimal('0'),
            balance_after=Decimal('0'),
        )
        self.loan.schedule_confirmed_at = timezone.now()
        self.loan.schedule_confirmed_by = self.officer
        self.loan.disbursement_status = LoanRequest.DISBURSE_SCHEDULE_CONFIRMED
        self.loan.save()
        policy = get_or_create_process_policy()
        if not policy.require_legal_clearance:
            policy.require_legal_clearance = True
            policy.save(update_fields=['require_legal_clearance'])

    def _verify_restriction(self):
        pdf = SimpleUploadedFile('restriction.pdf', b'%PDF-1.4 fake', content_type='application/pdf')
        doc = LoanCollateralLegalDocument.objects.create(
            loan_request=self.loan,
            kind=LoanCollateralLegalDocument.KIND_RESTRICTION,
            reference_number='LR-DESK-1',
            issuing_office='Land Admin',
            file=pdf,
            uploaded_by=self.officer,
            status=LoanCollateralLegalDocument.STATUS_UPLOADED,
        )
        verify_legal_document(doc, self.legal, approve=True)

    def test_home_redirects_legal_officer_to_desk(self):
        client = Client()
        client.login(username='legal.officer', password='pass')
        resp = client.get(reverse('home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('legal_desk'), resp.url)

    def test_readiness_blocks_until_legal_clears(self):
        self._verify_restriction()
        readiness = disbursement_readiness(self.loan)
        self.assertFalse(readiness['ok'])
        self.assertTrue(any('Legal Administration' in b for b in readiness['blockers']))

        clear_for_disbursement(self.loan, self.legal, note='Papers in order')
        self.loan.refresh_from_db()
        self.assertIsNotNone(self.loan.legal_cleared_at)
        readiness2 = disbursement_readiness(self.loan)
        self.assertFalse(any('Legal Administration' in b for b in readiness2['blockers']))

    def test_cannot_clear_with_paper_blockers(self):
        with self.assertRaises(ValueError):
            clear_for_disbursement(self.loan, self.legal)

    def test_return_clears_stamp(self):
        self._verify_restriction()
        clear_for_disbursement(self.loan, self.legal)
        return_to_branch(self.loan, self.legal, note='Missing stamp duty receipt')
        self.loan.refresh_from_db()
        self.assertIsNone(self.loan.legal_cleared_at)
        self.assertIn('stamp duty', self.loan.legal_clearance_note.lower())

    def test_legal_action_via_post(self):
        self._verify_restriction()
        client = Client()
        client.login(username='legal.officer', password='pass')
        resp = client.post(reverse('legal_loan_action', args=[self.loan.pk]), {
            'action': 'clear',
            'note': 'Cleared after review',
        })
        self.assertEqual(resp.status_code, 302)
        self.loan.refresh_from_db()
        self.assertIsNotNone(self.loan.legal_cleared_at)

    def test_policy_off_skips_clearance_gate(self):
        self._verify_restriction()
        policy = LoanProcessPolicyConfig.objects.first()
        policy.require_legal_clearance = False
        policy.save(update_fields=['require_legal_clearance'])
        readiness = disbursement_readiness(self.loan)
        self.assertFalse(any('Legal Administration' in b for b in readiness['blockers']))
