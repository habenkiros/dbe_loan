"""Tests for on-prem Ed25519 product license (no DB required)."""
from datetime import date, timedelta

from django.test import Client, SimpleTestCase, override_settings

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from loans.licensing import (
    clear_license_cache,
    issue_license,
    verify_license_string,
)


def _ephemeral_keypair():
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


class LicenseUnitTests(SimpleTestCase):
    def test_issue_and_verify_valid(self):
        priv, pub = _ephemeral_keypair()
        with override_settings(LICENSE_PUBLIC_KEY_PEM=pub):
            key = issue_license(
                org='Dedebit Credit and Savings Institution',
                org_code='DECSI',
                expires_on=date.today() + timedelta(days=90),
                private_key_pem=priv,
            )
            status = verify_license_string(key)
            self.assertTrue(status.valid)
            self.assertFalse(status.expired)
            self.assertEqual(status.org_code, 'DECSI')

    def test_expired_past_grace_invalid(self):
        priv, pub = _ephemeral_keypair()
        with override_settings(LICENSE_PUBLIC_KEY_PEM=pub, LICENSE_GRACE_DAYS=7):
            key = issue_license(
                org='Dedebit',
                org_code='DECSI',
                issued_on=date.today() - timedelta(days=400),
                expires_on=date.today() - timedelta(days=40),
                private_key_pem=priv,
            )
            status = verify_license_string(key)
            self.assertFalse(status.valid)
            self.assertTrue(status.expired)
            self.assertFalse(status.grace)

    def test_tamper_rejected(self):
        priv, pub = _ephemeral_keypair()
        with override_settings(LICENSE_PUBLIC_KEY_PEM=pub):
            key = issue_license(
                org='Dedebit',
                org_code='DECSI',
                expires_on=date.today() + timedelta(days=30),
                private_key_pem=priv,
            )
            bad = key[:-4] + 'XXXX'
            status = verify_license_string(bad)
            self.assertFalse(status.valid)


@override_settings(LICENSE_ENFORCE='true', DEBUG=False)
class LicenseMiddlewareTests(SimpleTestCase):
    def setUp(self):
        clear_license_cache()

    def tearDown(self):
        clear_license_cache()

    def test_blocked_without_key(self):
        with override_settings(LICENSE_KEY='SEQLA1.notavalid.license'):
            clear_license_cache()
            c = Client()
            r = c.get('/hub/login/')
            self.assertEqual(r.status_code, 403)

    def test_status_page_always_open(self):
        with override_settings(LICENSE_KEY='', LICENSE_KEY_FILE=''):
            clear_license_cache()
            c = Client()
            r = c.get('/license/')
            self.assertEqual(r.status_code, 200)
