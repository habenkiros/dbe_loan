"""Risk desk + Cooperative branch performance MVPs."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from loans.models import Branch, District, LoanCategory, CollateralType, LoanRequest

User = get_user_model()


class RiskAndCooperativeProductTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='RiskCoop Dist')
        self.branch = Branch.objects.create(name='RiskCoop Branch', district=self.district)
        self.category = LoanCategory.objects.create(name='RiskCoop Cat')
        self.collateral = CollateralType.objects.create(name='RiskCoop Coll')
        self.risk = User.objects.create_user(
            username='risk_mvp', password='pass', phone_number='0911000301',
            role='risk_compliance',
        )
        self.coop = User.objects.create_user(
            username='coop_mvp', password='pass', phone_number='0911000302',
            role='cooperative_manager',
        )
        self.loan = LoanRequest.objects.create(
            applicant_name='Risk Applicant',
            phone_number='0911000399',
            category=self.category,
            collateral=self.collateral,
            amount_requested=100000,
            reason='test',
            status='Pending',
            district=self.district,
            branch=self.branch,
            origin_level=LoanRequest.ORIGIN_BRANCH,
            operation_manager_approval=False,
        )

    def test_risk_desk_accessible(self):
        client = Client()
        client.login(username='risk_mvp', password='pass')
        resp = client.get(reverse('risk_desk'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Risk &amp; Compliance desk')

    def test_risk_review_saves(self):
        client = Client()
        client.login(username='risk_mvp', password='pass')
        resp = client.post(reverse('save_risk_review', args=[self.loan.id]), {
            'risk_review_note': 'Thin coverage watch',
            'next': reverse('loan_request_detail', args=[self.loan.id]),
        })
        self.assertEqual(resp.status_code, 302)
        self.loan.refresh_from_db()
        self.assertTrue(self.loan.risk_reviewed_at)
        self.assertEqual(self.loan.risk_review_note, 'Thin coverage watch')

    def test_cooperative_performance_accessible(self):
        client = Client()
        client.login(username='coop_mvp', password='pass')
        resp = client.get(reverse('cooperative_performance'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Branch performance')
        self.assertContains(resp, 'Intake pending')

    def test_cooperative_queue_shows_aging(self):
        client = Client()
        client.login(username='coop_mvp', password='pass')
        resp = client.get(reverse('view_loan_requests_operation_manager') + '?show=pending')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Age')

    def test_role_home_redirects(self):
        client = Client()
        client.login(username='risk_mvp', password='pass')
        resp = client.get(reverse('home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/risk/', resp['Location'])

        client.logout()
        client.login(username='coop_mvp', password='pass')
        resp = client.get(reverse('home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('view_loan_requests_operation_manager', resp['Location'])

    def test_risk_cannot_open_committee_queue(self):
        client = Client()
        client.login(username='risk_mvp', password='pass')
        resp = client.get(reverse('view_loan_requests_manager') + '?queue=my_votes')
        self.assertEqual(resp.status_code, 302)
        desk = client.get(reverse('risk_desk'))
        self.assertEqual(desk.status_code, 200)
        self.assertNotContains(desk, 'Committee loans')
        self.assertNotContains(desk, 'Approval queue')
