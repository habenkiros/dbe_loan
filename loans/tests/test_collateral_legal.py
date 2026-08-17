"""Collateral Restriction + Power of Attorney — disbursement gate."""

from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from loans.collateral_legal import (
    collateral_legal_blockers,
    restriction_satisfied,
    verify_legal_document,
)
from loans.disbursement import disbursement_readiness, start_disbursement_track
from loans.models import (
    AppraisalAmortizationEntry,
    Branch,
    CollateralType,
    District,
    LoanAppraisal,
    LoanCategory,
    LoanCollateralLegalDocument,
    LoanRequest,
    LoanRequestBasicInfo,
)

User = get_user_model()


class CollateralLegalGateTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Legal Dist')
        self.branch = Branch.objects.create(name='Legal Branch', district=district)
        collateral = CollateralType.objects.create(name='Building')
        category = LoanCategory.objects.create(name='Legal Cat')
        self.officer = User.objects.create_user(
            username='legal_lo', password='x', phone_number='0911888001', role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-LEGAL-1',
            applicant_name='Abebe Kebede',
            phone_number='0911888002',
            amount_requested=Decimal('80000'),
            reason='Trade WC',
            category=category,
            branch=self.branch,
            collateral=collateral,
            queue_approved=True,
            assigned_loan_officer=self.officer,
            appraisal_completed_at=timezone.now(),
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            committee_final_decision='approve',
            committee_final_amount=Decimal('75000'),
            committee_decided_at=timezone.now(),
            require_collateral_restriction=True,
            collateral_held_via_poa=False,
            require_agreement_signatures=False,
        )
        self.appraisal = LoanAppraisal.objects.create(
            loan_request=self.loan,
            created_by=self.officer,
            recommendation='approve',
            amount_approved=Decimal('75000'),
            term_approved_months=12,
            rate_approved=Decimal('14'),
        )
        LoanRequestBasicInfo.objects.create(
            loan_request=self.loan, term_months=12, interest_rate=Decimal('14'),
        )
        start_disbursement_track(self.loan)
        # Minimal schedule so readiness focuses on legal docs, not amortisation
        AppraisalAmortizationEntry.objects.create(
            appraisal=self.appraisal,
            period_number=1,
            payment_amount=Decimal('75000'),
            principal=Decimal('75000'),
            interest=Decimal('0'),
            balance_after=Decimal('0'),
        )
        self.loan.schedule_confirmed_at = timezone.now()
        self.loan.schedule_confirmed_by = self.officer
        self.loan.disbursement_status = LoanRequest.DISBURSE_SCHEDULE_CONFIRMED
        self.loan.save()

    def test_restriction_blocks_readiness_until_verified(self):
        blockers = collateral_legal_blockers(self.loan)
        self.assertTrue(any('Restriction' in b for b in blockers))
        readiness = disbursement_readiness(self.loan)
        self.assertFalse(readiness['ok'])
        self.assertTrue(any('Restriction' in b for b in readiness['blockers']))

        pdf = SimpleUploadedFile('restriction.pdf', b'%PDF-1.4 fake', content_type='application/pdf')
        doc = LoanCollateralLegalDocument.objects.create(
            loan_request=self.loan,
            kind=LoanCollateralLegalDocument.KIND_RESTRICTION,
            reference_number='LR-MK-2026-441',
            issuing_office='Mekelle Land Administration',
            file=pdf,
            uploaded_by=self.officer,
            status=LoanCollateralLegalDocument.STATUS_UPLOADED,
        )
        self.assertFalse(restriction_satisfied(self.loan))

        verify_legal_document(doc, self.officer, approve=True)
        self.assertTrue(restriction_satisfied(self.loan))
        readiness2 = disbursement_readiness(self.loan)
        self.assertFalse(any('Restriction' in b for b in readiness2['blockers']))

    def test_poa_required_when_flag_set(self):
        self.loan.collateral_held_via_poa = True
        self.loan.require_collateral_restriction = False
        self.loan.save(update_fields=['collateral_held_via_poa', 'require_collateral_restriction'])
        blockers = collateral_legal_blockers(self.loan)
        self.assertTrue(any('Power of Attorney' in b for b in blockers))

        pdf = SimpleUploadedFile('poa.pdf', b'%PDF-1.4 poa', content_type='application/pdf')
        doc = LoanCollateralLegalDocument.objects.create(
            loan_request=self.loan,
            kind=LoanCollateralLegalDocument.KIND_POA,
            grantor_name='Tigist Hailu',
            attorney_name='Abebe Kebede',
            reference_number='POA-2026-12',
            issuing_office='Notary Public — Mekelle',
            file=pdf,
            uploaded_by=self.officer,
        )
        verify_legal_document(doc, self.officer, approve=True)
        self.assertEqual(collateral_legal_blockers(self.loan), [])

    def test_reject_requires_reason(self):
        pdf = SimpleUploadedFile('restriction.pdf', b'%PDF-1.4 fake', content_type='application/pdf')
        doc = LoanCollateralLegalDocument.objects.create(
            loan_request=self.loan,
            kind=LoanCollateralLegalDocument.KIND_RESTRICTION,
            reference_number='LR-1',
            issuing_office='Land Admin',
            file=pdf,
            uploaded_by=self.officer,
        )
        with self.assertRaises(ValueError):
            verify_legal_document(doc, self.officer, approve=False, note='')
        verify_legal_document(doc, self.officer, approve=False, note='Stamp unreadable on scan.')
        doc.refresh_from_db()
        self.assertEqual(doc.status, LoanCollateralLegalDocument.STATUS_REJECTED)
        self.assertIn('unreadable', doc.verification_note)

    def test_upload_validation(self):
        from loans.collateral_legal import validate_legal_upload
        from loans.models import LoanCollateralLegalDocument

        err = validate_legal_upload(LoanCollateralLegalDocument.KIND_RESTRICTION, {})
        self.assertIsNotNone(err)
        err = validate_legal_upload(LoanCollateralLegalDocument.KIND_POA, {
            'reference_number': 'POA-1',
            'grantor_name': 'Owner',
            'attorney_name': 'Borrower',
        })
        self.assertIsNone(err)
