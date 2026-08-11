"""Production / security settings guards (no CBS live calls)."""
from django.test import SimpleTestCase

from decsi_loan import settings as app_settings


class EnvBoolHelperTests(SimpleTestCase):
    def test_truthy_values(self):
        from decsi_loan.settings import _env_bool
        import os
        from unittest import mock

        for val in ('1', 'true', 'TRUE', 'yes', 'on'):
            with mock.patch.dict(os.environ, {'X_FLAG': val}, clear=False):
                self.assertTrue(_env_bool('X_FLAG', default=False))

    def test_falsey_and_default(self):
        from decsi_loan.settings import _env_bool
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {'X_FLAG': 'False'}, clear=False):
            self.assertFalse(_env_bool('X_FLAG', default=True))
        os.environ.pop('X_FLAG_MISSING', None)
        self.assertFalse(_env_bool('X_FLAG_MISSING', default=False))
        self.assertTrue(_env_bool('X_FLAG_MISSING', default=True))


class ProductionSettingsSmokeTests(SimpleTestCase):
    def test_security_headers_always_on(self):
        self.assertTrue(app_settings.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertEqual(app_settings.X_FRAME_OPTIONS, 'DENY')
        self.assertTrue(app_settings.SESSION_COOKIE_HTTPONLY)
        # JS clients must read csrftoken for AJAX
        self.assertFalse(app_settings.CSRF_COOKIE_HTTPONLY)

    def test_password_min_length_at_least_ten(self):
        min_len = None
        for validator in app_settings.AUTH_PASSWORD_VALIDATORS:
            if validator['NAME'].endswith('MinimumLengthValidator'):
                min_len = validator.get('OPTIONS', {}).get('min_length')
        self.assertIsNotNone(min_len)
        self.assertGreaterEqual(int(min_len), 10)
