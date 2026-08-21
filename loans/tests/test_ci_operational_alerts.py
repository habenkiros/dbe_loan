"""Credit Intelligence operational alerts + Agentic file blockers."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from loans.agent_tools import dispatch_tool
from loans.ci_workspaces import build_risk_alerts
from loans.file_blockers import build_file_blockers
from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanApplicationDocumentType,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
)

User = get_user_model()


class DifferentiatorAlertsTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Diff Dist')
        self.branch = Branch.objects.create(name='Diff Branch', district=district)
        self.category = LoanCategory.objects.create(name='Diff Cat')
        self.collateral = CollateralType.objects.create(name='Building')
        self.doc_type = LoanApplicationDocumentType.objects.create(
            name='National ID Diff', order=1, is_required=True,
        )
        self.bm = User.objects.create_user(
            username='diff_bm', password='pass', phone_number='0911888001',
            role='branch_manager', branch=self.branch, district=district,
        )
        self.lo = User.objects.create_user(
            username='diff_lo', password='pass', phone_number='0911888002',
            role='loan_officer', branch=self.branch, district=district,
        )
        old = timezone.now() - timedelta(days=10)
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-DIFF-1',
            applicant_name='Diff Applicant',
            phone_number='0911888010',
            amount_requested=Decimal('120000'),
            reason='WC',
            category=self.category,
            collateral=self.collateral,
            branch=self.branch,
            district=district,
            status='Pending',
            assigned_loan_officer=self.lo,
            committee_status=LoanRequest.COMMITTEE_PENDING,
            submitted_to_committee_at=old,
            date_requested=old,
            operation_manager_approval=True,
        )
        # Force date_requested in DB (auto_now_add-ish fields may ignore create kwargs)
        LoanRequest.objects.filter(pk=self.loan.pk).update(
            date_requested=old,
            submitted_to_committee_at=old,
        )
        self.loan.refresh_from_db()
        LoanAppraisal.objects.create(
            loan_request=self.loan,
            created_by=self.lo,
            recommendation='approve',
            amount_approved=Decimal('100000'),
            credit_score_total=Decimal('55.0'),
            credit_score_band='weak',
            collateral_coverage_ratio=Decimal('0.5'),
            dscr_annual=Decimal('0.9'),
        )

    @override_settings(CI_AGING_APPRAISAL_DAYS=7, CI_COMMITTEE_SLA_DAYS=5)
    def test_risk_alerts_include_operational_kinds(self):
        alerts = build_risk_alerts(self.bm, limit=24)
        kinds = {a['kind'] for a in alerts}
        self.assertIn('committee_sla', kinds)
        self.assertIn('collateral_coverage', kinds)
        self.assertIn('aging_file', kinds)
        self.assertIn('missing_docs', kinds)
        cov = next(a for a in alerts if a['kind'] == 'collateral_coverage')
        self.assertIn('policy min', cov['body'])

    def test_file_blockers_and_agent_tool(self):
        data = build_file_blockers(self.loan)
        self.assertGreaterEqual(data['blocker_count'], 1)
        self.assertTrue(data['draft_missing_doc_request'])
        self.assertIn('National ID Diff', data['draft_missing_doc_request'])

        out = dispatch_tool(
            self.lo,
            'file_blockers',
            {'loan_id': self.loan.pk},
            conversation=None,
        )
        self.assertTrue(out.get('ok'))
        self.assertEqual(out['loan_request_id'], 'LR-DIFF-1')
        self.assertTrue(out.get('blockers'))
