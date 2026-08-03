"""Corporate appraisal mode: category stamp, Sheet 2 governance factors."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from loans.appraisal_mode import MODE_CORPORATE, MODE_MSME, resolve_appraisal_mode
from loans.models import (
    AppraisalQualitativeFactor,
    Branch,
    CollateralType,
    CORPORATE_QUALITATIVE_FACTOR_KEYS,
    District,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
    LoanRequestBasicInfo,
    QUALITATIVE_FACTOR_KEYS,
)
from loans.views import _ensure_qualitative_factors


User = get_user_model()


class CorporateAppraisalModeTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Corp Dist')
        self.branch = Branch.objects.create(name='Corp Branch', district=district)
        collateral = CollateralType.objects.create(name='Corp Collateral')
        self.msme_cat = LoanCategory.objects.create(name='MSME CorpTest', appraisal_mode=MODE_MSME)
        self.corp_cat = LoanCategory.objects.create(name='Corporate CorpTest', appraisal_mode=MODE_CORPORATE)
        self.officer = User.objects.create_user(
            username='corp_officer', password='pass', phone_number='0911222666', role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-CORP-001',
            applicant_name='Acme PLC',
            phone_number='0911000222',
            amount_requested=Decimal('500000'),
            reason='Expansion',
            category=self.corp_cat,
            branch=self.branch,
            collateral=collateral,
            operation_manager_approval=True,
            finance_approval=True,
            queue_approved=True,
            assigned_loan_officer=self.officer,
        )
        self.basic = LoanRequestBasicInfo.objects.create(
            loan_request=self.loan,
            business_name='Acme PLC',
            legal_registration_number='CR-12345',
        )
        self.appraisal = LoanAppraisal.objects.create(
            loan_request=self.loan,
            created_by=self.officer,
            appraisal_mode=MODE_CORPORATE,
        )

    def test_resolve_mode_from_category(self):
        self.assertEqual(resolve_appraisal_mode(self.loan), MODE_CORPORATE)
        msme_loan = LoanRequest.objects.create(
            loan_request_id='LR-CORP-002',
            applicant_name='Small Biz',
            phone_number='0911000333',
            amount_requested=Decimal('10000'),
            reason='WC',
            category=self.msme_cat,
            branch=self.branch,
            collateral=self.loan.collateral,
            operation_manager_approval=True,
            finance_approval=True,
            queue_approved=True,
            assigned_loan_officer=self.officer,
        )
        self.assertEqual(resolve_appraisal_mode(msme_loan), MODE_MSME)

    def test_sheet6_draft_save_allowed_when_recommendation_was_empty(self):
        """Hard blocks must not prevent saving the Sheet 6 fields that clear those blocks."""
        from django.urls import reverse
        from loans.models import LoanAnalysisPolicyConfig

        LoanAnalysisPolicyConfig.objects.all().delete()
        LoanAnalysisPolicyConfig.objects.create(hard_block_incomplete_sheets=True)
        self.assertFalse(self.appraisal.recommendation)
        self.assertFalse(self.appraisal.strengths)
        self.assertFalse(self.appraisal.weaknesses)

        self.client.login(username='corp_officer', password='pass')
        url = reverse('loan_appraisal_step', args=[self.loan.pk, 6])
        res = self.client.post(url, {
            'recommendation': 'approve',
            'recommendation_comment': 'Strong cashflow and collateral coverage.',
            'strengths': 'Registered corporate; stable revenue.',
            'weaknesses': 'Sector concentration.',
            'committee_comments': '',
            'amount_approved': '500000',
            'term_approved_months': '36',
            'rate_approved': '14.5',
            'save': '1',
            'risk-TOTAL_FORMS': '0',
            'risk-INITIAL_FORMS': '0',
            'risk-MIN_NUM_FORMS': '0',
            'risk-MAX_NUM_FORMS': '1000',
            'cond-TOTAL_FORMS': '0',
            'cond-INITIAL_FORMS': '0',
            'cond-MIN_NUM_FORMS': '0',
            'cond-MAX_NUM_FORMS': '1000',
        })
        self.assertEqual(res.status_code, 302, getattr(res, 'content', b'')[:500])
        self.appraisal.refresh_from_db()
        self.assertEqual(self.appraisal.recommendation, 'approve')
        self.assertIn('Registered corporate', self.appraisal.strengths)
        self.assertIn('concentration', self.appraisal.weaknesses)

    def test_corporate_qualitative_factors_seeded(self):
        _ensure_qualitative_factors(self.appraisal)
        keys = set(self.appraisal.qualitative_factors.values_list('factor_key', flat=True))
        expected = {k for k, _ in CORPORATE_QUALITATIVE_FACTOR_KEYS}
        self.assertEqual(keys, expected)
        self.assertNotIn('years_operation', keys)

    def test_switching_mode_replaces_factors(self):
        _ensure_qualitative_factors(self.appraisal)
        self.assertEqual(self.appraisal.qualitative_factors.count(), 10)
        self.appraisal.appraisal_mode = MODE_MSME
        self.appraisal.save(update_fields=['appraisal_mode'])
        _ensure_qualitative_factors(self.appraisal)
        keys = set(self.appraisal.qualitative_factors.values_list('factor_key', flat=True))
        self.assertEqual(keys, {k for k, _ in QUALITATIVE_FACTOR_KEYS})
        self.assertIn('years_operation', keys)
