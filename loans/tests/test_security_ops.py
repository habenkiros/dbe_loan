"""Password reset, idle session, audit export."""
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from loans.models import SecurityAuditLog
from loans.security_export import parse_audit_filters

User = get_user_model()


@override_settings(
    MFA_REQUIRED=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SESSION_IDLE_TIMEOUT=1800,
)
class PasswordResetTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='resetme',
            email='resetme@example.com',
            password='CorrectHorse1!',
            phone_number='0911222333',
            role='loan_officer',
        )

    def test_password_reset_sends_mail_and_audits(self):
        resp = self.client.post(reverse('password_reset'), {'email': 'resetme@example.com'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(
            SecurityAuditLog.objects.filter(
                event_type=SecurityAuditLog.EVT_PASSWORD_RESET_REQUESTED,
                username='resetme',
            ).exists()
        )

    def test_password_reset_confirm_audits(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        # Step 1: validate token (Django stores it in session and redirects)
        url = reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        set_url = reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': 'set-password'})
        resp2 = self.client.post(set_url, {
            'new_password1': 'NewCorrectHorse2!',
            'new_password2': 'NewCorrectHorse2!',
        })
        self.assertEqual(resp2.status_code, 302)
        self.assertTrue(
            SecurityAuditLog.objects.filter(
                event_type=SecurityAuditLog.EVT_PASSWORD_RESET_COMPLETED,
                username='resetme',
            ).exists()
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewCorrectHorse2!'))


@override_settings(MFA_REQUIRED=False, SESSION_IDLE_TIMEOUT=1800)
class SessionKeepaliveTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='idleuser',
            password='CorrectHorse1!',
            phone_number='0911222444',
            role='loan_officer',
        )
        self.client.login(username='idleuser', password='CorrectHorse1!')

    def test_keepalive_ok(self):
        resp = self.client.post(reverse('session_keepalive'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['idle_timeout'], 1800)


@override_settings(MFA_REQUIRED=False)
class AuditExportTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.auditor = User.objects.create_user(
            username='auditor1',
            password='CorrectHorse1!',
            phone_number='0911222555',
            role='auditor',
        )
        SecurityAuditLog.objects.create(
            event_type=SecurityAuditLog.EVT_LOGIN_SUCCESS,
            username='someone',
            detail={'test': True},
        )
        self.client.login(username='auditor1', password='CorrectHorse1!')

    def test_export_csv_and_audit_event(self):
        resp = self.client.get(reverse('security_audit_export') + '?format=csv')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp['Content-Type'])
        self.assertTrue(
            SecurityAuditLog.objects.filter(
                event_type=SecurityAuditLog.EVT_AUDIT_EXPORTED,
                username='auditor1',
            ).exists()
        )

    def test_export_xlsx(self):
        resp = self.client.get(reverse('security_audit_export') + '?format=xlsx')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('spreadsheetml', resp['Content-Type'])

    def test_parse_filters(self):
        qs, meta = parse_audit_filters({'event_type': 'login_success', 'username': 'some'})
        self.assertEqual(meta['event_type'], 'login_success')
        self.assertTrue(qs.filter(username='someone').exists())
