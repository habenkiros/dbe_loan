"""Offline PWA scaffold: SW, bundle, sync API."""

import base64
import json
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from PIL import Image

from collateral.models import Building, BuildingImage, LandValuation
from collateral.policy import clear_policy_cache
from loans.models import (
    Branch, CollateralEstimationConfig, CollateralType, District, LoanCategory,
    LoanRequest, Region, Zone, City,
)


User = get_user_model()


def _tiny_jpeg_b64():
    buf = BytesIO()
    Image.new('RGB', (12, 12), color=(40, 120, 40)).save(buf, format='JPEG')
    return base64.b64encode(buf.getvalue()).decode('ascii')


class CollateralOfflineTests(TestCase):
    def setUp(self):
        region = Region.objects.create(name='Tigray')
        zone = Zone.objects.create(name='Mekelle', region=region)
        self.city = City.objects.create(name='Hawelti', zone=zone)
        district = District.objects.create(name='Central')
        branch = Branch.objects.create(name='Main', district=district)
        collateral = CollateralType.objects.create(name='Building')
        category = LoanCategory.objects.create(name='MSME')
        self.officer = User.objects.create_user(
            username='officer_off', password='pass', phone_number='0911000099', role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-OFF-001',
            applicant_name='Offline Applicant',
            phone_number='0911000000',
            amount_requested=Decimal('200000'),
            reason='Working capital',
            category=category,
            branch=branch,
            collateral=collateral,
            operation_manager_approval=True,
            finance_approval=True,
            queue_approved=True,
            assigned_loan_officer=self.officer,
        )
        CollateralEstimationConfig.objects.all().delete()
        CollateralEstimationConfig.objects.create(mode=CollateralEstimationConfig.MODE_LOAN_OFFICER)
        clear_policy_cache()
        self.building = Building.objects.create(
            loan_request=self.loan,
            name='Site House',
            construction_type='RC',
            floors=1,
            city=self.city,
        )
        self.client = Client()
        self.client.login(username='officer_off', password='pass')

    def test_service_worker_served_under_collateral(self):
        url = reverse('collateral:offline_sw')
        self.assertEqual(url, '/collateral/sw.js')
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertIn('application/javascript', res['Content-Type'])
        self.assertEqual(res['Service-Worker-Allowed'], '/collateral/')
        self.assertIn(b'collateral-field-v1', res.content)

    def test_offline_manifest(self):
        res = self.client.get(reverse('collateral:offline_manifest'))
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Collateral Field', res.content)

    def test_field_checklist_page(self):
        url = reverse('collateral:field_checklist')
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Tablet field checklist')
        self.assertContains(res, 'gen_field_https_certs')

    def test_loan_bundle(self):
        url = reverse('collateral:offline_bundle', args=[self.loan.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['bundle']['loan_request_code'], 'LR-OFF-001')
        self.assertEqual(len(data['bundle']['buildings']), 1)
        self.assertEqual(data['bundle']['buildings'][0]['name'], 'Site House')

    def test_sync_building_site_gps(self):
        url = reverse('collateral:offline_sync')
        payload = {
            'kind': 'building_site',
            'loan_request_id': self.loan.pk,
            'visit_kind': 'building',
            'subject_id': self.building.pk,
            'fields': {
                'name': 'Site House Updated',
                'construction_type': 'RC',
                'floors': '2',
                'city': str(self.city.pk),
                'site_gps_lat': '13.496900',
                'site_gps_lon': '39.476900',
                'site_gps_accuracy_m': '12',
            },
        }
        res = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertTrue(data['ok'], data)
        self.building.refresh_from_db()
        self.assertEqual(self.building.name, 'Site House Updated')
        self.assertEqual(self.building.floors, 2)
        self.assertIsNotNone(self.building.site_gps_lat)

    def test_sync_photo(self):
        url = reverse('collateral:offline_sync')
        payload = {
            'kind': 'photo',
            'loan_request_id': self.loan.pk,
            'visit_kind': 'building',
            'subject_id': self.building.pk,
            'fields': {
                'photo_type': 'front',
                'caption': 'Offline photo',
                'gps_lat': '13.4969',
                'gps_lon': '39.4769',
                'gps_accuracy_m': '8',
            },
            'image': {
                'name': 'offline.jpg',
                'type': 'image/jpeg',
                'data_base64': _tiny_jpeg_b64(),
            },
        }
        res = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.json()['ok'])
        self.assertEqual(BuildingImage.objects.filter(building=self.building).count(), 1)

    def test_sync_land_asset_site(self):
        land, _ = LandValuation.objects.get_or_create(loan_request=self.loan)
        url = reverse('collateral:offline_sync')
        payload = {
            'kind': 'asset_site',
            'loan_request_id': self.loan.pk,
            'visit_kind': 'land',
            'subject_id': land.pk,
            'fields': {
                'land_size_sqm': '250',
                'unit_price_per_sqm': '1500',
                'notes': 'Offline land',
                'site_gps_lat': '13.5',
                'site_gps_lon': '39.5',
                'site_gps_accuracy_m': '15',
            },
        }
        res = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.json()['ok'])
        land.refresh_from_db()
        self.assertEqual(land.land_size_sqm, Decimal('250'))
        self.assertIsNotNone(land.site_gps_lat)
