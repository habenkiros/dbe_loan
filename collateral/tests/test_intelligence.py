"""Assistive collateral intelligence — never auto-values."""

from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from PIL import Image

from collateral.intelligence import (
    build_collateral_risk_brief,
    find_collateral_duplicates,
    gps_confidence_for_site,
    hash_image_bytes,
    market_outlier_flags,
    suggest_photo_type,
)
from collateral.models import Building, BuildingImage, BuildingValuation, LandValuation, MainWork, SubWork
from loans.models import Branch, City, CollateralType, District, LoanCategory, LoanRequest, Region, Zone
from partners.models import MarketObservation, MarketPriceBand


User = get_user_model()


def _jpeg_bytes(color=(180, 90, 40), size=(64, 64)) -> bytes:
    buf = BytesIO()
    Image.new('RGB', size, color).save(buf, format='JPEG')
    return buf.getvalue()


class CollateralIntelligenceTests(TestCase):
    def setUp(self):
        region = Region.objects.create(name='Intel R')
        zone = Zone.objects.create(name='Intel Z', region=region)
        self.city = City.objects.create(name='Intel City', zone=zone)
        district = District.objects.create(name='Intel D')
        self.branch = Branch.objects.create(name='Intel Branch', district=district)
        self.building_type = CollateralType.objects.create(name='Building Intel')
        self.msme = LoanCategory.objects.create(name='MSME Intel')
        self.officer = User.objects.create_user(
            username='officer_intel', password='pass', phone_number='0911888001',
            role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-INTEL-001',
            applicant_name='Intel Borrower',
            phone_number='0911888000',
            amount_requested=Decimal('500000'),
            reason='Working capital',
            category=self.msme,
            branch=self.branch,
            collateral=self.building_type,
            queue_approved=True,
            operation_manager_approval=True,
            assigned_loan_officer=self.officer,
        )
        self.loan_b = LoanRequest.objects.create(
            loan_request_id='LR-INTEL-002',
            applicant_name='Other Borrower',
            phone_number='0911888002',
            amount_requested=Decimal('400000'),
            reason='WC',
            category=self.msme,
            branch=self.branch,
            collateral=self.building_type,
            queue_approved=True,
            operation_manager_approval=True,
            assigned_loan_officer=self.officer,
        )

    def test_suggest_photo_type_keyword_and_missing(self):
        hit = suggest_photo_type(kind='building', filename='front_elevation.jpg')
        self.assertEqual(hit['key'], 'front')
        miss = suggest_photo_type(kind='land', missing_types=['plot', 'boundary'])
        self.assertEqual(miss['key'], 'plot')
        self.assertIsNone(suggest_photo_type(kind='building'))

    def test_gps_confidence_manual_vs_device(self):
        building = Building.objects.create(
            loan_request=self.loan, name='Shop', city=self.city,
            site_gps_lat=Decimal('9.0100'), site_gps_lon=Decimal('38.7500'),
            site_gps_source='device', site_gps_accuracy_m=Decimal('12'),
        )
        device = gps_confidence_for_site(building, [])
        self.assertEqual(device['band'], 'high')
        self.assertGreaterEqual(device['score'], 75)

        building.site_gps_source = 'manual'
        building.site_gps_accuracy_m = None
        building.save(update_fields=['site_gps_source', 'site_gps_accuracy_m'])
        manual = gps_confidence_for_site(building, [])
        self.assertLess(manual['score'], device['score'])
        self.assertIn('manual_coordinates', manual['reasons'])

        bare = Building.objects.create(loan_request=self.loan, name='No GPS', city=self.city)
        none = gps_confidence_for_site(bare, [])
        self.assertEqual(none['score'], 0)
        self.assertEqual(none['band'], 'none')

    def test_hash_and_cross_loan_duplicate(self):
        raw = _jpeg_bytes()
        sha, phash = hash_image_bytes(raw, 'a.jpg')
        self.assertEqual(len(sha), 64)
        self.assertTrue(phash)

        b1 = Building.objects.create(loan_request=self.loan, name='A', city=self.city)
        b2 = Building.objects.create(loan_request=self.loan_b, name='B', city=self.city)
        upload = SimpleUploadedFile('a.jpg', raw, content_type='image/jpeg')
        BuildingImage.objects.create(
            building=b1, image=upload, photo_type='front',
            content_sha256=sha, perceptual_hash=phash,
        )
        dups = find_collateral_duplicates(
            content_sha256=sha, perceptual_hash=phash, exclude_loan_id=self.loan_b.pk,
        )
        self.assertTrue(dups)
        self.assertEqual(dups[0]['match'], 'exact')
        self.assertEqual(dups[0]['loan_request_id'], 'LR-INTEL-001')
        self.assertTrue(Building.objects.filter(pk=b2.pk).exists())

    def test_market_outlier_boq_flag(self):
        mw = MainWork.objects.create(name='Intel Structure', order=1)
        sw = SubWork.objects.create(name='Intel Foundation', main_work=mw, order=1)
        building = Building.objects.create(
            loan_request=self.loan, name='Outlier shop', city=self.city,
        )
        BuildingValuation.objects.create(
            building=building, sub_work=sw, quantity=Decimal('10'),
            unit_price=Decimal('50000'),
        )
        MarketPriceBand.objects.create(
            city=self.city,
            asset_class=MarketObservation.ASSET_BUILDING,
            sub_work=sw,
            unit='m2',
            sample_count=5,
            median_price=Decimal('1000'),
            p25_price=Decimal('800'),
            p75_price=Decimal('1200'),
            last_observed_at=timezone.localdate(),
        )
        flags = market_outlier_flags(self.loan)
        self.assertTrue(any(f['key'] == 'boq_outlier' for f in flags))
        self.assertEqual(flags[0]['level'], 'block')

    def test_risk_brief_assistive_shape(self):
        building = Building.objects.create(
            loan_request=self.loan, name='Brief shop', city=self.city,
            site_gps_lat=Decimal('9.01'), site_gps_lon=Decimal('38.75'),
            site_gps_source='device', site_gps_accuracy_m=Decimal('8'),
        )
        LandValuation.objects.create(
            loan_request=self.loan,
            land_size_sqm=Decimal('100'),
            unit_price_per_sqm=Decimal('500'),
        )
        brief = build_collateral_risk_brief(self.loan)
        self.assertTrue(brief['assistive_only'])
        self.assertIn(brief['overall'], ('clear', 'watch', 'elevated'))
        self.assertIsNotNone(brief['gps'])
        self.assertIn('market_outliers', brief)
        self.assertIn('duplicates', brief)
        self.assertEqual(building.name, 'Brief shop')
