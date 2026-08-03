"""
Three real field scenarios for collateral estimation:

1. Online at branch — prepare offline + live capture while connected
2. Offline on site, then sync later — queue payloads, sync when back online
3. Weak / intermittent network — partial sync failures stay queued and retry

These exercise the server sync/bundle APIs that the phone PWA calls.
Client IndexedDB queue semantics are asserted from the JS contract
(listPending includes pending+failed; markFailed increments attempts).
"""

from __future__ import annotations

import base64
import json
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from PIL import Image

from collateral.models import Building, BuildingImage
from collateral.policy import clear_policy_cache
from loans.models import (
    Branch,
    City,
    CollateralEstimationConfig,
    CollateralType,
    District,
    LoanCategory,
    LoanRequest,
    Region,
    Zone,
)


User = get_user_model()
BASE_DIR = Path(__file__).resolve().parents[2]


def _tiny_jpeg_b64():
    buf = BytesIO()
    Image.new('RGB', (16, 16), color=(20, 140, 60)).save(buf, format='JPEG')
    return base64.b64encode(buf.getvalue()).decode('ascii')


class FieldScenarioBase(TestCase):
    def setUp(self):
        region = Region.objects.create(name='Tigray Scenario')
        zone = Zone.objects.create(name='Mekelle Scenario', region=region)
        self.city = City.objects.create(name='Hawelti Scenario', zone=zone)
        district = District.objects.create(name='Central Scenario')
        branch = Branch.objects.create(name='Branch Scenario', district=district)
        collateral = CollateralType.objects.create(name='Building Scenario')
        category = LoanCategory.objects.create(name='MSME Scenario')
        self.officer = User.objects.create_user(
            username='officer_scenario',
            password='pass',
            phone_number='0911888777',
            role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-SCEN-001',
            applicant_name='Scenario Applicant',
            phone_number='0911555666',
            amount_requested=Decimal('350000'),
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
        CollateralEstimationConfig.objects.create(
            mode=CollateralEstimationConfig.MODE_LOAN_OFFICER,
        )
        clear_policy_cache()
        self.building = Building.objects.create(
            loan_request=self.loan,
            name='Scenario Building',
            construction_type='RC',
            floors=1,
            city=self.city,
        )
        self.client = Client()
        self.client.login(username='officer_scenario', password='pass')
        self.sync_url = reverse('collateral:offline_sync')
        self.bundle_url = reverse('collateral:offline_bundle', args=[self.loan.pk])

    def _post_sync(self, payload):
        return self.client.post(
            self.sync_url,
            data=json.dumps(payload),
            content_type='application/json',
        )

    def _site_payload(self, **overrides):
        payload = {
            'kind': 'building_site',
            'loan_request_id': self.loan.pk,
            'visit_kind': 'building',
            'subject_id': self.building.pk,
            'fields': {
                'name': 'Scenario Building',
                'construction_type': 'RC',
                'floors': '2',
                'city': str(self.city.pk),
                'site_gps_lat': '13.496900',
                'site_gps_lon': '39.476900',
                'site_gps_accuracy_m': '12',
            },
        }
        payload.update(overrides)
        return payload

    def _photo_payload(self, *, include_image=True, photo_type='front', caption='Field photo'):
        payload = {
            'kind': 'photo',
            'loan_request_id': self.loan.pk,
            'visit_kind': 'building',
            'subject_id': self.building.pk,
            'fields': {
                'photo_type': photo_type,
                'caption': caption,
                'gps_lat': '13.49695',
                'gps_lon': '39.47695',
                'gps_accuracy_m': '9',
            },
        }
        if include_image:
            payload['image'] = {
                'name': f'{photo_type}.jpg',
                'type': 'image/jpeg',
                'data_base64': _tiny_jpeg_b64(),
            }
        return payload


class OnlineAtBranchScenarioTests(FieldScenarioBase):
    """Scenario 1: officer is online at the branch before leaving for the site."""

    def test_prepare_offline_bundle_and_field_pages(self):
        # Prepare offline
        bundle = self.client.get(self.bundle_url)
        self.assertEqual(bundle.status_code, 200)
        data = bundle.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['bundle']['loan_request_code'], 'LR-SCEN-001')
        self.assertEqual(len(data['bundle']['buildings']), 1)
        self.assertIn('field_visit_path', data['bundle']['buildings'][0])

        sw = self.client.get(reverse('collateral:offline_sw'))
        self.assertEqual(sw.status_code, 200)
        self.assertIn(b'CACHE_NAME', sw.content)

        checklist = self.client.get(reverse('collateral:field_checklist'))
        self.assertEqual(checklist.status_code, 200)
        self.assertContains(checklist, 'Download for offline')

        # Live field visit screens load online
        visit = self.client.get(
            reverse('collateral:field_visit_step', args=[self.building.pk, 1]),
        )
        self.assertEqual(visit.status_code, 200)
        self.assertContains(visit, 'Mark site location')
        self.assertContains(visit, 'Download for offline')

        photos = self.client.get(
            reverse('collateral:field_visit_step', args=[self.building.pk, 3]),
        )
        self.assertEqual(photos.status_code, 200)
        self.assertContains(photos, 'Take photo')

    def test_online_capture_site_and_photo(self):
        # Online capture via the same sync API the PWA uses when reconnecting,
        # and also as the authoritative write path for queued items.
        site = self._post_sync(self._site_payload())
        self.assertEqual(site.status_code, 200, site.content)
        self.assertTrue(site.json()['ok'])
        self.building.refresh_from_db()
        self.assertEqual(self.building.floors, 2)
        self.assertIsNotNone(self.building.site_gps_lat)

        photo = self._post_sync(self._photo_payload(caption='Branch online photo'))
        self.assertEqual(photo.status_code, 200, photo.content)
        self.assertTrue(photo.json()['ok'])
        self.assertEqual(BuildingImage.objects.filter(building=self.building).count(), 1)


