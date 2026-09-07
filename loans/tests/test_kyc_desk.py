"""Scan/Admin + parallel CRM / Engineering / Legal KYC packs."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from loans.kyc_desk import (
    KycClearBlocked,
    complete_checklist_payload,
    ensure_intake_screenings,
    kyc_applies,
    kyc_is_complete,
    set_screening_status,
)
from loans.models import (
    Branch,
    CollateralType,
    CreditDeskScreening,
    District,
    LoanCategory,
    LoanRequest,
)
from loans.product_family import FAMILY_GENERAL, FAMILY_PROJECT


User = get_user_model()


class KycDeskTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='Kyc Dist')
        self.branch = Branch.objects.create(name='Kyc Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='Kyc Coll')
        self.officer = User.objects.create_user(
            username='kyc_clo', password='pass', phone_number='0911999001',
            role='credit_loan_officer',
        )
        self.engineer = User.objects.create_user(
            username='kyc_eng', password='pass', phone_number='0911999002',
            role='engineer',
        )
        self.project_cat = LoanCategory.objects.create(
            name='Kyc Project', product_family=FAMILY_PROJECT,
        )
        self.general_cat = LoanCategory.objects.create(
            name='Kyc MSME', product_family=FAMILY_GENERAL, appraisal_mode='msme',
        )

    def _loan(self, category, rid, **kwargs):
        defaults = dict(
            loan_request_id=rid,
            applicant_name='Kyc Co',
            phone_number='0911000222',
            amount_requested=Decimal('1000000'),
            reason='plant',
            category=category,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
        )
        defaults.update(kwargs)
        return LoanRequest.objects.create(**defaults)

    def test_decsi_general_skips_kyc_packs(self):
        loan = self._loan(self.general_cat, 'LR-KYC-G')
        self.assertFalse(kyc_applies(loan))
        self.assertEqual(ensure_intake_screenings(loan), [])
        self.assertTrue(kyc_is_complete(loan))

    def test_staff_project_opens_three_parallel_packs(self):
        loan = self._loan(self.project_cat, 'LR-KYC-P')
        rows = ensure_intake_screenings(loan)
        desks = {r.desk for r in rows}
        self.assertEqual(desks, {'crm', 'engineering', 'legal'})
        self.assertFalse(kyc_is_complete(loan))

    def test_online_project_starts_at_scan_admin(self):
        loan = self._loan(
            self.project_cat, 'LR-KYC-O',
            source_channel=LoanRequest.SOURCE_ONLINE,
        )
        rows = ensure_intake_screenings(loan)
        self.assertEqual([r.desk for r in rows], [CreditDeskScreening.DESK_SCAN])
        set_screening_status(
            loan, CreditDeskScreening.DESK_SCAN,
            CreditDeskScreening.STATUS_CLEARED, self.officer,
            checklist=complete_checklist_payload(CreditDeskScreening.DESK_SCAN, loan),
        )
        desks = set(
            loan.desk_screenings.values_list('desk', flat=True)
        )
        self.assertIn('crm', desks)
        self.assertIn('engineering', desks)
        self.assertIn('legal', desks)

    def test_kyc_desk_lists_pending_crm(self):
        loan = self._loan(self.project_cat, 'LR-KYC-Q')
        ensure_intake_screenings(loan)
        client = Client()
        client.force_login(self.officer)
        resp = client.get(reverse('kyc_desk') + '?queue=crm')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, loan.loan_request_id)

    def test_http_clear_without_ticks_stays_pending(self):
        loan = self._loan(self.project_cat, 'LR-KYC-HTTP')
        ensure_intake_screenings(loan)
        client = Client()
        client.force_login(self.officer)
        resp = client.post(
            reverse('kyc_screening_action', args=[loan.id]),
            {'desk': 'crm', 'action': 'clear', 'note': 'trying to clear'},
        )
        self.assertEqual(resp.status_code, 302)
        row = loan.desk_screenings.get(desk=CreditDeskScreening.DESK_CRM)
        self.assertEqual(row.status, CreditDeskScreening.STATUS_PENDING)

    def test_loan_detail_shows_kyc_checklist_and_desk_intel(self):
        loan = self._loan(self.project_cat, 'LR-KYC-UI')
        ensure_intake_screenings(loan)
        client = Client()
        client.force_login(self.officer)
        resp = client.get(reverse('loan_request_detail', args=[loan.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'KYC packs')
        self.assertContains(resp, 'Identity documents present')
        self.assertContains(resp, 'Project financing appraisal')

    def test_cannot_clear_crm_without_checklist(self):
        loan = self._loan(self.project_cat, 'LR-KYC-CL')
        ensure_intake_screenings(loan)
        with self.assertRaises(KycClearBlocked):
            set_screening_status(
                loan, CreditDeskScreening.DESK_CRM,
                CreditDeskScreening.STATUS_CLEARED, self.officer, 'ok',
            )

    def test_clear_crm_with_checklist_records_ticks(self):
        loan = self._loan(self.project_cat, 'LR-KYC-OK')
        ensure_intake_screenings(loan)
        row = set_screening_status(
            loan, CreditDeskScreening.DESK_CRM,
            CreditDeskScreening.STATUS_CLEARED, self.officer, 'ok',
            checklist=complete_checklist_payload(CreditDeskScreening.DESK_CRM, loan),
        )
        self.assertEqual(row.status, CreditDeskScreening.STATUS_CLEARED)
        self.assertTrue(row.checklist.get('identity_docs'))
        self.assertTrue(row.checklist.get('pep_sanctions'))
        self.assertIn('sanctions', row.findings)
