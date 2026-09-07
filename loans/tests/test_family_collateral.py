"""Product family locks appraisal desk and allowed security types."""

from django.test import TestCase

from loans.appraisal_mode import locked_appraisal_mode
from loans.collateral_kind import KIND_FINANCED, KIND_LAND, is_financed_asset
from loans.collateral_policy import (
    ensure_financed_collateral_types,
    family_restricts_collateral,
    kinds_for_family,
)
from loans.models import CollateralType, LoanCategory
from loans.product_family import FAMILY_GENERAL, FAMILY_LEASE, FAMILY_PROJECT, FAMILY_WHOLESALE
from loans.registration import collateral_for_category, collateral_required


class FamilyAppraisalLockTests(TestCase):
    def test_lease_msme_default_becomes_lease_desk(self):
        lease = LoanCategory.objects.create(
            name='Lock Lease', appraisal_mode='msme', product_family=FAMILY_LEASE,
        )
        lease.refresh_from_db()
        self.assertEqual(lease.appraisal_mode, FAMILY_LEASE)
        self.assertEqual(locked_appraisal_mode(FAMILY_LEASE), FAMILY_LEASE)

    def test_explicit_appraisal_override_is_kept(self):
        project = LoanCategory.objects.create(
            name='Lock Project', appraisal_mode='corporate', product_family=FAMILY_PROJECT,
        )
        project.refresh_from_db()
        self.assertEqual(project.appraisal_mode, 'corporate')

    def test_form_selecting_family_fills_appraisal_and_can_skip_collateral(self):
        from loans.forms import LoanCategoryForm

        form = LoanCategoryForm(data={
            'name': 'Form Lease',
            'product_family': FAMILY_LEASE,
            'appraisal_mode': 'msme',
            'requires_collateral': 'on',
        })
        self.assertTrue(form.is_valid(), form.errors)
        cat = form.save()
        self.assertEqual(cat.appraisal_mode, FAMILY_LEASE)
        self.assertTrue(cat.requires_collateral)

        form2 = LoanCategoryForm(data={
            'name': 'Form Wholesale',
            'product_family': FAMILY_WHOLESALE,
            'appraisal_mode': 'msme',
        })
        self.assertTrue(form2.is_valid(), form2.errors)
        cat2 = form2.save()
        self.assertEqual(cat2.appraisal_mode, FAMILY_WHOLESALE)
        self.assertFalse(cat2.requires_collateral)
        self.assertFalse(collateral_required(cat2))

    def test_form_keeps_explicit_appraisal_override(self):
        from loans.forms import LoanCategoryForm

        form = LoanCategoryForm(data={
            'name': 'Form Project Corporate',
            'product_family': FAMILY_PROJECT,
            'appraisal_mode': 'corporate',
            'requires_collateral': 'on',
        })
        self.assertTrue(form.is_valid(), form.errors)
        cat = form.save()
        self.assertEqual(cat.appraisal_mode, 'corporate')

    def test_wholesale_family_default_is_unsecured(self):
        self.assertFalse(collateral_required(FAMILY_WHOLESALE))
        wholesale = LoanCategory.objects.create(
            name='Inherit Wholesale', product_family=FAMILY_WHOLESALE,
        )
        self.assertIsNone(wholesale.requires_collateral)
        self.assertFalse(wholesale.needs_collateral)
        self.assertFalse(collateral_required(wholesale))
        from loans.registration import category_family_payload
        payload = category_family_payload([wholesale])[0]
        self.assertFalse(payload['needs_collateral'])
        self.assertEqual(payload['collateral_ids'], [])

    def test_general_still_allows_msme_or_corporate(self):
        self.assertIsNone(locked_appraisal_mode(FAMILY_GENERAL))
        cat = LoanCategory.objects.create(
            name='Lock MSME', appraisal_mode='corporate', product_family=FAMILY_GENERAL,
        )
        cat.refresh_from_db()
        self.assertEqual(cat.appraisal_mode, 'corporate')


class FamilyCollateralPolicyTests(TestCase):
    def setUp(self):
        self.land = CollateralType.objects.create(name='Pol Land', kind=KIND_LAND)
        ensure_financed_collateral_types()
        self.financed = CollateralType.objects.get(
            name='Financed machinery / plant (from this loan)',
        )

    def test_lease_default_is_financed_asset_not_land(self):
        lease = LoanCategory.objects.create(
            name='Pol Lease', product_family=FAMILY_LEASE,
        )
        ids = set(collateral_for_category(lease).values_list('id', flat=True))
        self.assertNotIn(self.land.id, ids)
        self.assertIn(self.financed.id, ids)
        self.assertTrue(is_financed_asset(self.financed))
        self.assertEqual(kinds_for_family(FAMILY_LEASE), (KIND_FINANCED,))

    def test_project_allows_site_and_financed_plant(self):
        project = LoanCategory.objects.create(
            name='Pol Project', product_family=FAMILY_PROJECT,
        )
        ids = set(collateral_for_category(project).values_list('id', flat=True))
        self.assertIn(self.land.id, ids)
        self.assertIn(self.financed.id, ids)

    def test_category_can_turn_collateral_off(self):
        project = LoanCategory.objects.create(
            name='Unsecured Project', product_family=FAMILY_PROJECT,
            requires_collateral=False,
        )
        self.assertFalse(collateral_required(project))
        self.assertFalse(collateral_for_category(project).exists())

    def test_general_empty_m2m_still_any_type(self):
        general = LoanCategory.objects.create(
            name='Pol General', product_family=FAMILY_GENERAL, appraisal_mode='msme',
        )
        ids = set(collateral_for_category(general).values_list('id', flat=True))
        self.assertIn(self.land.id, ids)
        self.assertIn(self.financed.id, ids)


class FamilyPolicyPayloadTests(TestCase):
    def test_lease_payload_has_desk_and_financed_collateral(self):
        from loans.family_policy import ensure_family_policies, policy_payload

        ensure_financed_collateral_types()
        ensure_family_policies()
        data = policy_payload(FAMILY_LEASE)
        self.assertEqual(data['appraisal_mode'], FAMILY_LEASE)
        self.assertTrue(data['requires_collateral'])
        self.assertTrue(data['collaterals'])

    def test_wholesale_payload_is_unsecured(self):
        from loans.family_policy import ensure_family_policies, policy_payload

        ensure_family_policies()
        data = policy_payload(FAMILY_WHOLESALE)
        self.assertEqual(data['appraisal_mode'], FAMILY_WHOLESALE)
        self.assertFalse(data['requires_collateral'])
        self.assertEqual(data['collaterals'], [])
