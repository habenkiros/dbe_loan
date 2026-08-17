"""Digital loan agreement signatures — disbursement gate."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from loans.agreement_signing import (
    agreement_blockers,
    generate_loan_agreement,
    record_signature,
)
from loans.disbursement import disbursement_readiness, start_disbursement_track
from loans.models import (
    AppraisalAmortizationEntry,
    Branch,
    CollateralType,
    District,
    LoanAgreement,
    LoanAgreementSignature,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
    LoanRequestBasicInfo,
)

User = get_user_model()

# Minimal valid 1×1 PNG
_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f'
    b'\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
)


def _data_url():
    import base64
    return 'data:image/png;base64,' + base64.b64encode(_PNG).decode('ascii')


class AgreementSigningGateTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Agr Dist')
        self.branch = Branch.objects.create(name='Agr Branch', district=district)
        collateral = CollateralType.objects.create(name='Building')
        category = LoanCategory.objects.create(name='Agr Cat')
        self.officer = User.objects.create_user(
            username='agr_lo', password='x', phone_number='0911999001', role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-AGR-1',
            applicant_name='Abebe Kebede',
            phone_number='0911999002',
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
            require_collateral_restriction=False,
            collateral_held_via_poa=False,
            require_agreement_signatures=True,
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
        self.factory = RequestFactory()

    def test_unsigned_blocks_readiness(self):
        blockers = agreement_blockers(self.loan)
        self.assertTrue(any('agreement' in b.lower() for b in blockers))
        readiness = disbursement_readiness(self.loan)
        self.assertFalse(readiness['ok'])
        self.assertTrue(any('agreement' in b.lower() for b in readiness['blockers']))

    def test_full_signatures_clear_gate(self):
        agr = generate_loan_agreement(self.loan, self.officer)
        self.assertEqual(agr.status, LoanAgreement.STATUS_PENDING)
        req = self.factory.post('/sign/')
        req.META['REMOTE_ADDR'] = '127.0.0.1'
        req.META['HTTP_USER_AGENT'] = 'test'

        record_signature(
            agr,
            role=LoanAgreementSignature.ROLE_BORROWER,
            signer_name='Abebe Kebede',
            typed_name='Abebe Kebede',
            signer_id_number='TIN-001122',
            declaration_accepted=True,
            data_url=_data_url(),
            request=req,
        )
        agr.refresh_from_db()
        self.assertEqual(agr.status, LoanAgreement.STATUS_PARTIAL)

        record_signature(
            agr,
            role=LoanAgreementSignature.ROLE_OFFICER,
            signer_name='Officer',
            typed_name='Officer',
            declaration_accepted=True,
            data_url=_data_url(),
            request=req,
            signer_user=self.officer,
        )
        agr.refresh_from_db()
        self.assertEqual(agr.status, LoanAgreement.STATUS_SIGNED)
        self.assertEqual(agreement_blockers(self.loan), [])
        readiness = disbursement_readiness(self.loan)
        self.assertFalse(any('agreement' in b.lower() for b in readiness['blockers']))

    def test_flag_off_skips_gate(self):
        self.loan.require_agreement_signatures = False
        self.loan.save(update_fields=['require_agreement_signatures'])
        self.assertEqual(agreement_blockers(self.loan), [])

    def test_declaration_and_id_required(self):
        agr = generate_loan_agreement(self.loan, self.officer)
        req = self.factory.post('/sign/')
        req.META['REMOTE_ADDR'] = '127.0.0.1'
        with self.assertRaises(ValueError):
            record_signature(
                agr,
                role=LoanAgreementSignature.ROLE_BORROWER,
                signer_name='Abebe Kebede',
                typed_name='Abebe Kebede',
                signer_id_number='TIN-1',
                declaration_accepted=False,
                data_url=_data_url(),
                request=req,
            )
        with self.assertRaises(ValueError):
            record_signature(
                agr,
                role=LoanAgreementSignature.ROLE_BORROWER,
                signer_name='Abebe Kebede',
                typed_name='Someone Else',
                signer_id_number='TIN-001122',
                declaration_accepted=True,
                data_url=_data_url(),
                request=req,
            )
        with self.assertRaises(ValueError):
            record_signature(
                agr,
                role=LoanAgreementSignature.ROLE_BORROWER,
                signer_name='Abebe Kebede',
                typed_name='Abebe Kebede',
                signer_id_number='',
                declaration_accepted=True,
                data_url=_data_url(),
                request=req,
            )

    def test_agreement_pdf_builds(self):
        from loans.agreement_pdf import build_agreement_pdf

        agr = generate_loan_agreement(self.loan, self.officer)
        pdf, engine = build_agreement_pdf(agr)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertIn(engine, ('weasyprint', 'reportlab'))