class OfflineThenSyncScenarioTests(FieldScenarioBase):
    """Scenario 2: capture while offline, sync later when back online."""

    def test_queued_site_then_photos_sync_in_order(self):
        # Branch prepare
        prep = self.client.get(self.bundle_url)
        self.assertTrue(prep.json()['ok'])

        # Simulated offline queue (IndexedDB → sync API when online again)
        queued = [
            self._site_payload(),
            self._photo_payload(photo_type='front', caption='Offline front'),
            self._photo_payload(photo_type='side', caption='Offline side'),
        ]

        results = []
        for item in queued:
            res = self._post_sync(item)
            self.assertEqual(res.status_code, 200, res.content)
            body = res.json()
            self.assertTrue(body['ok'], body)
            results.append(body)

        self.building.refresh_from_db()
        self.assertEqual(self.building.name, 'Scenario Building')
        self.assertEqual(self.building.floors, 2)
        self.assertIsNotNone(self.building.site_gps_lat)
        self.assertEqual(BuildingImage.objects.filter(building=self.building).count(), 2)
        self.assertEqual(len(results), 3)

    def test_client_queue_contract_keeps_failed_for_later_sync(self):
        """Assert JS contract: failed items remain in pending list for retry."""
        offline_js = (BASE_DIR / 'static/js/collateral_offline.js').read_text(encoding='utf-8')
        db_js = (BASE_DIR / 'static/js/collateral_offline_db.js').read_text(encoding='utf-8')

        self.assertIn("navigator.onLine", offline_js)
        self.assertIn("serverReachable", offline_js)
        self.assertIn("shouldQueueLocally", offline_js)
        self.assertIn("nextFieldVisitStepUrl", offline_js)
        self.assertIn("queueForm", offline_js)
        self.assertIn("runSync", offline_js)
        self.assertIn("SYNC_CONCURRENCY", offline_js)
        self.assertIn("mapPool", offline_js)
        self.assertIn("client_uid", offline_js)
        self.assertIn("pingUrl", offline_js)
        self.assertIn("window.addEventListener('online'", offline_js)
        self.assertIn('markFailed', offline_js)
        self.assertIn('markDone', offline_js)
        self.assertIn('startAutoRetry', offline_js)
        self.assertIn('listReadyToSync', offline_js)
        self.assertIn('opts.permanent', db_js)

        self.assertIn("r.status === 'pending' || r.status === 'failed'", db_js)
        self.assertIn('row.attempts = (row.attempts || 0) + 1', db_js)
        self.assertIn("row.status = 'failed'", db_js)
        self.assertIn("row.status = 'synced'", db_js)
        self.assertIn("row.status = 'abandoned'", db_js)
        self.assertIn('next_retry_at', db_js)
        self.assertIn('MAX_ATTEMPTS', db_js)
        self.assertIn('backoffMs', db_js)


