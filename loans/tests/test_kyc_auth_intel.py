"""KYC document-auth committee gate + product-desk appraisal intel."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from loans.document_checklist import checklist_for_category
from loans.kyc_desk import complete_checklist_payload, ensure_intake_screenings, set_screening_status
from loans.models import (
    Branch,
    CollateralType,
    CreditDeskScreening,
    District,
    LoanApplicationDocumentType,
    LoanCategory,
    LoanCategoryDocumentRequirement,
    LoanRequest,
)
from loans.product_family import FAMILY_CONSUMER, FAMILY_GENERAL, FAMILY_PROJECT
from loans.product_intel import build_product_intel, compact_product_desk
from loans.services.document_auth import document_committee_blockers


User = get_user_model()


class KycAuthAndProductIntelTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='Intel Dist')
        self.branch = Branch.objects.create(name='Intel Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='Intel Coll')
        self.officer = User.objects.create_user(
            username='intel_clo', password='pass', phone_number='0911777001',
            role='credit_loan_officer',
        )
        self.project_cat = LoanCategory.objects.create(
            name='Intel Project', product_family=FAMILY_PROJECT, appraisal_mode=FAMILY_PROJECT,
        )
        self.general_cat = LoanCategory.objects.create(
            name='Intel MSME', product_family=FAMILY_GENERAL, appraisal_mode='msme',
        )
        self.consumer_cat = LoanCategory.objects.create(
            name='Intel Consumer', product_family=FAMILY_CONSUMER, appraisal_mode=FAMILY_CONSUMER,
        )

    def _loan(self, category, lid):
        return LoanRequest.objects.create(
            loan_request_id=lid,
            applicant_name='Intel Co',
            phone_number='0911000999',
            amount_requested=Decimal('800000'),
            reason='desk',
            category=category,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
        )

    def test_project_document_mode_not_on_msme_fallback(self):
        LoanApplicationDocumentType.objects.create(
            name='Feasibility Intel', order=90, is_required=True, for_appraisal_mode=FAMILY_PROJECT,
        )
        LoanApplicationDocumentType.objects.create(
            name='National ID Intel', order=10, is_required=True, for_appraisal_mode='msme',
        )
        empty_msme = LoanCategory.objects.create(
            name='Intel Empty MSME', product_family=FAMILY_GENERAL, appraisal_mode='msme',
        )
        names = [i.name for i in checklist_for_category(empty_msme)]
        self.assertIn('National ID Intel', names)
        self.assertNotIn('Feasibility Intel', names)
        names_p = [i.name for i in checklist_for_category(self.project_cat)]
        self.assertIn('Feasibility Intel', names_p)
        self.assertNotIn('National ID Intel', names_p)

    def test_missing_pack_blocks_committee_for_project(self):
        dt = LoanApplicationDocumentType.objects.create(
            name='Site evidence Intel', order=91, is_required=True, for_appraisal_mode=FAMILY_PROJECT,
        )
        LoanCategoryDocumentRequirement.objects.create(
            category=self.project_cat, document_type=dt, is_required=True, order=1,
        )
        loan = self._loan(self.project_cat, 'LR-INT-DOC')
        blockers = document_committee_blockers(loan)
        self.assertTrue(blockers)
        self.assertTrue(any('Site evidence Intel' in b for b in blockers))
        msme = self._loan(self.general_cat, 'LR-INT-MSME')
        self.assertEqual(document_committee_blockers(msme), [])

    def test_project_intel_shows_kyc_gates(self):
        loan = self._loan(self.project_cat, 'LR-INT-P')
        intel = build_product_intel(loan)
        self.assertIsNotNone(intel)
        self.assertEqual(intel['family'], FAMILY_PROJECT)
        self.assertEqual(intel['decision']['code'], 'blocked')
        self.assertTrue(any('KYC' in b for b in intel['blockers']))
        compact = compact_product_desk(loan)
        self.assertEqual(compact['band'], 'blocked')
        self.assertFalse(compact['kyc_complete'])

    def test_msme_has_no_product_desk_intel(self):
        loan = self._loan(self.general_cat, 'LR-INT-G')
        self.assertIsNone(build_product_intel(loan))
        self.assertEqual(compact_product_desk(loan), {})

    def test_consumer_intel_after_kyc(self):
        loan = self._loan(self.consumer_cat, 'LR-INT-C')
        ensure_intake_screenings(loan)
        for desk in ('crm', 'engineering', 'legal'):
            set_screening_status(
                loan, desk, CreditDeskScreening.STATUS_CLEARED, self.officer, 'ok',
                checklist=complete_checklist_payload(desk, loan),
            )
        intel = build_product_intel(loan)
        self.assertEqual(intel['family'], FAMILY_CONSUMER)
        self.assertTrue(intel['kyc']['complete'])
        self.assertIn(intel['decision']['code'], ('blocked', 'review'))
