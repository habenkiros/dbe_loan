"""Legacy /hub URL redirects for staff routes moved off the public root."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse


User = get_user_model()


class StaffHubRedirectTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='hubstaff',
            password='StaffPass1!',
            phone_number='0911000888',
            role='loan_officer',
            is_staff=True,
        )

    def test_old_staff_path_redirects_to_hub(self):
        resp = self.client.get('/manage_users/', follow=False)
        # superuser-only page still redirects to hub path first (then login)
        self.assertIn(resp.status_code, (301, 302))
        self.assertTrue(resp.url.startswith('/hub/manage_users'))

    def test_staff_home_at_hub(self):
        self.client.login(username='hubstaff', password='StaffPass1!')
        resp = self.client.get('/hub/')
        self.assertEqual(resp.status_code, 200)

    def test_named_reverse_uses_hub_prefix(self):
        self.assertTrue(reverse('home').startswith('/hub'))
        self.assertTrue(reverse('login').startswith('/hub/login'))
        self.assertTrue(reverse('agent_chat_api').startswith('/hub/agent/chat'))

    def test_applicant_login_stays_on_root(self):
        resp = self.client.get('/login/')
        self.assertEqual(resp.status_code, 200)
        # Must NOT redirect to hub login
        self.assertEqual(resp.request['PATH_INFO'], '/login/')
