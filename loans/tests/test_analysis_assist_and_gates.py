"""Mode-aware analysis gates and analysis-assist panel."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from loans.analysis_assist import build_analysis_assist, officer_checklist_for_mode
from loans.appraisal_mode import MODE_CORPORATE, MODE_MSME
from loans.appraisal_scorecard import evaluate_analysis_gates
from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
    LoanRequestBasicInfo,
)


User = get_user_model()


class AnalysisAssistAndGatesTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Assist Dist')
        self.branch = Branch.objects.create(name='Assist Branch', district=district)
        collateral = CollateralType.objects.create(name='Assist Collateral')
        self.corp_cat = LoanCategory.objects.create(name='Corp Assist', appraisal_mode=MODE_CORPORATE)
        self.msme_cat = LoanCategory.objects.create(name='MSME Assist', appraisal_mode=MODE_MSME)
        self.officer = User.objects.create_user(
            username='assist_officer', password='pass', phone_number='0911222777', role='loan_officer',
        )

    def _loan(self, *, category, lid, name='Assist Co', cr=None):
        loan = LoanRequest.objects.create(
            loan_request_id=lid,
            applicant_name=name,
            phone_number='0911000444',
            amount_requested=Decimal('100000'),
            reason='WC',
            category=category,
            branch=self.branch,
            collateral=CollateralType.objects.first(),
            operation_manager_approval=True,
            finance_approval=True,
            queue_approved=True,
            assigned_loan_officer=self.officer,
        )
        basic = LoanRequestBasicInfo.objects.create(
            loan_request=loan,
            business_name=name,
            legal_registration_number=cr or '',
        )
        appraisal = LoanAppraisal.objects.create(
            loan_request=loan,
            created_by=self.officer,
            appraisal_mode=category.appraisal_mode,
        )
        return loan, basic, appraisal

    def test_corporate_missing_cr_is_hard_block(self):
        _loan, basic, appraisal = self._loan(category=self.corp_cat, lid='LR-ASSIST-1', cr='')
        blocks, _warnings = evaluate_analysis_gates(appraisal, basic)
        self.assertTrue(any('registration' in b.lower() or 'CR' in b for b in blocks))

    def test_corporate_with_cr_no_registration_block(self):
        _loan, basic, appraisal = self._loan(category=self.corp_cat, lid='LR-ASSIST-2', cr='CR-99')
        blocks, warnings = evaluate_analysis_gates(appraisal, basic)
        self.assertFalse(any('registration' in b.lower() for b in blocks))
        self.assertTrue(any('audited' in w.lower() or 'revenue' in w.lower() for w in warnings))

    def test_msme_nbe_warning(self):
        _loan, basic, appraisal = self._loan(category=self.msme_cat, lid='LR-ASSIST-3')
        _blocks, warnings = evaluate_analysis_gates(appraisal, basic)
        self.assertTrue(any('NBE' in w for w in warnings))

    def test_build_analysis_assist_returns_insights(self):
        _loan, basic, appraisal = self._loan(category=self.corp_cat, lid='LR-ASSIST-4', cr='')
        assist = build_analysis_assist(appraisal, basic)
        self.assertEqual(assist['appraisal_mode'], MODE_CORPORATE)
        self.assertTrue(assist['blocks'] or assist['insights'])
        titles = ' '.join(i['title'] for i in assist['insights'])
        self.assertIn('registration', titles.lower())

    def test_officer_checklist_mode_specific(self):
        corp = officer_checklist_for_mode(MODE_CORPORATE)
        msme = officer_checklist_for_mode(MODE_MSME)
        self.assertTrue(any('CR' in x or 'registration' in x.lower() for x in corp))
        self.assertTrue(any('cashflow' in x.lower() or 'DSCR' in x for x in msme))
        self.assertNotEqual(corp[0], msme[0])
