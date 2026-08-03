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

    def test_geocode_prefers_gebeta_when_configured(self):
        from unittest.mock import patch
        from django.test import override_settings
        from collateral import geocoding as geo

        with override_settings(GEBETA_MAPS_API_KEY='test-key', GEBETA_MAPS_GEOCODE_PROVIDER='auto'):
            with patch.object(geo, 'geocode_address_gebeta', return_value=(9.01, 38.75)) as gebeta:
                with patch.object(geo, 'geocode_address_nominatim') as nominatim:
                    coords = geo.geocode_address('Bole, Addis Ababa')
        self.assertEqual(coords, (9.01, 38.75))
        gebeta.assert_called_once()
        nominatim.assert_not_called()

    def test_geocode_falls_back_to_nominatim(self):
        from unittest.mock import patch
        from django.test import override_settings
        from collateral import geocoding as geo

        with override_settings(GEBETA_MAPS_API_KEY='test-key', GEBETA_MAPS_GEOCODE_PROVIDER='auto'):
            with patch.object(geo, 'geocode_address_gebeta', return_value=None):
                with patch.object(geo, 'geocode_address_nominatim', return_value=(8.98, 38.79)) as nominatim:
                    coords = geo.geocode_address('Somewhere Ethiopia')
        self.assertEqual(coords, (8.98, 38.79))
        nominatim.assert_called_once()

    def test_map_tiles_provider_auto_uses_gebeta_when_keyed(self):
        from django.test import override_settings
        from collateral.geocoding import map_provider_context, resolve_map_tiles_provider

        with override_settings(GEBETA_MAPS_API_KEY='test-key', GEBETA_MAPS_TILES_PROVIDER='auto'):
            self.assertEqual(resolve_map_tiles_provider(), 'gebeta')
            ctx = map_provider_context()
            self.assertEqual(ctx['map_tiles_provider'], 'gebeta')
            self.assertTrue(ctx['gebeta_maps_configured'])
            self.assertIn('styles/standard', ctx['gebeta_style_standard'])

        with override_settings(GEBETA_MAPS_API_KEY='', GEBETA_MAPS_TILES_PROVIDER='auto'):
            self.assertEqual(resolve_map_tiles_provider(), 'leaflet_osm')

        with override_settings(GEBETA_MAPS_API_KEY='test-key', GEBETA_MAPS_TILES_PROVIDER='leaflet_osm'):
            self.assertEqual(resolve_map_tiles_provider(), 'leaflet_osm')

        with override_settings(GEBETA_MAPS_API_KEY='', GEBETA_MAPS_TILES_PROVIDER='gebeta'):
            # Forced gebeta without key still falls back — tiles need auth
            self.assertEqual(resolve_map_tiles_provider(), 'leaflet_osm')

    def test_other_item_form_empty_year_saves(self):
        from collateral.forms import OtherCollateralItemForm
        from collateral.models import OtherCollateralItem

        item = OtherCollateralItem(loan_request=self.loan, name='Test Truck', estimated_value=Decimal('100000'))
        form = OtherCollateralItemForm(
            {'name': 'Test Truck', 'estimated_value': '100000', 'year_made': ''},
            instance=item,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data['year_made'])

    def test_other_item_ready_without_site_gps(self):
        from collateral.models import OtherCollateralItem, OtherCollateralItemImage
        from collateral.field_utils import get_other_item_readiness
        from django.core.files.uploadedfile import SimpleUploadedFile

        vehicle = OtherCollateralItem.objects.create(
            loan_request=self.loan,
            name='Toyota Pickup',
            make_model='Toyota Hilux',
            plate_number='AA-12345',
            estimated_value=Decimal('400000'),
        )
        for i, ptype in enumerate(('plate', 'asset', 'serial_label')):
            OtherCollateralItemImage.objects.create(
                item=vehicle,
                image=SimpleUploadedFile(f'p{i}.jpg', b'fake-image-bytes', content_type='image/jpeg'),
                photo_type=ptype,
                gps_lat=Decimal('9.01'),
                gps_lon=Decimal('38.75'),
            )
        readiness = get_other_item_readiness(vehicle)
        self.assertTrue(readiness['ready'])
        self.assertFalse(vehicle.site_gps_lat)

    def test_pending_qa_blocks_officer_unlock_request(self):
        from collateral.views import _can_request_collateral_unlock, _can_review_collateral_unlock

        self.loan.collateral_submitted_at = timezone.now()
        self.loan.collateral_submitted_by = self.officer
        self.loan.collateral_engineering_status = LoanRequest.ENG_COLLATERAL_PENDING
        self.loan.save()
        self.assertFalse(_can_request_collateral_unlock(self.officer, self.loan))
        self.assertFalse(_can_request_collateral_unlock(self.engineer, self.loan))
        eng_head = User.objects.create_user(
            username='enghead2', password='pass', phone_number='0911000012', role='engineering_head',
        )
        self.assertTrue(_can_review_collateral_unlock(eng_head, self.loan))
        bm = User.objects.create_user(
            username='bm2', password='pass', phone_number='0911000013',
            role='branch_manager', branch=self.loan.branch,
        )
        self.assertFalse(_can_review_collateral_unlock(bm, self.loan))

    def test_engineering_head_can_open_other_field_visit_for_qa(self):
        """QA review links must not 404 when loan was never 'sent to engineering'."""
        from django.test import Client
        from django.urls import reverse
        from collateral.models import OtherCollateralItem
        from collateral.views import _user_can_access_loan_collateral

        eng_head = User.objects.create_user(
            username='enghead_qa', password='pass', phone_number='0911000099', role='engineering_head',
        )
        item = OtherCollateralItem.objects.create(
            loan_request=self.loan,
            name='Sample movable asset',
            estimated_value=Decimal('100000'),
        )
        self.loan.collateral_submitted_at = timezone.now()
        self.loan.collateral_submitted_by = self.officer
        self.loan.collateral_engineering_status = LoanRequest.ENG_COLLATERAL_PENDING
        self.loan.sent_to_engineering_at = None
        self.loan.save()
        self.assertTrue(_user_can_access_loan_collateral(eng_head, self.loan))
        client = Client()
        self.assertTrue(client.login(username='enghead_qa', password='pass'))
        res = client.get(reverse('collateral:other_field_visit', args=[item.pk]))
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertContains(res, 'Sample movable asset')

    def test_summary_shows_return_note_after_engineering_return(self):
        from django.template.loader import render_to_string
        from collateral.pipeline import collateral_pipeline_stage, pipeline_stage_label

        self.loan.collateral_engineering_status = LoanRequest.ENG_COLLATERAL_RETURNED
        self.loan.collateral_engineering_return_note = 'Add clearer front facade photos.'
        self.loan.collateral_submitted_at = None
        self.loan.collateral_submitted_by = None
        self.loan.save()

        # Template-level check (LO visibility depends on estimation mode config).
        html = render_to_string('collateral/summary.html', {
            'loan_request': self.loan,
            'collateral_type_lower': 'building',
            'grand_total': Decimal('0'),
            'coverage': {},
            'can_submit_collateral': True,
            'submit_blockers': [],
            'loan_readiness': {'applies': False},
            'min_images_per_building': 3,
            'buildings_below_image_min': [],
            'can_request_unlock': False,
            'pending_unlock': None,
            'pipeline_stage': collateral_pipeline_stage(self.loan),
            'pipeline_label': pipeline_stage_label(collateral_pipeline_stage(self.loan)),
        })
        self.assertIn('Returned for correction by engineering', html)
        self.assertIn('Add clearer front facade photos.', html)
        self.assertIn('Resubmit collateral', html)
        self.assertIn('What to fix:', html)
