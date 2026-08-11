"""Help / user-manual routes for hub, Digital Apply, and market portal."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse


User = get_user_model()


class HubHelpTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='helpstaff',
            password='StaffPass1!',
            phone_number='0911000999',
            role='loan_officer',
            is_staff=True,
        )

    def test_help_requires_login(self):
        resp = self.client.get('/hub/help/')
        self.assertIn(resp.status_code, (301, 302))
        self.assertIn('/hub/login', resp.url)

    def test_help_index_ok(self):
        self.client.login(username='helpstaff', password='StaffPass1!')
        resp = self.client.get(reverse('help_index'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'User manuals')

    def test_help_chapter_customers(self):
        self.client.login(username='helpstaff', password='StaffPass1!')
        resp = self.client.get(reverse('help_chapter', kwargs={'slug': '03-customers'}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Digital Apply')

    def test_help_combined_html(self):
        self.client.login(username='helpstaff', password='StaffPass1!')
        resp = self.client.get(reverse('help_manual_html'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/html', resp['Content-Type'])


class ApplicantHelpTests(TestCase):
    def test_public_help_index(self):
        resp = self.client.get('/help/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Digital Apply')

    def test_public_help_hides_admin(self):
        resp = self.client.get('/help/01-admin/')
        self.assertEqual(resp.status_code, 404)

    def test_amharic_customer_chapter(self):
        resp = self.client.get('/help/03-customers-am/')
        self.assertEqual(resp.status_code, 200)


class MarketHelpTests(TestCase):
    def test_market_help(self):
        resp = self.client.get('/market-portal/help/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Market')
