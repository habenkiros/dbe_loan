"""Collateral governance and readiness tests."""

from django.core.files.uploadedfile import SimpleUploadedFile
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from collateral.field_utils import collateral_submit_blockers, get_building_readiness
from collateral.governance import collateral_is_locked, gps_is_weak, log_collateral_event
from collateral.models import Building, BuildingImage, CollateralFieldAuditLog
from loans.models import Branch, CollateralType, District, LoanCategory, LoanRequest, Region, Zone, City


User = get_user_model()


class CollateralGovernanceTests(TestCase):
    def setUp(self):
        region = Region.objects.create(name='Addis')
        zone = Zone.objects.create(name='Kirkos', region=region)
        city = City.objects.create(name='Woreda 1', zone=zone)
        district = District.objects.create(name='Central')
        branch = Branch.objects.create(name='Main', district=district)
        collateral = CollateralType.objects.create(name='Building')
        category = LoanCategory.objects.create(name='MSME')
        self.user = User.objects.create_user(username='officer1', password='pass', phone_number='0911000000')
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-GOV-001',
            applicant_name='Test Applicant',
            phone_number='0911000000',
            amount_requested=Decimal('8000'),
            reason='Working capital',
            category=category,
            branch=branch,
            collateral=collateral,
            queue_approved=True,
        )
        self.building = Building.objects.create(
            loan_request=self.loan,
            name='Shop',
            city=city,
            site_gps_lat=Decimal('9.01000000'),
            site_gps_lon=Decimal('38.75000000'),
            site_gps_accuracy_m=Decimal('15'),
        )

    def test_collateral_locked_after_submit(self):
        self.assertFalse(collateral_is_locked(self.loan))
        self.loan.collateral_submitted_at = timezone.now()
        self.loan.save(update_fields=['collateral_submitted_at'])
        self.assertTrue(collateral_is_locked(self.loan))

    def test_gps_is_weak_threshold(self):
        self.assertTrue(gps_is_weak(None))
        self.assertTrue(gps_is_weak(150))
        self.assertFalse(gps_is_weak(50))

    def test_audit_log_created(self):
        log_collateral_event(
            self.loan,
            CollateralFieldAuditLog.EVT_SITE_GPS,
            user=self.user,
            subject_type='Building',
            subject_id=self.building.pk,
            payload={'lat': '9.01'},
        )
        self.assertEqual(CollateralFieldAuditLog.objects.filter(loan_request=self.loan).count(), 1)

    def test_submit_blockers_need_photos(self):
        blockers = collateral_submit_blockers(self.loan)
        self.assertTrue(any('photos' in b.lower() or 'photo' in b.lower() for b in blockers))

    def test_building_ready_with_photos_and_boq(self):
        from collateral.models import BuildingValuation, SubWork, MainWork

        mw = MainWork.objects.create(name='Structure', order=1)
        sw = SubWork.objects.create(name='Foundation', main_work=mw, order=1)
        BuildingValuation.objects.create(
            building=self.building,
            sub_work=sw,
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
        )
        tiny = SimpleUploadedFile('p.jpg', b'fake-image-bytes', content_type='image/jpeg')
        for i in range(5):
            BuildingImage.objects.create(
                building=self.building,
                image=tiny,
                photo_type=BuildingImage.PHOTO_FRONT if i == 0 else BuildingImage.PHOTO_OTHER,
                gps_lat=Decimal('9.01'),
                gps_lon=Decimal('38.75'),
            )
        readiness = get_building_readiness(self.building)
        self.assertTrue(readiness['ready'])

    def test_building_stays_ready_when_collateral_locked(self):
        from collateral.models import BuildingValuation, SubWork, MainWork

        mw = MainWork.objects.create(name='Structure2', order=1)
        sw = SubWork.objects.create(name='Foundation2', main_work=mw, order=1)
        BuildingValuation.objects.create(
            building=self.building,
            sub_work=sw,
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
        )
        tiny = SimpleUploadedFile('p.jpg', b'fake-image-bytes', content_type='image/jpeg')
        for i in range(5):
            BuildingImage.objects.create(
                building=self.building,
                image=tiny,
                photo_type=BuildingImage.PHOTO_FRONT if i == 0 else BuildingImage.PHOTO_OTHER,
                gps_lat=Decimal('9.01'),
                gps_lon=Decimal('38.75'),
            )
        self.loan.collateral_submitted_at = timezone.now()
        self.loan.save(update_fields=['collateral_submitted_at'])
        readiness = get_building_readiness(self.building)
        self.assertTrue(readiness['ready'])
        self.assertTrue(readiness['locked'])
        from collateral.models import BuildingValuation, SubWork, MainWork

        mw = MainWork.objects.create(name='Structure', order=1)
        sw = SubWork.objects.create(name='Foundation', main_work=mw, order=1)
        BuildingValuation.objects.create(
            building=self.building,
            sub_work=sw,
            quantity=Decimal('10'),
            unit_price=Decimal('1000'),
        )
        tiny = SimpleUploadedFile('p.jpg', b'fake-image-bytes', content_type='image/jpeg')
        for i in range(5):
            BuildingImage.objects.create(
                building=self.building,
                image=tiny,
                photo_type=BuildingImage.PHOTO_FRONT if i == 0 else BuildingImage.PHOTO_OTHER,
                gps_lat=Decimal('9.01'),
                gps_lon=Decimal('38.75'),
            )
        self.assertEqual(collateral_submit_blockers(self.loan), [])