class WeakNetworkRetryScenarioTests(FieldScenarioBase):
    """Scenario 3: intermittent failures; failed items stay retryable."""

    def test_photo_without_image_fails_then_retries_successfully(self):
        # First attempt: incomplete offline payload (common on flaky upload)
        bad = self._post_sync(self._photo_payload(include_image=False))
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(bad.json()['ok'])
        self.assertIn('image', bad.json()['error'].lower())
        self.assertEqual(BuildingImage.objects.filter(building=self.building).count(), 0)

        # Retry with full payload (as Sync now / online event would do)
        good = self._post_sync(self._photo_payload(include_image=True, caption='Retry photo'))
        self.assertEqual(good.status_code, 200, good.content)
        self.assertTrue(good.json()['ok'])
        self.assertEqual(BuildingImage.objects.filter(building=self.building).count(), 1)

    def test_partial_batch_one_fails_one_succeeds_then_retry_failed(self):
        ok_site = self._post_sync(self._site_payload())
        self.assertTrue(ok_site.json()['ok'])

        fail_photo = self._post_sync(self._photo_payload(include_image=False))
        self.assertEqual(fail_photo.status_code, 400)

        ok_photo = self._post_sync(
            self._photo_payload(include_image=True, photo_type='rear', caption='Ok photo'),
        )
        self.assertTrue(ok_photo.json()['ok'])
        self.assertEqual(BuildingImage.objects.filter(building=self.building).count(), 1)

        # Retry the failed one
        retry = self._post_sync(
            self._photo_payload(include_image=True, photo_type='front', caption='Retried'),
        )
        self.assertTrue(retry.json()['ok'])
        self.assertEqual(BuildingImage.objects.filter(building=self.building).count(), 2)

    def test_invalid_json_and_missing_loan_are_safe_failures(self):
        bad_json = self.client.post(
            self.sync_url,
            data='{not-json',
            content_type='application/json',
        )
        self.assertEqual(bad_json.status_code, 400)
        self.assertFalse(bad_json.json()['ok'])

        missing_loan = self._post_sync({'kind': 'building_site', 'fields': {}})
        self.assertEqual(missing_loan.status_code, 400)
        self.assertIn('loan_request_id', missing_loan.json()['error'])

    def test_retry_behavior_documented_gaps(self):
        """Production retry policy must be present in the client queue."""
        offline_js = (BASE_DIR / 'static/js/collateral_offline.js').read_text(encoding='utf-8')
        db_js = (BASE_DIR / 'static/js/collateral_offline_db.js').read_text(encoding='utf-8')
        sw_js = (BASE_DIR / 'static/js/collateral_sw.js').read_text(encoding='utf-8')

        self.assertIn('AUTO_RETRY_INTERVAL_MS', offline_js)
        self.assertIn('SYNC_TIMEOUT_MS', offline_js)
        self.assertIn('setInterval', offline_js)
        self.assertIn('AbortController', offline_js)
        self.assertIn('includeAbandoned', offline_js)
        self.assertIn('silent: true', offline_js)

        self.assertIn('var MAX_ATTEMPTS = 8', db_js)
        self.assertIn('BASE_BACKOFF_MS', db_js)
        self.assertIn('MAX_BACKOFF_MS', db_js)
        self.assertIn('function backoffMs', db_js)
        self.assertIn('listReadyToSync', db_js)
        self.assertIn('resetAbandonedAll', db_js)
        self.assertIn("row.status = 'abandoned'", db_js)

        self.assertIn('collateral-field-v8', sw_js)
        self.assertIn('cacheFirst', sw_js)
        self.assertIn('offline/shell', sw_js)
        # Final submit stays online by design (not a queue item)
        offline_bar = (
            BASE_DIR / 'templates/collateral/_offline_bar.html'
        ).read_text(encoding='utf-8')
        self.assertIn('Final collateral submit stays online', offline_bar)
