"""Field HTTPS overlay must accept whatever LAN IP DHCP assigned."""
import os
from unittest.mock import patch

from django.http import HttpRequest
from django.test import SimpleTestCase, override_settings

from decsi_loan.settings import _https_allow_any_host


class FieldHttpsAnyHostTests(SimpleTestCase):
    def test_proxy_defaults_to_any_host(self):
        with patch.dict(os.environ, {'USE_HTTPS_PROXY': '1', 'HTTPS_ALLOW_ANY_HOST': '1'}):
            self.assertTrue(_https_allow_any_host())

    def test_proxy_can_lock_hosts(self):
        with patch.dict(os.environ, {'USE_HTTPS_PROXY': '1', 'HTTPS_ALLOW_ANY_HOST': '0'}):
            self.assertFalse(_https_allow_any_host())

    def test_http_only_does_not_force_any_host(self):
        with patch.dict(os.environ, {'USE_HTTPS_PROXY': '0', 'HTTPS_ALLOW_ANY_HOST': '1'}):
            self.assertFalse(_https_allow_any_host())

    @override_settings(ALLOWED_HOSTS=['*'])
    def test_request_to_arbitrary_lan_ip_is_not_disallowed(self):
        request = HttpRequest()
        request.META['HTTP_HOST'] = '10.9.8.7:8443'
        self.assertEqual(request.get_host(), '10.9.8.7:8443')
