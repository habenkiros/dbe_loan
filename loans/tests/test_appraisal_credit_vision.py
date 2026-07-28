"""Credit analysis vision: qualitative scoring, scorecard, features, capacity."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from loans.appraisal_features import build_appraisal_features, persist_feature_snapshot
from loans.appraisal_scorecard import build_credit_scorecard, persist_credit_scorecard
from loans.appraisal_vision import FEATURE_SCHEMA_VERSION, GAP_MAP, RATE_WORKBOOK_EXCLUDED, SAMPLE_BIBLE
from loans.cashflow_utils import max_loan_capacity_from_cashflow, suggested_installment_declining
from loans.models import (
    AppraisalQualitativeFactor,
    Branch,
    CollateralType,
    District,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
    LoanRequestBasicInfo,
    QUALITATIVE_FACTOR_KEYS,
    QUALITATIVE_RATING_CHOICES_BY_FACTOR,
)
from loans.qualitative_scoring import update_appraisal_qualitative_totals


User = get_user_model()


class AppraisalCreditVisionTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Central')
        self.branch = Branch.objects.create(name='Main', district=district)
        collateral = CollateralType.objects.create(name='Building')
        category = LoanCategory.objects.create(name='MSME')
        self.officer = User.objects.create_user(
            username='app_officer', password='pass', phone_number='0911222333', role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-APP-001',
            applicant_name='Appraisal Applicant',
            phone_number='0911000000',
            amount_requested=Decimal('100000'),
            reason='Working capital',
            category=category,
            branch=self.branch,
            collateral=collateral,
            operation_manager_approval=True,
            finance_approval=True,
            queue_approved=True,
            assigned_loan_officer=self.officer,
        )
        self.basic = LoanRequestBasicInfo.objects.create(
            loan_request=self.loan,
            term_months=24,
            interest_rate=Decimal('18'),
            repayment_frequency='Monthly',
        )
        self.appraisal = LoanAppraisal.objects.create(
            loan_request=self.loan,
            created_by=self.officer,
        )
        for order, (key, name) in enumerate(QUALITATIVE_FACTOR_KEYS):
            from loans.qualitative_scoring import best_rating_for_factor
            best = best_rating_for_factor(key) or QUALITATIVE_RATING_CHOICES_BY_FACTOR[key][0]
            AppraisalQualitativeFactor.objects.create(
                appraisal=self.appraisal,
                factor_key=key,
                factor_name=name,
                rating=best,
                display_order=order,
            )

    def test_vision_lock_excludes_rate_workbook(self):
        self.assertIn('Cashflow', SAMPLE_BIBLE)
        self.assertIn('rate', RATE_WORKBOOK_EXCLUDED.lower())
        self.assertEqual(GAP_MAP['rate_workbook']['status'], 'excluded')
        self.assertEqual(FEATURE_SCHEMA_VERSION, 'appraisal_features_v2')

    def test_qualitative_scoring_pass(self):
        total, passed = update_appraisal_qualitative_totals(self.appraisal)
        self.appraisal.refresh_from_db()
        self.assertGreaterEqual(total, Decimal('75'))
        self.assertTrue(passed)
        self.assertEqual(self.appraisal.qualitative_total_score, total)

    def test_cashflow_capacity_helpers(self):
        sug = suggested_installment_declining(Decimal('100000'), Decimal('18'), 24, 12)
        self.assertIsNotNone(sug)
        self.assertGreater(sug, 0)
        cap = max_loan_capacity_from_cashflow(Decimal('60000'), Decimal('18'), 24, Decimal('1.2'), 12)
        self.assertIsNotNone(cap)
        self.assertGreater(cap, 0)

    def test_scorecard_and_features(self):
        from loans.services.banking_transactions import refresh_appraisal_banking
        update_appraisal_qualitative_totals(self.appraisal)
        self.loan.customer_number = '1001'
        self.loan.save(update_fields=['customer_number'])
        self.appraisal.dscr = Decimal('1.5')
        self.appraisal.dscr_annual = Decimal('1.4')
        self.appraisal.proposed_monthly_installment = Decimal('5000')
        self.appraisal.es_eligibility_decision = LoanAppraisal.ES_ELIGIBILITY_PASS
        self.appraisal.es_risk_category = LoanAppraisal.ES_RISK_LOW
        self.appraisal.collateral_coverage_ratio = Decimal('1.3')
        self.appraisal.max_loan_capacity = Decimal('120000')
        self.appraisal.bureau_score_band = 'good'
        self.appraisal.save()
        refresh_appraisal_banking(self.appraisal, self.loan)
        card = persist_credit_scorecard(self.appraisal)
        self.assertEqual(card['schema'], 'credit_scorecard_v2')
        self.assertEqual(len(card['pillars']), 5)
        self.assertTrue(any(p['key'] == 'banking' for p in card['pillars']))
        self.assertGreater(card['total'], 40)
        snap = persist_feature_snapshot(self.loan, appraisal=self.appraisal, basic_info=self.basic)
        self.assertEqual(snap['schema_version'], FEATURE_SCHEMA_VERSION)
        self.assertIn('banking', snap)
        self.assertTrue((snap.get('banking') or {}).get('tx_count', 0) > 0)
        self.appraisal.refresh_from_db()
        self.assertEqual(self.appraisal.feature_snapshot['schema_version'], FEATURE_SCHEMA_VERSION)
        built = build_appraisal_features(self.loan, appraisal=self.appraisal, basic_info=self.basic)
        self.assertIn('qualitative', built)
        self.assertIn('cashflow', built)
