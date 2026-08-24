"""Fraud / AML case engine and transaction anomaly scoring."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from loans.compliance.case_engine import (
    compliance_blockers,
    open_case,
    origination_compliance_blocked,
    transition_case,
)
from loans.compliance.transaction_fraud import score_transaction_anomalies
from loans.models import Branch, CollateralType, ComplianceCase, District, LoanCategory, LoanRequest


User = get_user_model()


class TransactionFraudScoringTests(TestCase):
    def test_high_nsf_raises_score(self):
        metrics = {'nsf_count': 6, 'negative_balance_days': 12, 'tx_count': 40, 'inflow_cv': 1.3}
        result = score_transaction_anomalies([], metrics=metrics, proposed_installment=Decimal('5000'))
        self.assertGreaterEqual(result['score'], 60)
        self.assertIn(result['risk_band'], ('high', 'critical'))
        self.assertTrue(result['signals'])

    def test_clean_profile_low_score(self):
        metrics = {'nsf_count': 0, 'negative_balance_days': 0, 'tx_count': 20, 'inflow_cv': 0.2}
        result = score_transaction_anomalies([], metrics=metrics, proposed_installment=Decimal('2000'))
        self.assertLess(result['score'], 35)


class ComplianceCaseEngineTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='AML Dist')
        branch = Branch.objects.create(name='AML Branch', district=district)
        category = LoanCategory.objects.create(name='AML Cat')
        collateral = CollateralType.objects.create(name='AML Coll')
        self.risk = User.objects.create_user(
            username='aml_officer', password='x', role='risk_compliance', phone_number='0911000999',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-AML-001',
            applicant_name='Case Test',
            phone_number='0911222333',
            amount_requested=Decimal('75000'),
            reason='Trade',
            category=category,
            branch=branch,
            collateral=collateral,
            operation_manager_approval=True,
            finance_approval=True,
            queue_approved=True,
        )

    def test_open_case_and_close(self):
        case = open_case(
            case_type=ComplianceCase.TYPE_FRAUD,
            source=ComplianceCase.SOURCE_MANUAL,
            summary='Suspected forged ID on intake',
            loan_request=self.loan,
            opened_by=self.risk,
            fingerprint='manual:test:1',
        )
        self.assertIsNotNone(case)
        self.assertTrue(case.is_open)
        self.assertTrue(origination_compliance_blocked(self.loan))
        transition_case(case, self.risk, ComplianceCase.STATUS_FALSE_POSITIVE, note='Verified authentic at branch')
        case.refresh_from_db()
        self.assertFalse(case.is_open)
        self.assertFalse(origination_compliance_blocked(self.loan))

    def test_banking_refresh_opens_aml_case(self):
        from loans.models import LoanAppraisal
        from loans.services.banking_transactions import refresh_appraisal_banking

        appraisal = LoanAppraisal.objects.create(
            loan_request=self.loan,
            proposed_monthly_installment=Decimal('10000'),
        )
        self.loan.customer_number = '2000050041'
        self.loan.save(update_fields=['customer_number'])

        bad_metrics = {
            'nsf_count': 8,
            'negative_balance_days': 15,
            'tx_count': 5,
            'inflow_cv': 1.5,
            'avg_monthly_credit': 1000.0,
            'turnover_vs_installment': 0.1,
        }
        with patch('loans.services.banking_transactions.fetch_account_transactions', return_value=([], 'mock')):
            with patch('loans.services.banking_transactions.compute_banking_metrics', return_value=bad_metrics):
                refresh_appraisal_banking(appraisal, self.loan)
        self.assertTrue(ComplianceCase.objects.filter(loan_request=self.loan, case_type=ComplianceCase.TYPE_AML).exists())

    def test_compliance_desk_accessible(self):
        client = Client()
        self.assertTrue(client.login(username='aml_officer', password='x'))
        resp = client.get(reverse('compliance_desk'))
        self.assertEqual(resp.status_code, 200)

    def test_committee_blocked_with_open_case(self):
        from loans.committee import officer_can_submit_to_committee
        open_case(
            case_type=ComplianceCase.TYPE_FRAUD,
            source=ComplianceCase.SOURCE_DOCUMENT,
            summary='Duplicate document hash on another loan',
            loan_request=self.loan,
            opened_by=self.risk,
            fingerprint='dup:abc',
        )
        result = officer_can_submit_to_committee(self.loan)
        self.assertFalse(result['ok'])
        self.assertTrue(any('Fraud/AML' in e or 'case' in e.lower() for e in result['errors']))
