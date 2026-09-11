"""Lockout + MFA + security audit tests."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
import pyotp

from loans.models import IpLoginThrottle, SecurityAuditLog
from loans.security import encrypt_mfa_secret, generate_mfa_secret, verify_totp

User = get_user_model()


@override_settings(
    MFA_REQUIRED=False,
    LOGIN_MAX_FAILED_ATTEMPTS=3,
    LOGIN_LOCKOUT_MINUTES=15,
)
class LoginLockoutTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='officer1',
            password='CorrectHorse1!',
            phone_number='0911000000',
            role='loan_officer',
        )

    def test_failed_login_increments_and_locks(self):
        for _ in range(3):
            self.client.post(reverse('login'), {
                'username': 'officer1',
                'password': 'wrong',
            })
        self.user.refresh_from_db()
        self.assertGreaterEqual(self.user.failed_login_attempts, 3)
        self.assertTrue(self.user.is_login_locked())
        self.assertTrue(
            SecurityAuditLog.objects.filter(event_type=SecurityAuditLog.EVT_LOGIN_LOCKED).exists()
        )

    def test_successful_login_without_mfa(self):
        resp = self.client.post(reverse('login'), {
            'username': 'officer1',
            'password': 'CorrectHorse1!',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            SecurityAuditLog.objects.filter(event_type=SecurityAuditLog.EVT_LOGIN_SUCCESS).exists()
        )

    def test_authenticated_login_ignores_next_to_avoid_permission_loop(self):
        """Logged-in non-superadmin + ?next= to a gated page must not bounce forever."""
        self.client.force_login(self.user)
        resp = self.client.get(
            reverse('login') + '?next=/collateral/settings/policy/',
            follow=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/hub/')
        # Policy is admin/superadmin — officer gets 403, not another login redirect.
        denied = self.client.get('/collateral/settings/policy/', follow=False)
        self.assertEqual(denied.status_code, 403)


@override_settings(MFA_REQUIRED=False)
class MfaFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.secret = generate_mfa_secret()
        self.user = User.objects.create_user(
            username='mfa_user',
            password='CorrectHorse1!',
            phone_number='0911000001',
            role='loan_officer',
            mfa_enabled=True,
            mfa_secret_encrypted=encrypt_mfa_secret(self.secret),
        )

    def test_login_requires_totp(self):
        resp = self.client.post(reverse('login'), {
            'username': 'mfa_user',
            'password': 'CorrectHorse1!',
        })
        self.assertRedirects(resp, reverse('mfa_verify'))
        code = pyotp.TOTP(self.secret).now()
        resp2 = self.client.post(reverse('mfa_verify'), {'otp_code': code})
        self.assertEqual(resp2.status_code, 302)
        self.assertTrue(
            SecurityAuditLog.objects.filter(event_type=SecurityAuditLog.EVT_MFA_SUCCESS).exists()
        )

    def test_verify_totp_helper(self):
        code = pyotp.TOTP(self.secret).now()
        self.assertTrue(verify_totp(self.secret, code))
        self.assertFalse(verify_totp(self.secret, '000000'))


@override_settings(MFA_REQUIRED=False, LOGIN_MAX_FAILED_ATTEMPTS=3)
class IpThrottleTests(TestCase):
    def test_unknown_user_failures_throttle_ip(self):
        client = Client()
        for _ in range(3):
            client.post(reverse('login'), {'username': 'ghost', 'password': 'bad'})
        self.assertTrue(IpLoginThrottle.objects.filter(failed_attempts__gte=3).exists())
