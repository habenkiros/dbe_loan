"""CRM / committee pack content for product-desk modalities."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from loans.appraisal_pack import build_committee_appraisal_pack
from loans.crm_pack import build_modality_pack_section, default_crm_send_note, uses_sheet_pack
from loans.models import Branch, CollateralType, District, LoanCategory, LoanRequest, ProjectProfile
from loans.product_family import FAMILY_GENERAL, FAMILY_PROJECT
from loans.project_appraisal import sync_project_decision_to_appraisal


User = get_user_model()


class CrmPackModalityTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='Pack Dist')
        self.branch = Branch.objects.create(name='Pack Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='Pack Coll')
        self.officer = User.objects.create_user(
            username='pack_lo', password='pass', phone_number='0911999001', role='loan_officer',
        )
        self.general = LoanCategory.objects.create(
            name='Pack MSME', appraisal_mode='msme', product_family=FAMILY_GENERAL,
        )
        self.project = LoanCategory.objects.create(
            name='Pack Project', appraisal_mode='corporate', product_family=FAMILY_PROJECT,
        )

    def _loan(self, category, lid='LR-PACK-1', **extra):
        defaults = dict(
            loan_request_id=lid,
            applicant_name='Pack Co',
            phone_number='0911000444',
            amount_requested=Decimal('5000000'),
            reason='Plant',
            category=category,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
        )
        defaults.update(extra)
        return LoanRequest.objects.create(**defaults)

    def test_general_uses_sheet_pack(self):
        loan = self._loan(self.general, lid='LR-PACK-G')
        self.assertTrue(uses_sheet_pack(loan))
        self.assertIsNone(build_modality_pack_section(loan))
        pack = build_committee_appraisal_pack(loan)
        self.assertTrue(pack['sheet_pack'])
        self.assertIsNone(pack['modality_pack'])

    def test_project_modality_pack_and_crm_note(self):
        loan = self._loan(self.project, lid='LR-PACK-P')
        profile = ProjectProfile.objects.create(
            loan_request=loan,
            project_title='Demo Plant',
            total_project_cost=Decimal('7000000'),
            promoter_equity=Decimal('2000000'),
            requested_debt=Decimal('5000000'),
            npv=Decimal('900000'),
            irr_pct=Decimal('18'),
            project_dscr=Decimal('1.4'),
            implementation_months=24,
            grace_months=6,
        )
        sync_project_decision_to_appraisal(
            loan, profile, self.officer,
            recommendation='approve',
            amount_approved=Decimal('5000000'),
            rate_approved=Decimal('14.5'),
            term_approved_months=30,
            recommendation_comment='NPV and DSCR support approval.',
        )
        self.assertFalse(uses_sheet_pack(loan))
        section = build_modality_pack_section(loan)
        self.assertIsNotNone(section)
        self.assertEqual(section['modality'], 'project')
        self.assertTrue(any(r['label'] == 'NPV' for r in section['rows']))
        note = default_crm_send_note(loan)
        self.assertIn('Project appraisal pack', note)
        pack = build_committee_appraisal_pack(loan)
        self.assertFalse(pack['sheet_pack'])
        self.assertEqual(pack['modality_pack']['modality'], 'project')
