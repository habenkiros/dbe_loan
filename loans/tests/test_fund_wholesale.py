"""Phase C — fund covenants + wholesale PFI. DECSI general stays ungated without a fund."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from loans.committee import officer_can_submit_to_committee
from loans.disbursement import add_disbursement_tranche
from loans.engines import FundEngine, WholesaleEngine, get_engine
from loans.fund_overlay import fund_committee_blockers, fund_disbursement_blockers
from loans.models import (
    Branch,
    CollateralType,
    District,
    FinancingFund,
    LoanCategory,
    LoanRequest,
    PfiInstitutionProfile,
    PfiUtilizationReport,
)
from loans.product_family import FAMILY_EXTERNAL_FUND, FAMILY_GENERAL, FAMILY_WHOLESALE
from loans.wholesale_overlay import (
    wholesale_committee_blockers,
    wholesale_disbursement_blockers,
)


User = get_user_model()


class FundAndWholesaleTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='FW Dist')
        self.branch = Branch.objects.create(name='FW Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='FW Coll')
        self.officer = User.objects.create_user(
            username='fw_lo', password='pass', phone_number='0911222333', role='loan_officer',
        )
        self.general = LoanCategory.objects.create(
            name='FW MSME', appraisal_mode='msme', product_family=FAMILY_GENERAL,
        )
        self.wholesale = LoanCategory.objects.create(
            name='FW PFI', appraisal_mode='corporate', product_family=FAMILY_WHOLESALE,
        )
        self.ext = LoanCategory.objects.create(
            name='FW Fund', appraisal_mode='msme', product_family=FAMILY_EXTERNAL_FUND,
        )
        self.kfw = FinancingFund.objects.create(
            code='KFW21826',
            name='EU/KfW MSME recovery',
            kind=FinancingFund.KIND_DONOR,
            source_name='KfW / EU',
            envelope_amount=Decimal('1000000'),
            dbe_to_pfi_rate_pct=Decimal('4.50'),
            max_end_user_rate_pct=Decimal('11.00'),
            eligible_regions='Tigray, Amhara, Afar',
            women_min_pct=Decimal('30'),
            youth_min_pct=Decimal('20'),
            par90_max_pct=Decimal('10'),
        )

    def _loan(self, category, lid='LR-FW-1', **extra):
        defaults = dict(
            loan_request_id=lid,
            applicant_name='DECSI',
            phone_number='0911000111',
            amount_requested=Decimal('500000'),
            reason='WC on-lending',
            category=category,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
        )
        defaults.update(extra)
        return LoanRequest.objects.create(**defaults)

    def _ready_pfi(self, loan, **extra):
        kwargs = dict(
            loan_request=loan,
            institution_name='Tigray Microfinance',
            kind=PfiInstitutionProfile.KIND_MFI,
            license_number='MFI-001',
            footprint_regions='Tigray',
            has_adequate_mis=True,
            capital=Decimal('2000000'),
            npl_pct=Decimal('4.00'),
            par90_pct=Decimal('6.00'),
            par30_pct=Decimal('8.00'),
            audited_year=2024,
            credit_policy_on_file=True,
            on_lending_policy_on_file=True,
            has_governance=True,
            has_esms=True,
            facility_amount=Decimal('500000'),
            tenor_months=36,
            facility_purpose=PfiInstitutionProfile.PURPOSE_WC,
            end_user_rate_ceiling_pct=Decimal('11.00'),
            dbe_to_pfi_rate_pct=Decimal('4.50'),
            target_women_pct=Decimal('30'),
            target_youth_pct=Decimal('20'),
            target_regions='Tigray',
        )
        kwargs.update(extra)
        profile = PfiInstitutionProfile.objects.create(**kwargs)
        from loans.wholesale_appraisal import sync_wholesale_decision_to_appraisal
        sync_wholesale_decision_to_appraisal(
            loan, profile, self.officer,
            recommendation='approve',
            amount_approved=profile.facility_amount,
            rate_approved=profile.dbe_to_pfi_rate_pct,
            term_approved_months=profile.tenor_months,
            recommendation_comment='PFI controls and PAR within fund band.',
        )
        return profile

    def test_general_without_fund_is_ungated(self):
        loan = self._loan(self.general, lid='LR-FW-G')
        self.assertEqual(get_engine(loan).committee_blockers(), [])
        self.assertEqual(get_engine(loan).disbursement_blockers(), [])
        self.assertIsNone(get_engine(loan).file_summary())

    def test_envelope_blocks_when_line_is_full(self):
        taken = self._loan(self.general, lid='LR-FW-TK', financing_fund=self.kfw, amount_requested=Decimal('900000'))
        taken.committee_status = LoanRequest.COMMITTEE_APPROVED
        taken.committee_final_amount = Decimal('900000')
        taken.save(update_fields=['committee_status', 'committee_final_amount'])
        loan = self._loan(self.general, lid='LR-FW-OV', financing_fund=self.kfw, amount_requested=Decimal('200000'))
        blockers = fund_committee_blockers(loan)
        self.assertTrue(any('envelope' in b.lower() for b in blockers))

    def test_wholesale_blocked_without_institution_file(self):
        loan = self._loan(self.wholesale, lid='LR-FW-NP', financing_fund=self.kfw)
        self.assertIsInstance(get_engine(loan), WholesaleEngine)
        blockers = wholesale_committee_blockers(loan)
        self.assertTrue(any('institution' in b.lower() or 'PFI' in b for b in blockers))
        check = officer_can_submit_to_committee(loan)
        self.assertFalse(check['ok'])
        self.assertFalse(any('Sheet' in e for e in check['errors']))

    def test_decsi_21826_line_can_go_to_committee_without_sheet3(self):
        loan = self._loan(self.wholesale, lid='LR-FW-OK', financing_fund=self.kfw)
        self._ready_pfi(loan)
        self.assertEqual(wholesale_committee_blockers(loan), [])
        self.assertEqual(fund_committee_blockers(loan), [])
        check = officer_can_submit_to_committee(loan)
        self.assertFalse(any('Sheet' in e or 'NPV' in e or 'Plant' in e for e in check['errors']))

    def test_par90_over_ten_blocks(self):
        loan = self._loan(self.wholesale, lid='LR-FW-PAR', financing_fund=self.kfw)
        self._ready_pfi(loan, par90_pct=Decimal('14.00'))
        blockers = wholesale_committee_blockers(loan) + fund_committee_blockers(loan)
        self.assertTrue(any('PAR' in b for b in blockers))

    def test_end_user_rate_over_ceiling_blocks(self):
        loan = self._loan(self.wholesale, lid='LR-FW-RT', financing_fund=self.kfw)
        self._ready_pfi(loan, end_user_rate_ceiling_pct=Decimal('15.00'))
        self.assertTrue(any('End-user' in b for b in fund_committee_blockers(loan)))

    def test_women_cut_below_fund_blocks(self):
        loan = self._loan(self.wholesale, lid='LR-FW-W', financing_fund=self.kfw)
        self._ready_pfi(loan, target_women_pct=Decimal('10'))
        self.assertTrue(any('women' in b.lower() for b in fund_committee_blockers(loan)))

    def test_region_outside_21826_blocks(self):
        loan = self._loan(self.wholesale, lid='LR-FW-RG', financing_fund=self.kfw)
        self._ready_pfi(loan, footprint_regions='Addis Ababa', target_regions='Addis Ababa')
        self.assertTrue(any('Tigray' in b or 'limited to' in b for b in fund_committee_blockers(loan)))

    def test_second_draw_needs_utilization_report(self):
        loan = self._loan(self.wholesale, lid='LR-FW-UT', financing_fund=self.kfw)
        profile = self._ready_pfi(loan)
        add_disbursement_tranche(loan, Decimal('200000'), note='first envelope')
        tranche = loan.disbursement_tranches.get(sequence=1)
        tranche.status = tranche.STATUS_DISBURSED
        tranche.disbursed_at = timezone.now()
        tranche.save(update_fields=['status', 'disbursed_at'])
        loan.disbursement_status = loan.DISBURSE_PARTIAL
        loan.save(update_fields=['disbursement_status'])
        blockers = wholesale_disbursement_blockers(loan)
        self.assertTrue(any('utilization' in b.lower() for b in blockers))
        PfiUtilizationReport.objects.create(
            profile=profile, as_of=timezone.localdate(),
            amount_onlent=Decimal('150000'), pfi_repaid_to_dbe=Decimal('0'),
            sub_par90_pct=Decimal('5'), women_onlent_pct=Decimal('32'),
            youth_onlent_pct=Decimal('22'),
        )
        self.assertFalse(any('utilization' in b.lower() for b in wholesale_disbursement_blockers(loan)))

    def test_sub_par90_over_cap_blocks_next_draw(self):
        loan = self._loan(self.wholesale, lid='LR-FW-PARU', financing_fund=self.kfw)
        profile = self._ready_pfi(loan)
        add_disbursement_tranche(loan, Decimal('200000'), note='first envelope')
        tranche = loan.disbursement_tranches.get(sequence=1)
        tranche.status = tranche.STATUS_DISBURSED
        tranche.disbursed_at = timezone.now()
        tranche.save(update_fields=['status', 'disbursed_at'])
        loan.disbursement_status = loan.DISBURSE_PARTIAL
        loan.save(update_fields=['disbursement_status'])
        PfiUtilizationReport.objects.create(
            profile=profile, as_of=timezone.localdate(),
            amount_onlent=Decimal('150000'), pfi_repaid_to_dbe=Decimal('0'),
            sub_par90_pct=Decimal('15'),
        )
        blockers = wholesale_disbursement_blockers(loan)
        self.assertTrue(any('PAR>90' in b or 'PAR' in b for b in blockers))

    def test_officer_can_open_pfi_file(self):
        loan = self._loan(self.wholesale, lid='LR-FW-UI')
        self.client.force_login(self.officer)
        resp = self.client.get(reverse('wholesale_file', args=[loan.id]))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(reverse('wholesale_file', args=[loan.id]), {
            'institution_name': 'Awash Bank PFI',
            'kind': PfiInstitutionProfile.KIND_MFI,
            'license_number': 'MFI-9',
            'ownership': 'Regional',
            'footprint_regions': 'Tigray',
            'has_adequate_mis': 'on',
            'capital': '2000000',
            'npl_pct': '4',
            'par30_pct': '8',
            'par90_pct': '6',
            'audited_year': '2024',
            'credit_policy_on_file': 'on',
            'on_lending_policy_on_file': 'on',
            'has_governance': 'on',
            'has_esms': 'on',
            'facility_amount': '500000',
            'tenor_months': '36',
            'facility_purpose': PfiInstitutionProfile.PURPOSE_WC,
            'end_user_rate_ceiling_pct': '11',
            'dbe_to_pfi_rate_pct': '4.5',
            'target_women_pct': '30',
            'target_youth_pct': '20',
            'target_regions': 'Tigray',
            'notes': '',
            'recommendation': 'approve',
            'amount_approved': '500000',
            'rate_approved': '4.5',
            'term_approved_months': '36',
            'recommendation_comment': 'Ready for committee.',
            'strengths': 'PAR and MIS adequate.',
            'weaknesses': '',
        })
        self.assertEqual(resp.status_code, 302)
        loan.refresh_from_db()
        self.assertEqual(loan.pfi_profile.institution_name, 'Awash Bank PFI')
        from loans.models import LoanAppraisal
        appr = LoanAppraisal.objects.get(loan_request=loan)
        self.assertEqual(appr.recommendation, 'approve')
        self.assertEqual(appr.scorecard_detail['modality'], 'wholesale')

    def test_general_cannot_open_pfi_page(self):
        loan = self._loan(self.general, lid='LR-FW-NO')
        self.client.force_login(self.officer)
        resp = self.client.get(reverse('wholesale_file', args=[loan.id]))
        self.assertEqual(resp.status_code, 302)

    def test_external_fund_family_requires_window(self):
        loan = self._loan(self.ext, lid='LR-FW-EF')
        engine = get_engine(loan)
        self.assertIsInstance(engine, FundEngine)
        self.assertTrue(any('funding window' in b.lower() for b in engine.committee_blockers()))

    def test_fund_disbursement_empty_without_envelope_pressure(self):
        loan = self._loan(self.general, lid='LR-FW-OK2', financing_fund=self.kfw, amount_requested=Decimal('10000'))
        self.assertEqual(fund_disbursement_blockers(loan), [])

    def test_wholesale_appraisal_scorecard_and_evidence(self):
        from loans.committee_evidence import build_committee_vote_evidence
        from loans.wholesale_appraisal import (
            build_wholesale_scorecard,
            sync_wholesale_decision_to_appraisal,
            wholesale_appraisal_blockers,
        )

        loan = self._loan(self.wholesale, lid='LR-FW-SC', financing_fund=self.kfw)
        profile = PfiInstitutionProfile.objects.create(
            loan_request=loan,
            institution_name='Scorecard MFI',
            kind=PfiInstitutionProfile.KIND_MFI,
            license_number='MFI-SC',
            has_adequate_mis=True,
            capital=Decimal('3000000'),
            npl_pct=Decimal('3.00'),
            par30_pct=Decimal('5.00'),
            par90_pct=Decimal('4.00'),
            audited_year=2024,
            credit_policy_on_file=True,
            on_lending_policy_on_file=True,
            has_governance=True,
            has_esms=True,
            facility_amount=Decimal('400000'),
            tenor_months=24,
            end_user_rate_ceiling_pct=Decimal('11.00'),
            dbe_to_pfi_rate_pct=Decimal('4.50'),
        )
        self.assertTrue(wholesale_appraisal_blockers(loan))
        card = build_wholesale_scorecard(loan, profile)
        self.assertEqual(card['modality'], 'wholesale')
        self.assertGreaterEqual(card['total'], Decimal('60'))
        appraisal, saved = sync_wholesale_decision_to_appraisal(
            loan, profile, self.officer,
            recommendation='approve',
            amount_approved=Decimal('400000'),
            rate_approved=Decimal('4.50'),
            term_approved_months=24,
            recommendation_comment='Controls and PAR support facility.',
        )
        self.assertEqual(appraisal.recommendation, 'approve')
        self.assertEqual(appraisal.scorecard_detail['modality'], 'wholesale')
        self.assertEqual(saved['modality'], 'wholesale')
        self.assertEqual(wholesale_committee_blockers(loan), [])
        evidence = build_committee_vote_evidence(loan)
        self.assertEqual(evidence['modality'], 'wholesale')
        self.assertEqual(evidence['scorecard']['modality'], 'wholesale')
