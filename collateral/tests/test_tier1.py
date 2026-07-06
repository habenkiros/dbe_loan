"""Tier 1: coverage, policy config, unlock workflow."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from collateral.coverage import compute_coverage_adequacy
from collateral.evidence_pack import build_collateral_evidence_pack
from collateral.governance import collateral_is_locked
from collateral.models import (
    Building, BuildingValuation, CollateralPolicyConfig, CollateralUnlockRequest,
    MainWork, SubWork,
)
from collateral.policy import clear_policy_cache, get_collateral_policy
from collateral.views import _can_request_collateral_unlock, _can_review_collateral_unlock
from loans.models import Branch, CollateralType, District, LoanCategory, LoanRequest, Region, Zone, City


User = get_user_model()


class CollateralTier1Tests(TestCase):
    def setUp(self):
        region = Region.objects.create(name='Addis')
        zone = Zone.objects.create(name='Kirkos', region=region)
        city = City.objects.create(name='Woreda 1', zone=zone)
        district = District.objects.create(name='Central')
        self.branch = Branch.objects.create(name='Main', district=district)
        collateral = CollateralType.objects.create(name='Building')
        category = LoanCategory.objects.create(name='MSME')
        self.officer = User.objects.create_user(
            username='officer1', password='pass', phone_number='0911000001', role='loan_officer',
        )
        self.manager = User.objects.create_user(
            username='bm1', password='pass', phone_number='0911000002',
            role='branch_manager', branch=self.branch,
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-T1-001',
            applicant_name='Test Applicant',
            phone_number='0911000000',
            amount_requested=Decimal('500000'),
            reason='Working capital',
            category=category,
            branch=self.branch,
            collateral=collateral,
            queue_approved=True,
            assigned_loan_officer=self.officer,
        )
        self.building = Building.objects.create(
            loan_request=self.loan,
            name='Shop',
            city=city,
            site_gps_lat=Decimal('9.01000000'),
            site_gps_lon=Decimal('38.75000000'),
        )
        mw = MainWork.objects.create(name='Structure', order=1)
        sw = SubWork.objects.create(name='Foundation', main_work=mw, order=1)
        BuildingValuation.objects.create(
            building=self.building,
            sub_work=sw,
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
        )

    def test_coverage_blocks_when_below_policy_minimum(self):
        coverage = compute_coverage_adequacy(self.loan)
        self.assertLess(coverage['coverage_ratio'], Decimal('1'))
        self.assertFalse(coverage['adequate_for_submit'])
        self.assertTrue(any(f['key'] == 'coverage_below_min' for f in coverage['flags']))

    def test_policy_config_refreshes_cache(self):
        clear_policy_cache()
        config, _ = CollateralPolicyConfig.objects.get_or_create()
        config.min_images_per_building = 7
        config.save()
        policy = get_collateral_policy(refresh=True)
        self.assertEqual(policy.min_images_per_building, 7)

    def test_unlock_request_and_approve_clears_submit_lock(self):
        self.loan.collateral_submitted_at = timezone.now()
        self.loan.collateral_submitted_by = self.officer
        self.loan.save(update_fields=['collateral_submitted_at', 'collateral_submitted_by'])
        self.assertTrue(collateral_is_locked(self.loan))

        self.assertTrue(_can_request_collateral_unlock(self.officer, self.loan))
        self.assertTrue(_can_review_collateral_unlock(self.manager, self.loan))

        unlock = CollateralUnlockRequest.objects.create(
            loan_request=self.loan,
            requested_by=self.officer,
            reason='Correct BOQ quantities after site re-measurement.',
            previous_submitted_at=self.loan.collateral_submitted_at,
            previous_submitted_by=self.officer,
        )
        self.assertFalse(_can_request_collateral_unlock(self.officer, self.loan))

        unlock.status = CollateralUnlockRequest.STATUS_APPROVED
        unlock.reviewed_by = self.manager
        unlock.reviewed_at = timezone.now()
        unlock.save()
        self.loan.collateral_submitted_at = None
        self.loan.collateral_submitted_by = None
        self.loan.save(update_fields=['collateral_submitted_at', 'collateral_submitted_by'])

        self.loan.refresh_from_db()
        self.assertFalse(collateral_is_locked(self.loan))
        self.assertFalse(_can_request_collateral_unlock(self.officer, self.loan))

    def test_evidence_pack_includes_coverage_and_building_data(self):
        pack = build_collateral_evidence_pack(self.loan)
        self.assertEqual(pack['loan_request'].pk, self.loan.pk)
        self.assertIn('coverage', pack)
        self.assertEqual(len(pack['buildings_data']), 1)
        self.assertEqual(pack['buildings_data'][0]['total'], Decimal('10000'))
