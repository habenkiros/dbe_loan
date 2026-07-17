"""Tier 3: dossier export, required movable photo types, EXIF helpers."""

from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from collateral.dossier import build_collateral_dossier, dossier_json_bytes, dossier_zip_bytes
from collateral.exif_gps import extract_exif_gps
from collateral.field_utils import get_other_item_readiness
from collateral.models import OtherCollateralItem, OtherCollateralItemImage
from collateral.policy import clear_policy_cache
from loans.models import (
    Branch, CollateralEstimationConfig, CollateralType, District, LoanCategory,
    LoanRequest, Region, Zone, City,
)


User = get_user_model()


def _tiny_jpeg():
    buf = BytesIO()
    Image.new('RGB', (10, 10), color=(80, 80, 80)).save(buf, format='JPEG')
    return buf.getvalue()


class CollateralTier3Tests(TestCase):
    def setUp(self):
        region = Region.objects.create(name='Addis')
        zone = Zone.objects.create(name='Kirkos', region=region)
        City.objects.create(name='Woreda 1', zone=zone)
        district = District.objects.create(name='Central')
        branch = Branch.objects.create(name='Main', district=district)
        collateral = CollateralType.objects.create(name='Vehicle')
        category = LoanCategory.objects.create(name='MSME')
        self.officer = User.objects.create_user(
            username='officer3', password='pass', phone_number='0911000020', role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-T3-001',
            applicant_name='Vehicle Applicant',
            phone_number='0911000000',
            amount_requested=Decimal('100000'),
            reason='Working capital',
            category=category,
            branch=branch,
            collateral=collateral,
            queue_approved=True,
            assigned_loan_officer=self.officer,
        )
        CollateralEstimationConfig.objects.all().delete()
        CollateralEstimationConfig.objects.create(mode=CollateralEstimationConfig.MODE_LOAN_OFFICER)
        clear_policy_cache()
        self.item = OtherCollateralItem.objects.create(
            loan_request=self.loan,
            name='Toyota Hilux',
            estimated_value=Decimal('250000'),
            plate_number='AA-99',
        )

    def test_required_photo_types_block_readiness(self):
        for i in range(3):
            OtherCollateralItemImage.objects.create(
                item=self.item,
                image=SimpleUploadedFile(f'p{i}.jpg', _tiny_jpeg(), content_type='image/jpeg'),
                photo_type=OtherCollateralItemImage.PHOTO_OTHER,
            )
        readiness = get_other_item_readiness(self.item)
        self.assertFalse(readiness['ready'])
        self.assertTrue(readiness['missing_photo_types'])

    def test_required_photo_types_complete(self):
        for i, ptype in enumerate((
            OtherCollateralItemImage.PHOTO_PLATE,
            OtherCollateralItemImage.PHOTO_ASSET,
            OtherCollateralItemImage.PHOTO_SERIAL,
        )):
            OtherCollateralItemImage.objects.create(
                item=self.item,
                image=SimpleUploadedFile(f'r{i}.jpg', _tiny_jpeg(), content_type='image/jpeg'),
                photo_type=ptype,
            )
        readiness = get_other_item_readiness(self.item)
        self.assertTrue(readiness['ready'])
        self.assertEqual(readiness['missing_photo_types'], [])

    def test_dossier_json_and_zip(self):
        dossier = build_collateral_dossier(self.loan)
        self.assertEqual(dossier['schema_version'], '1.0')
        self.assertEqual(dossier['loan']['loan_request_id'], 'LR-T3-001')
        self.assertEqual(len(dossier['other_items']), 1)
        raw = dossier_json_bytes(self.loan)
        self.assertIn(b'LR-T3-001', raw)
        zbytes = dossier_zip_bytes(self.loan)
        self.assertTrue(zbytes[:2] == b'PK')

    def test_extract_exif_gps_none_on_plain_jpeg(self):
        self.assertIsNone(extract_exif_gps(BytesIO(_tiny_jpeg())))
