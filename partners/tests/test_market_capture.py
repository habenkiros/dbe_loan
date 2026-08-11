"""External-only market portal tests (2-step submit)."""

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from collateral.models import MainWork, SubWork
from loans.models import City, Region, Zone
from partners.models import MarketActor, MarketObservation


class ExternalMarketPortalTests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name='Portal Region')
        self.zone = Zone.objects.create(name='Portal Zone', region=self.region)
        self.city = City.objects.create(name='Portal City', zone=self.zone)
        self.mw = MainWork.objects.create(name='Concrete P')
        self.sw = SubWork.objects.create(main_work=self.mw, name='Slab')

    def test_staff_market_nav_removed(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        lo = User.objects.create_user(
            username='no_mkt_lo', password='pass', phone_number='0911777001',
            role='loan_officer',
        )
        client = Client()
        client.force_login(lo)
        res = client.get('/partners/')
        self.assertIn(res.status_code, (404, 301, 302))

    def test_guest_two_step_catalog(self):
        client = Client()
        landing = client.get(reverse('market_portal:landing'))
        self.assertEqual(landing.status_code, 200)
        self.assertContains(landing, 'Share a local price')
        self.assertContains(landing, 'Area')

        step1 = client.post(reverse('market_portal:landing'), {
            'guest_name': 'Adi Haki Cement',
            'guest_phone': '0912345678',
            'region': self.region.pk,
            'zone': self.zone.pk,
            'city': self.city.pk,
        })
        self.assertEqual(step1.status_code, 302)
        self.assertEqual(step1.url, reverse('market_portal:submit_product'))

        step2_page = client.get(reverse('market_portal:submit_product'))
        self.assertEqual(step2_page.status_code, 200)
        self.assertContains(step2_page, 'Construction catalog')
        self.assertContains(step2_page, 'Other product')

        step2 = client.post(reverse('market_portal:submit_product'), {
            'product_mode': 'catalog',
            'main_work': self.mw.pk,
            'sub_work': self.sw.pk,
            'sub_sub_work': '',
            'item_label': '',
            'unit': 'm2',
            'unit_price_etb': '1500',
            'condition': MarketObservation.CONDITION_NA,
            'observed_at': '2026-08-07',
            'notes': '',
        })
        self.assertEqual(step2.status_code, 302, step2.content)
        obs = MarketObservation.objects.get(unit_price_etb=Decimal('1500'))
        self.assertEqual(obs.sub_work_id, self.sw.pk)
        self.assertEqual(obs.city_id, self.city.pk)

    def test_guest_two_step_free_text(self):
        client = Client()
        client.post(reverse('market_portal:landing'), {
            'guest_name': 'Land Broker',
            'guest_phone': '',
            'region': self.region.pk,
            'zone': self.zone.pk,
            'city': self.city.pk,
        })
        step2 = client.post(reverse('market_portal:submit_product'), {
            'product_mode': 'free',
            'main_work': '',
            'sub_work': '',
            'sub_sub_work': '',
            'item_label': 'Plot near stela',
            'unit': 'm2',
            'unit_price_etb': '8000',
            'condition': MarketObservation.CONDITION_NA,
            'observed_at': '2026-08-07',
            'notes': '',
        })
        self.assertEqual(step2.status_code, 302, step2.content)
        self.assertTrue(
            MarketObservation.objects.filter(
                item_label='Plot near stela', unit_price_etb=Decimal('8000'),
            ).exists()
        )

    def test_self_register_uses_saved_location(self):
        """Registered actors set city once at signup; later only product+price."""
        client = Client()
        reg = client.post(reverse('market_portal:register'), {
            'name': 'Self Dealer Co',
            'phone_number': '0911111111',
            'actor_kind': MarketActor.KIND_DEALER,
            'product_focus': MarketActor.FOCUS_BUILDING,
            'region': self.region.pk,
            'zone': self.zone.pk,
            'city': self.city.pk,
            'username': 'selfdealer1',
            'password': 'secret99',
            'password2': 'secret99',
        })
        self.assertEqual(reg.status_code, 302, reg.content)
        self.assertEqual(reg.url, reverse('market_portal:submit_product'))

        actor = MarketActor.objects.get(portal_username='selfdealer1')
        self.assertEqual(actor.primary_city_id, self.city.pk)

        # Home skips area and lands on product (location already known)
        home = client.get(reverse('market_portal:home'))
        self.assertEqual(home.status_code, 302)
        self.assertEqual(home.url, reverse('market_portal:submit_product'))

        product_page = client.get(reverse('market_portal:submit_product'))
        self.assertEqual(product_page.status_code, 200)
        self.assertContains(product_page, 'Portal City')
        self.assertContains(product_page, 'Change')
        self.assertContains(product_page, 'Seqela Market')
        self.assertContains(product_page, 'Profile')

        # Profile edit
        profile_get = client.get(reverse('market_portal:profile'))
        self.assertEqual(profile_get.status_code, 200)
        self.assertContains(profile_get, 'Your profile')

        city2 = City.objects.create(name='Portal City 2', zone=self.zone)
        profile_post = client.post(reverse('market_portal:profile'), {
            'name': 'Self Dealer Updated',
            'phone_number': '0999999999',
            'actor_kind': MarketActor.KIND_BROKER,
            'product_focus': MarketActor.FOCUS_VEHICLE,
            'region': self.region.pk,
            'zone': self.zone.pk,
            'city': city2.pk,
            'username': 'selfdealer1',
            'password': '',
            'password2': '',
        })
        self.assertEqual(profile_post.status_code, 302, profile_post.content)
        actor.refresh_from_db()
        self.assertEqual(actor.name, 'Self Dealer Updated')
        self.assertEqual(actor.phone_number, '0999999999')
        self.assertEqual(actor.actor_kind, MarketActor.KIND_BROKER)
        self.assertEqual(actor.primary_city_id, city2.pk)

        post = client.post(reverse('market_portal:submit_product'), {
            'product_mode': 'free',
            'item_label': 'HCB 20cm',
            'unit': 'piece',
            'unit_price_etb': '48',
            'condition': MarketObservation.CONDITION_NEW,
            'observed_at': '2026-08-07',
            'notes': '',
        })
        self.assertEqual(post.status_code, 302, post.content)
        obs = MarketObservation.objects.get(item_label='HCB 20cm', unit_price_etb=Decimal('48'))
        self.assertEqual(obs.city_id, city2.pk)
        self.assertEqual(obs.market_actor_id, actor.pk)

    def test_ajax_cascade_public(self):
        client = Client()
        z = client.get(reverse('market_portal:ajax_zones'), {'region_id': self.region.pk})
        self.assertEqual(z.json()[0]['name'], 'Portal Zone')
        c = client.get(reverse('market_portal:ajax_cities'), {'zone_id': self.zone.pk})
        self.assertEqual(c.json()[0]['name'], 'Portal City')
        sw = client.get(reverse('market_portal:ajax_sub_works'), {'main_work_id': self.mw.pk})
        self.assertEqual(sw.json()[0]['name'], 'Slab')
