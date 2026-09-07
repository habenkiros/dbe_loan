"""DBE prototyping desks: same spine, product-specific appraisal, wholesale as PFI."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from loans.dbe_desks import (
    DESK_APPRAISAL,
    DESK_CRM,
    DESK_CREDIT,
    DESK_ENGINEERING,
    DESK_EXTERNAL_FUND,
    DESK_HRM,
    DESK_LEGAL,
    MECH_LEASE,
    MECH_PROJECT,
    MECH_SHEETS,
    MECH_WHOLESALE,
    appraisal_mechanism,
    intake_desk,
    stage_owners,
    uses_decsi_sheets,
)
from loans.engines import get_engine
from loans.models import Branch, CollateralType, Department, District, LoanCategory, LoanRequest
from loans.product_family import (
    FAMILY_CONSUMER,
    FAMILY_GENERAL,
    FAMILY_LEASE,
    FAMILY_PROJECT,
    FAMILY_WHOLESALE,
)


User = get_user_model()


class DbeDeskCatalogTests(TestCase):
    def test_project_and_lease_are_not_decsi_sheets(self):
        self.assertEqual(appraisal_mechanism(FAMILY_PROJECT), MECH_PROJECT)
        self.assertEqual(appraisal_mechanism(FAMILY_LEASE), MECH_LEASE)
        self.assertFalse(uses_decsi_sheets(FAMILY_PROJECT))
        self.assertFalse(uses_decsi_sheets(FAMILY_LEASE))
        self.assertTrue(uses_decsi_sheets(FAMILY_GENERAL))

    def test_wholesale_is_pfi_desk_not_sheets(self):
        self.assertEqual(appraisal_mechanism(FAMILY_WHOLESALE), MECH_WHOLESALE)
        self.assertEqual(intake_desk(FAMILY_WHOLESALE), DESK_EXTERNAL_FUND)
        self.assertFalse(uses_decsi_sheets(FAMILY_WHOLESALE))

    def test_pdf_intake_desks(self):
        self.assertEqual(intake_desk(FAMILY_PROJECT), DESK_CRM)
        self.assertEqual(intake_desk(FAMILY_LEASE), DESK_CRM)
        self.assertEqual(intake_desk(FAMILY_CONSUMER), DESK_HRM)
        self.assertEqual(intake_desk(FAMILY_GENERAL), DESK_CREDIT)

    def test_kyc_is_parallel_crm_engineering_legal(self):
        self.assertEqual(
            stage_owners('kyc'),
            (DESK_CRM, DESK_ENGINEERING, DESK_LEGAL),
        )

    def test_appraisal_stage_includes_crm_feedback(self):
        self.assertEqual(
            stage_owners('appraisal'),
            (DESK_APPRAISAL, DESK_ENGINEERING, DESK_CRM),
        )

    def test_committees_are_not_departments(self):
        self.assertEqual(stage_owners('review'), ())
        self.assertEqual(stage_owners('approval'), ())


class DbeDeskEngineTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='Desk Dist')
        self.branch = Branch.objects.create(name='Desk Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='Desk Coll')
        self.officer = User.objects.create_user(
            username='desk_lo', password='pass', phone_number='0911222001', role='loan_officer',
        )

    def _loan(self, family, rid):
        cat = LoanCategory.objects.create(
            name=f'{family} cat', product_family=family, appraisal_mode=family,
        )
        return LoanRequest.objects.create(
            loan_request_id=rid,
            applicant_name='Desk Co',
            phone_number='0911000111',
            amount_requested=Decimal('1000000'),
            reason='file',
            category=cat,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
        )

    def test_engines_skip_seven_sheet_for_project_lease_wholesale(self):
        for family, rid, desk in (
            (FAMILY_PROJECT, 'LR-DESK-P', DESK_CRM),
            (FAMILY_LEASE, 'LR-DESK-L', DESK_CRM),
            (FAMILY_WHOLESALE, 'LR-DESK-W', DESK_EXTERNAL_FUND),
        ):
            loan = self._loan(family, rid)
            engine = get_engine(loan)
            self.assertFalse(engine.requires_appraisal_sheets(), family)
            self.assertEqual(appraisal_mechanism(loan), family)
            self.assertEqual(intake_desk(loan), desk)

    def test_dbe_desks_are_seedable_keys(self):
        from loans.dbe_desks import DBE_DESK_SEED

        keys = {k for k, _ in Department.KEY_CHOICES}
        for key, name, order in DBE_DESK_SEED:
            self.assertIn(key, keys)
            Department.objects.get_or_create(
                key=key, defaults={'name': name, 'sort_order': order, 'is_active': True},
            )
        self.assertTrue(Department.objects.filter(key='crm').exists())
        self.assertTrue(Department.objects.filter(key='external_fund').exists())


class DirectorateInboxTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='dir_admin', password='pass', phone_number='0911222111',
            role='admin', is_staff=True,
        )
        self.officer = User.objects.create_user(
            username='dir_lo', password='pass', phone_number='0911222112',
            role='loan_officer',
        )

    def test_admin_opens_appraisal_its_mis(self):
        from django.urls import reverse

        self.client.force_login(self.admin)
        for name, needle in (
            ('appraisal_desk', 'Appraisal Directorate'),
            ('its_desk', 'ITS Directorate'),
            ('mis_desk', 'PM & MIS'),
        ):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 200, name)
            self.assertContains(resp, needle)

    def test_officer_opens_appraisal_not_its(self):
        from django.urls import reverse

        self.client.force_login(self.officer)
        self.assertEqual(self.client.get(reverse('appraisal_desk')).status_code, 200)
        self.assertEqual(self.client.get(reverse('its_desk')).status_code, 302)


