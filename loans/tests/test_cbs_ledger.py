"""CBS / Temenos outstanding + disbursement booking adapter."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from loans.ci_assistant import run_assistant_query
from loans.credit_intelligence import build_overview
from loans.disbursement import mark_disbursed, mark_ready_for_disbursement, confirm_schedule, start_disbursement_track
from loans.models import (
    AppraisalCondition,
    Branch,
    CollateralType,
    District,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
    LoanRequestBasicInfo,
)
from loans.portfolio_ledger import (
    DecsiCbsLedgerAdapter,
    StubPortfolioLedgerAdapter,
    get_ledger_adapter,
    set_ledger_adapter,
)
from loans.services.cbs_client import (
    BookDisbursementResult,
    fetch_customer_outstanding,
    mock_book_disbursement,
    mock_fetch_customer_outstanding,
)
from loans.views import _generate_amortization_schedule

User = get_user_model()


@override_settings(
    DECSI_LEDGER_ADAPTER='cbs',
    DECSI_CBS_USE_MOCK_LEDGER=True,
    DECSI_CBS_FORCE_MOCK=True,
    DECSI_CBS_BOOK_ON_DISBURSE=True,
    DECSI_BASE_URL='',
)
class CbsLedgerTests(TestCase):
    def setUp(self):
        set_ledger_adapter(None)
        district = District.objects.create(name='CBS Dist')
        self.branch = Branch.objects.create(name='CBS Branch', district=district)
        collateral = CollateralType.objects.create(name='CBS Coll')
        category = LoanCategory.objects.create(name='CBS MSME')
        self.officer = User.objects.create_user(
            username='cbs_officer', password='pass', phone_number='0911555001',
            role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-CBS-1',
            applicant_name='CBS Applicant',
            phone_number='0911555010',
            amount_requested=Decimal('100000'),
            reason='WC',
            category=category,
            branch=self.branch,
            collateral=collateral,
            assigned_loan_officer=self.officer,
            customer_number='1001',
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            committee_final_amount=Decimal('90000'),
            committee_decided_at=timezone.now(),
            appraisal_completed_at=timezone.now(),
            queue_approved=True,
            operation_manager_approval=True,
            finance_approval=True,
        )
        self.appraisal = LoanAppraisal.objects.create(
            loan_request=self.loan,
            created_by=self.officer,
            recommendation='approve',
            amount_approved=Decimal('90000'),
            term_approved_months=12,
            rate_approved=Decimal('15'),
        )
        self.basic = LoanRequestBasicInfo.objects.create(
            loan_request=self.loan, term_months=12, interest_rate=Decimal('15'),
        )
        AppraisalCondition.objects.create(
            appraisal=self.appraisal,
            condition_type=AppraisalCondition.TYPE_CP,
            description='Clear',
            required_before_disbursement=True,
            fulfilled=True,
        )
        start_disbursement_track(self.loan)
        self.loan.refresh_from_db()
        self.loan.disbursement_status = LoanRequest.DISBURSE_READY
        self.loan.schedule_confirmed_at = timezone.now()
        self.loan.finance_disbursement_approval = True
        self.loan.save(update_fields=[
            'disbursement_status', 'schedule_confirmed_at', 'finance_disbursement_approval',
        ])

    def tearDown(self):
        set_ledger_adapter(None)

    def test_mock_outstanding(self):
        row = mock_fetch_customer_outstanding('1001')
        self.assertIsNotNone(row)
        self.assertGreater(row.total_outstanding, 0)
        fetched = fetch_customer_outstanding('1001')
        self.assertEqual(fetched.provider, 'mock')

    def test_adapter_connected_and_overview(self):
        adapter = get_ledger_adapter()
        self.assertIsInstance(adapter, DecsiCbsLedgerAdapter)
        self.assertTrue(adapter.is_connected())
        out = adapter.total_outstanding(self.officer)
        self.assertIsNotNone(out)
        data = build_overview(self.officer)
        self.assertTrue(data['ledger']['connected'])
        keys = {k['key'] for k in data['kpis']}
        self.assertIn('cbs_outstanding', keys)

    def test_book_on_mark_disbursed(self):
        _generate_amortization_schedule(self.appraisal, self.basic, self.loan)
        ok, err = mark_disbursed(self.loan, self.officer, notes='wire done')
        self.assertTrue(ok, err)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.disbursement_status, LoanRequest.DISBURSE_DISBURSED)
        self.assertTrue(self.loan.cbs_booking_ref.startswith('MOCK-DISB-'))
        self.assertEqual(self.loan.cbs_booking_status, LoanRequest.CBS_BOOK_MOCK)
        self.assertIsNotNone(self.loan.cbs_outstanding_at_booking)

    def test_book_requires_customer_number(self):
        self.loan.customer_number = ''
        self.loan.save(update_fields=['customer_number'])
        ok, err = mark_disbursed(self.loan, self.officer)
        self.assertFalse(ok)
        self.assertTrue(err)

    def test_assistant_uses_ledger_when_connected(self):
        ans = run_assistant_query(self.officer, 'What is total outstanding?')
        self.assertTrue(ans['understood'])
        # Mock ledger returns a number, not the stub "not wired" message
        self.assertNotIn('not wired', ans['answer'].lower())

    @override_settings(DECSI_LEDGER_ADAPTER='stub', DECSI_CBS_BOOK_ON_DISBURSE=True)
    def test_stub_blocks_book_when_required(self):
        set_ledger_adapter(None)
        self.assertIsInstance(get_ledger_adapter(), StubPortfolioLedgerAdapter)
        ok, err = mark_disbursed(self.loan, self.officer)
        self.assertFalse(ok)
        self.assertIn('not connected', err[0].lower())
