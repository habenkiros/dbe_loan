"""Sanctions / PEP screening into Fraud/AML compliance desk."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from loans.compliance.case_engine import (
    maybe_open_sanctions_case,
    origination_compliance_blocked,
    screen_loan_and_open_case,
)
from loans.compliance.sanctions_screen import screen_subject
from loans.models import (
    Branch,
    CollateralType,
    ComplianceCase,
    District,
    LoanCategory,
    LoanRequest,
    SanctionsScreeningResult,
)

User = get_user_model()


class SanctionsScreeningTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='SAN Dist')
        branch = Branch.objects.create(name='SAN Branch', district=district)
        category = LoanCategory.objects.create(name='SAN Cat')
        collateral = CollateralType.objects.create(name='SAN Coll')
        self.risk = User.objects.create_user(
            username='san_risk', password='x', role='risk_compliance', phone_number='0911000888',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-SAN-001',
            applicant_name='Clean Applicant',
            phone_number='0911222444',
            amount_requested=Decimal('50000'),
            reason='Trade',
            category=category,
            branch=branch,
            collateral=collateral,
            queue_approved=True,
        )

    @override_settings(SANCTIONS_PROVIDER='mock')
    def test_demo_customer_number_hits(self):
        result = screen_subject(name='Anyone', customer_number='SANCTIONED001')
        self.assertTrue(result['hit'])
        self.assertIn('sanctions', result['match_types'])

    @override_settings(SANCTIONS_PROVIDER='mock')
    def test_pep_demo_hits(self):
        result = screen_subject(name='PEP Demo Official', customer_number='')
        self.assertTrue(result['hit'])
        self.assertIn('pep', result['match_types'])

    @override_settings(SANCTIONS_PROVIDER='mock')
    def test_clear_name_no_hit(self):
        result = screen_subject(name='Tekeste Jigar Meles', customer_number='2000050041')
        self.assertFalse(result['hit'])

    @override_settings(SANCTIONS_PROVIDER='mock')
    def test_hit_opens_case_and_blocks_committee(self):
        self.loan.applicant_name = 'Sanctioned Demo Person'
        self.loan.customer_number = 'SANCTIONED001'
        self.loan.save()
        case = screen_loan_and_open_case(self.loan, opened_by=self.risk)
        self.assertIsNotNone(case)
        self.assertEqual(case.case_type, ComplianceCase.TYPE_SANCTIONS)
        self.assertTrue(origination_compliance_blocked(self.loan))
        self.assertTrue(
            SanctionsScreeningResult.objects.filter(loan_request=self.loan, hit=True).exists()
        )

    @override_settings(SANCTIONS_PROVIDER='off')
    def test_provider_off_skips(self):
        self.loan.customer_number = 'SANCTIONED001'
        self.loan.save()
        self.assertIsNone(screen_loan_and_open_case(self.loan))

    @override_settings(SANCTIONS_PROVIDER='mock')
    def test_policy_can_disable_sanctions_open(self):
        from loans.compliance.policy import get_compliance_policy

        policy = get_compliance_policy()
        policy.auto_open_sanctions_hit = False
        policy.auto_open_pep_hit = False
        policy.save()
        result = screen_subject(name='x', customer_number='SANCTIONED001')
        case = maybe_open_sanctions_case(self.loan, result, opened_by=self.risk)
        self.assertIsNone(case)
        self.assertTrue(
            SanctionsScreeningResult.objects.filter(loan_request=self.loan, hit=True).exists()
        )

    @override_settings(SANCTIONS_PROVIDER='mock')
    def test_rescreen_endpoint(self):
        self.loan.customer_number = 'SANCTIONED001'
        self.loan.applicant_name = 'Sanctioned Demo Person'
        self.loan.save()
        client = Client()
        self.assertTrue(client.login(username='san_risk', password='x'))
        resp = client.post(reverse('compliance_rescreen_loan', args=[self.loan.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            ComplianceCase.objects.filter(
                loan_request=self.loan, case_type=ComplianceCase.TYPE_SANCTIONS,
            ).exists()
        )

    def test_sanctions_queue_on_desk(self):
        open_case = ComplianceCase.objects.create(
            case_number='FC-209901-0001',
            case_type=ComplianceCase.TYPE_SANCTIONS,
            source=ComplianceCase.SOURCE_NAME_SCREEN,
            summary='Demo sanctions hit for queue test',
            loan_request=self.loan,
            opened_by=self.risk,
        )
        self.assertTrue(open_case.is_open)
        client = Client()
        self.assertTrue(client.login(username='san_risk', password='x'))
        resp = client.get(reverse('compliance_desk') + '?queue=sanctions')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, open_case.case_number)
