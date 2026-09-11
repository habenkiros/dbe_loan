"""DBE portal doors: institution / promoter fill the same overlays as the hub."""

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from applicant_portal.access import categories_for_account
from applicant_portal.models import ApplicantAccount, ApplicantPortalSettings, OnlineApplication
from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanCategory,
    PfiInstitutionProfile,
    ProjectProfile,
)
from loans.product_family import FAMILY_GENERAL, FAMILY_PROJECT, FAMILY_WHOLESALE


class DbePortalAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        ApplicantPortalSettings.objects.update_or_create(
            pk=1,
            defaults={
                'enabled': True,
                'processing_fee_etb': Decimal('0'),
                'min_password_length': 10,
                'require_uppercase': True,
                'require_lowercase': True,
                'require_digit': True,
                'require_special': True,
                'max_failed_logins': 5,
                'lockout_minutes': 15,
                'register_rate_limit_per_hour': 40,
                'require_customer_lookup': False,
            },
        )
        self.district = District.objects.create(name='DBE Dist')
        self.branch = Branch.objects.create(name='DBE Branch', district=self.district)
        self.collateral = CollateralType.objects.create(
            name='DBE Coll', kind=CollateralType.KIND_BUILDING,
        )
        self.financed = CollateralType.objects.create(
            name='Financed plant', kind=CollateralType.KIND_FINANCED,
        )
        self.general = LoanCategory.objects.create(
            name='MSME General', appraisal_mode='msme', product_family=FAMILY_GENERAL,
        )
        self.wholesale = LoanCategory.objects.create(
            name='PFI Facility', appraisal_mode='corporate', product_family=FAMILY_WHOLESALE,
        )
        self.project = LoanCategory.objects.create(
            name='Project Financing', appraisal_mode='corporate', product_family=FAMILY_PROJECT,
        )
        self.password = 'SecurePass1!'

    def test_person_details_form_renders_category_options(self):
        person = ApplicantAccount.objects.create(
            full_name='Sara Customer',
            phone_number='0911000100',
            customer_number='1002003',
            actor_kind=ApplicantAccount.ACTOR_PERSON,
        )
        person.set_password(self.password)
        person.save()
        self.client.post(reverse('applicant_portal:login'), {
            'login': '0911000100',
            'password': self.password,
        })
        # session may use phone or customer — ensure portal session
        from django.test import Client
        client = Client()
        session = client.session
        session['applicant_portal_account_id'] = person.id
        session.save()
        start = client.post(reverse('applicant_portal:apply_start'))
        self.assertEqual(start.status_code, 302)
        app = OnlineApplication.objects.get(applicant=person)
        page = client.get(reverse('applicant_portal:apply_details', args=[app.public_id]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'MSME General')
        self.assertContains(page, f'value="{self.general.id}"')
        self.assertNotContains(page, 'PFI Facility')

    def test_details_rejects_mismatched_collateral(self):
        person = ApplicantAccount.objects.create(
            full_name='Sara Customer',
            phone_number='0911000199',
            customer_number='1002099',
            actor_kind=ApplicantAccount.ACTOR_PERSON,
        )
        app = OnlineApplication.objects.create(
            applicant=person,
            applicant_name=person.full_name,
            phone_number=person.phone_number,
            customer_number=person.customer_number,
            status=OnlineApplication.STATUS_DRAFT,
            processing_fee_amount=Decimal('0'),
        )
        lease = LoanCategory.objects.create(
            name='Lease Test', appraisal_mode='corporate', product_family='lease',
        )
        from applicant_portal.forms import ApplicationDetailsForm
        form = ApplicationDetailsForm({
            'applicant_name': 'Sara Customer',
            'phone_number': person.phone_number,
            'customer_number': person.customer_number,
            'customer_history': 'new',
            'category': str(lease.id),
            'collateral': str(self.collateral.id),
            'district': str(self.district.id),
            'branch': str(self.branch.id),
            'amount_requested': '100000',
            'reason': 'Lease asset.',
        }, instance=app)
        self.assertFalse(form.is_valid())
        self.assertIn('collateral', form.errors)

    def test_person_does_not_see_wholesale_or_project(self):
        person = ApplicantAccount.objects.create(
            full_name='Sara Customer',
            phone_number='0911000100',
            customer_number='1002003',
            actor_kind=ApplicantAccount.ACTOR_PERSON,
        )
        names = set(categories_for_account(person).values_list('name', flat=True))
        self.assertIn('MSME General', names)
        self.assertNotIn('PFI Facility', names)
        self.assertNotIn('Project Financing', names)

    def test_institution_registers_without_customer_number(self):
        resp = self.client.post(reverse('applicant_portal:register') + '?kind=institution', {
            'actor_kind': ApplicantAccount.ACTOR_INSTITUTION,
            'institution_name': 'Tsehay MFI',
            'license_number': 'NBE-22',
            'full_name': 'Aster Desk',
            'phone_number': '0911000200',
            'password': self.password,
            'password_confirm': self.password,
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        acct = ApplicantAccount.objects.get(phone_number='0911000200')
        self.assertEqual(acct.actor_kind, ApplicantAccount.ACTOR_INSTITUTION)
        self.assertEqual(acct.institution_name, 'Tsehay MFI')
        self.assertTrue(acct.customer_number.isdigit())
        names = set(categories_for_account(acct).values_list('name', flat=True))
        self.assertIn('PFI Facility', names)
        self.assertNotIn('MSME General', names)

    def test_institution_fills_pfi_file(self):
        self.client.post(reverse('applicant_portal:register') + '?kind=institution', {
            'actor_kind': ApplicantAccount.ACTOR_INSTITUTION,
            'institution_name': 'Awash Bank',
            'full_name': 'PFI Desk',
            'phone_number': '0911000300',
            'password': self.password,
            'password_confirm': self.password,
            'accept_terms': 'on',
        })
        self.client.post(reverse('applicant_portal:apply_start'))
        app = OnlineApplication.objects.get()
        acct = ApplicantAccount.objects.get(phone_number='0911000300')
        details = self.client.post(reverse('applicant_portal:apply_details', args=[app.public_id]), {
            'applicant_name': 'Awash Bank',
            'phone_number': acct.phone_number,
            'customer_number': acct.customer_number,
            'customer_history': 'existing',
            'category': self.wholesale.id,
            'district': self.district.id,
            'branch': self.branch.id,
            'amount_requested': '5000000',
            'reason': 'On-lending working capital to MSMEs in Tigray.',
        })
        if details.status_code == 200:
            self.fail(details.context['form'].errors)
        self.assertEqual(details.status_code, 302)
        page = self.client.get(reverse('applicant_portal:apply_product', args=[app.public_id]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Institution file')
        saved = self.client.post(reverse('applicant_portal:apply_product', args=[app.public_id]), {
            'institution_name': 'Awash Bank',
            'kind': 'bank',
            'license_number': 'NBE-1',
            'has_adequate_mis': 'on',
            'has_governance': 'on',
            'has_esms': 'on',
            'capital': '1000000',
            'npl_pct': '4',
            'par90_pct': '6',
            'facility_amount': '5000000',
            'tenor_months': '36',
            'facility_purpose': 'wc_onlending',
            'end_user_rate_ceiling_pct': '11',
        })
        if saved.status_code == 200 and saved.context and saved.context.get('form'):
            self.fail(saved.context['form'].errors)
        app.refresh_from_db()
        profile = PfiInstitutionProfile.objects.get(loan_request=app.loan_request)
        self.assertEqual(profile.institution_name, 'Awash Bank')
        self.assertEqual(profile.par90_pct, Decimal('6'))

    def test_promoter_fills_project_file(self):
        self.client.post(reverse('applicant_portal:register') + '?kind=promoter', {
            'actor_kind': ApplicantAccount.ACTOR_PROMOTER,
            'institution_name': 'Mill Co',
            'full_name': 'Hagos Promoter',
            'phone_number': '0911000400',
            'password': self.password,
            'password_confirm': self.password,
            'accept_terms': 'on',
        })
        self.client.post(reverse('applicant_portal:apply_start'))
        app = OnlineApplication.objects.get()
        acct = ApplicantAccount.objects.get(phone_number='0911000400')
        details = self.client.post(reverse('applicant_portal:apply_details', args=[app.public_id]), {
            'applicant_name': 'Mill Co',
            'phone_number': acct.phone_number,
            'customer_number': acct.customer_number,
            'customer_history': 'new',
            'category': self.project.id,
            'collateral': self.collateral.id,
            'district': self.district.id,
            'branch': self.branch.id,
            'amount_requested': '2000000',
            'reason': 'Agro-processing mill.',
        })
        if details.status_code == 200:
            self.fail(details.context['form'].errors)
        self.assertEqual(details.status_code, 302)
        page = self.client.get(reverse('applicant_portal:apply_product', args=[app.public_id]))
        self.assertContains(page, 'Project file')
        saved = self.client.post(reverse('applicant_portal:apply_product', args=[app.public_id]), {
            'project_title': 'Sesame mill',
            'sector': 'industry',
            'location': 'Humera',
            'implementation_months': '18',
            'grace_months': '12',
            'debt_equity_policy': '75_25',
            'total_project_cost': '100000',
            'promoter_equity': '25000',
            'requested_debt': '75000',
            'equity_plan': 'lump',
        })
        if saved.status_code == 200 and saved.context and saved.context.get('form'):
            self.fail(saved.context['form'].errors)
        profile = ProjectProfile.objects.get(loan_request=OnlineApplication.objects.get().loan_request)
        self.assertEqual(profile.project_title, 'Sesame mill')
