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
        self.assertTrue(reverse('appraisal_desk').startswith('/hub/appraisal'))
        self.assertTrue(reverse('its_desk').startswith('/hub/its'))
        self.assertTrue(reverse('mis_desk').startswith('/hub/mis'))

    def test_applicant_login_stays_on_root(self):
        resp = self.client.get('/login/')
        self.assertEqual(resp.status_code, 200)
        # Must NOT redirect to hub login
        self.assertEqual(resp.request['PATH_INFO'], '/login/')


class HubAdminRoleTests(TestCase):
    """admin.sys is role=admin, often without Django is_superuser."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='admin.sys',
            password='Demo@12345',
            phone_number='0911000001',
            role='admin',
            is_staff=True,
            is_superuser=False,
        )

    def test_hub_admin_sees_workbench_and_settings(self):
        self.client.login(username='admin.sys', password='Demo@12345')
        home = self.client.get(reverse('home'))
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, 'System workbench')
        self.assertContains(home, 'Users')
        self.assertContains(home, 'Organization')
        self.assertContains(home, 'Districts')
        self.assertContains(home, 'Branches')
        self.assertContains(home, 'Departments')
        self.assertContains(home, 'Settings')
        self.assertContains(home, 'hub-nav-toggle')
        self.assertContains(home, 'id="hub-main-nav"')
        self.assertContains(home, 'dropdown-label">Districts')
        self.assertContains(home, 'dropdown-label">Branches')
        self.assertContains(home, 'dropdown-label">Departments')
        self.assertNotContains(home, 'unlock-queue')
        self.assertNotContains(home, 'Unlock queue')

        users = self.client.get(reverse('manage_users'))
        self.assertEqual(users.status_code, 200)

        cats = self.client.get(reverse('manage_loan_categories'))
        self.assertEqual(cats.status_code, 200)

        districts = self.client.get(reverse('manage_districts'))
        self.assertEqual(districts.status_code, 200)


class HubEngineeringNavTests(TestCase):
    def test_engineering_head_sees_unlock_queue(self):
        User.objects.create_user(
            username='eng.head',
            password='Demo@12345',
            phone_number='0911000099',
            role='engineering_head',
        )
        client = Client()
        client.login(username='eng.head', password='Demo@12345')
        home = client.get(reverse('home'))
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, 'Unlock queue')
        self.assertContains(home, reverse('collateral:unlock_queue'))


class HubOfficerNavTests(TestCase):
    def test_loan_officer_primary_nav_is_short(self):
        User.objects.create_user(
            username='lo.nav',
            password='Demo@12345',
            phone_number='0911000777',
            role='loan_officer',
        )
        client = Client()
        client.login(username='lo.nav', password='Demo@12345')
        home = client.get(reverse('home'))
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, 'Scan / KYC')
        self.assertContains(home, 'More')
        self.assertContains(home, 'dropdown-label">Appraisal')
        self.assertContains(home, 'dropdown-label">Collateral')
        self.assertContains(home, reverse('appraisal_desk'))
        self.assertContains(home, 'hub-nav-mobile-account')
        self.assertContains(home, 'hub-user-notify')
        self.assertContains(home, reverse('loan_notifications_list'))
        self.assertContains(home, 'Reports catalog')
        self.assertContains(home, 'Open reports')
