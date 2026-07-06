"""Tier 2 tests: pipeline, engineering QA, movable fields, geocoding helpers."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from collateral.engineering_qa import can_review_engineering, initial_engineering_status
from collateral.geocoding import declared_address_for_loan
from collateral.pipeline import collateral_pipeline_stage
from loans.models import (
    Branch, CollateralEstimationConfig, CollateralType, District, LoanCategory,
    LoanRequest, LoanRequestBasicInfo, Region, Zone, City,
)


User = get_user_model()


class CollateralTier2Tests(TestCase):
    def setUp(self):
        region = Region.objects.create(name='Addis')
        zone = Zone.objects.create(name='Kirkos', region=region)
        city = City.objects.create(name='Woreda 1', zone=zone)
        district = District.objects.create(name='Central')
        branch = Branch.objects.create(name='Main', district=district)
        collateral = CollateralType.objects.create(name='Building')
        category = LoanCategory.objects.create(name='MSME')
        self.officer = User.objects.create_user(
            username='officer2', password='pass', phone_number='0911000010', role='loan_officer',
        )
        self.engineer = User.objects.create_user(
            username='eng2', password='pass', phone_number='0911000011', role='engineer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-T2-001',
            applicant_name='Test Applicant',
            phone_number='0911000000',
            amount_requested=Decimal('8000'),
            reason='Working capital',
            category=category,
            branch=branch,
            collateral=collateral,
            queue_approved=True,
            assigned_loan_officer=self.officer,
            assigned_engineer=self.engineer,
        )
        LoanRequestBasicInfo.objects.create(
            loan_request=self.loan,
            business_address='Bole Road, Addis Ababa',
        )
        CollateralEstimationConfig.objects.all().delete()
        CollateralEstimationConfig.objects.create(mode=CollateralEstimationConfig.MODE_ENGINEERING_TEAM)

    def test_initial_engineering_status_pending_for_officer(self):
        status = initial_engineering_status(self.officer)
        self.assertEqual(status, LoanRequest.ENG_COLLATERAL_PENDING)

    def test_pipeline_stage_submitted(self):
        self.loan.collateral_submitted_at = timezone.now()
        self.loan.collateral_engineering_status = LoanRequest.ENG_COLLATERAL_PENDING
        self.loan.save()
        self.assertEqual(collateral_pipeline_stage(self.loan), 'engineering_pending')

    def test_declared_address_from_basic_info(self):
        self.assertEqual(declared_address_for_loan(self.loan), 'Bole Road, Addis Ababa')

    def test_engineer_can_review_pending(self):
        self.loan.collateral_submitted_at = timezone.now()
        self.loan.collateral_engineering_status = LoanRequest.ENG_COLLATERAL_PENDING
        self.loan.save()
        self.assertTrue(can_review_engineering(self.engineer, self.loan))
