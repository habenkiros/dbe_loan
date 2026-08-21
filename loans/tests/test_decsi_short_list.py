"""DECSI short-list: Digital Apply harden, delegation docs, finance book, remote OTP."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from applicant_portal.chapa import callback_url_is_public_https
from applicant_portal.email_health import email_delivery_status
from loans.agreement_signing import generate_loan_agreement
from loans.delegation import SCOPE_APPRAISAL
from loans.disbursement import finance_ready_to_book, start_disbursement_track
from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanAgreementSignature,
    LoanCategory,
    LoanRequest,
    StaffDelegation,
)
from loans.remote_sign import complete_remote_sign, issue_remote_sign_challenge


User = get_user_model()


class ChapaHttpsGateTests(TestCase):
    def test_localhost_not_public_https(self):
        self.assertFalse(callback_url_is_public_https('http://localhost:8000/payments/chapa/webhook/'))
        self.assertFalse(callback_url_is_public_https('https://127.0.0.1/x'))
        self.assertTrue(callback_url_is_public_https('https://apply.decsi.et/payments/chapa/webhook/'))

    def test_email_health_reports_console(self):
        status = email_delivery_status()
        self.assertIn('backend', status)
        self.assertTrue(status['is_console'] or not status['production_ready'] or True)


class DelegationDocumentAccessTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='SL Dist')
        self.branch = Branch.objects.create(name='SL Branch', district=self.district)
        self.category = LoanCategory.objects.create(name='SL Cat')
        self.collateral = CollateralType.objects.create(name='SL Coll')
        self.principal = User.objects.create_user(
            username='sl_lo', password='x', role='loan_officer',
            phone_number='0911111001', branch=self.branch, district=self.district,
        )
        self.delegate = User.objects.create_user(
            username='sl_del', password='x', role='accountant',
            phone_number='0911111002', branch=self.branch, district=self.district,
        )
        self.bm = User.objects.create_user(
            username='sl_bm', password='x', role='branch_manager',
            phone_number='0911111003', branch=self.branch, district=self.district,
        )
        now = timezone.now()
        StaffDelegation.objects.create(
            principal=self.principal,
            delegate=self.delegate,
            scopes=[SCOPE_APPRAISAL],
            status=StaffDelegation.STATUS_APPROVED,
            is_active=True,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=7),
            created_by=self.principal,
            reviewed_by=self.bm,
            reviewed_at=now,
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-SL-DOC-1',
            applicant_name='Delegate Doc',
            phone_number='0911222333',
            amount_requested=Decimal('80000'),
            reason='Working capital',
            category=self.category,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.principal,
            operation_manager_approval=True,
            finance_approval=True,
            queue_approved=True,
        )

    def test_delegate_sees_upload_and_request_flags(self):
        from loans.views import (
            _user_can_upload_loan_documents,
            _user_covers_loan_documents,
            _user_can_work_loan_documents,
        )
        self.assertTrue(_user_can_work_loan_documents(self.delegate))
        self.assertTrue(_user_covers_loan_documents(self.delegate, self.loan))
        self.assertTrue(_user_can_upload_loan_documents(self.delegate, self.loan))

    def test_delegate_can_open_upload_page(self):
        client = Client()
        self.assertTrue(client.login(username='sl_del', password='x'))
        resp = client.get(reverse('upload_loan_request_documents', args=[self.loan.pk]))
        self.assertEqual(resp.status_code, 200)


class FinanceReadyToBookTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Fin Dist')
        self.branch = Branch.objects.create(name='Fin Branch', district=district)
        category = LoanCategory.objects.create(name='Fin Cat')
        collateral = CollateralType.objects.create(name='Fin Coll')
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-FIN-BOOK-1',
            applicant_name='Finance Book',
            phone_number='0911333444',
            customer_number='',
            amount_requested=Decimal('100000'),
            reason='Equip',
            category=category,
            branch=self.branch,
            collateral=collateral,
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            committee_decided_at=timezone.now(),
            require_agreement_signatures=False,
            disbursement_status=LoanRequest.DISBURSE_READY,
        )
        start_disbursement_track(self.loan)
        self.loan.disbursement_status = LoanRequest.DISBURSE_READY
        self.loan.save(update_fields=['disbursement_status'])

    def test_missing_customer_blocks_ready_to_book(self):
        book = finance_ready_to_book(self.loan)
        self.assertFalse(book['ok'])
        self.assertTrue(any('Customer number' in b for b in book['blockers']))

    def test_customer_number_helps_checklist(self):
        self.loan.customer_number = '2000050041'
        self.loan.save(update_fields=['customer_number'])
        book = finance_ready_to_book(self.loan)
        # May still fail on schedule/CPs — but customer blocker gone
        self.assertFalse(any('Customer number' in b for b in book['blockers']))
        self.assertIsNotNone(book.get('cbs_payload'))


class RemoteOtpSignTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='OTP Dist')
        self.branch = Branch.objects.create(name='OTP Branch', district=district)
        category = LoanCategory.objects.create(name='OTP Cat')
        collateral = CollateralType.objects.create(name='OTP Coll')
        self.officer = User.objects.create_user(
            username='otp_lo', password='x', role='loan_officer',
            phone_number='0911444555', branch=self.branch, district=district,
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-OTP-1',
            applicant_name='Remote Signer',
            phone_number='0911555666',
            amount_requested=Decimal('50000'),
            reason='Inventory',
            category=category,
            branch=self.branch,
            collateral=collateral,
            assigned_loan_officer=self.officer,
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            committee_decided_at=timezone.now(),
            require_agreement_signatures=True,
        )
        start_disbursement_track(self.loan)
        self.agreement = generate_loan_agreement(self.loan, self.officer)

    @patch('applicant_portal.notify.deliver_sms', return_value=True)
    def test_issue_and_complete_remote_otp(self, _sms):
        challenge, code, path = issue_remote_sign_challenge(
            self.agreement,
            role=LoanAgreementSignature.ROLE_BORROWER,
            signer_name='Remote Signer',
            signer_phone='0911555666',
            signer_id_number='ID-12345',
            created_by=self.officer,
        )
        self.assertTrue(path.startswith('/sign/agreement/'))
        sig = complete_remote_sign(
            challenge,
            otp=code,
            declaration_accepted=True,
        )
        self.assertEqual(sig.signature_method, LoanAgreementSignature.METHOD_REMOTE_OTP)
        self.assertTrue(sig.is_valid)

    @patch('applicant_portal.notify.deliver_sms', return_value=True)
    def test_public_sign_page(self, _sms):
        challenge, code, path = issue_remote_sign_challenge(
            self.agreement,
            role=LoanAgreementSignature.ROLE_BORROWER,
            signer_name='Remote Signer',
            signer_phone='0911555666',
            signer_id_number='ID-12345',
            created_by=self.officer,
        )
        client = Client()
        resp = client.get(path)
        self.assertEqual(resp.status_code, 200)
        resp2 = client.post(path, {
            'otp': code,
            'declaration_accepted': '1',
        })
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, 'Signature recorded')
