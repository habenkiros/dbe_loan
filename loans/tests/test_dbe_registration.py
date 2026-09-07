"""Staff registration follows the DBE product family, not a single CBS form."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from loans.models import (
    Branch,
    CollateralType,
    District,
    LeaseAssetProfile,
    LoanCategory,
    LoanRequest,
    PfiInstitutionProfile,
    ProjectProfile,
)
from loans.product_family import FAMILY_GENERAL, FAMILY_LEASE, FAMILY_PROJECT, FAMILY_WHOLESALE
from loans.registration import party_for_family, requires_cbs_customer

User = get_user_model()


class DbeRegistrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.district = District.objects.create(name='Reg Dist')
        self.branch = Branch.objects.create(name='Reg Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='Reg Coll')
        self.general = LoanCategory.objects.create(
            name='MSME Trade Reg', appraisal_mode='msme', product_family=FAMILY_GENERAL,
        )
        self.project = LoanCategory.objects.create(
            name='Project Financing Reg', appraisal_mode='corporate', product_family=FAMILY_PROJECT,
        )
        self.wholesale = LoanCategory.objects.create(
            name='Wholesale PFI Reg', appraisal_mode='corporate', product_family=FAMILY_WHOLESALE,
        )
        self.lease = LoanCategory.objects.create(
            name='Lease Financing Reg', appraisal_mode='msme', product_family=FAMILY_LEASE,
        )
        self.project.allowed_collateral.add(self.collateral)
        self.lease.allowed_collateral.add(self.collateral)
        self.officer = User.objects.create_user(
            username='reg_clo', password='pass', phone_number='0911888111',
            role='credit_loan_officer', branch=self.branch, district=self.district,
        )

    def test_party_rules(self):
        self.assertTrue(requires_cbs_customer(FAMILY_GENERAL))
        self.assertFalse(requires_cbs_customer(FAMILY_PROJECT))
        self.assertFalse(requires_cbs_customer(FAMILY_WHOLESALE))
        self.assertEqual(party_for_family(FAMILY_WHOLESALE), 'institution')
        self.assertEqual(party_for_family(FAMILY_PROJECT), 'promoter')

    def test_create_form_lists_product_families(self):
        self.client.force_login(self.officer)
        resp = self.client.get(reverse('create_loan_request'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Project Financing Reg — Project financing')
        self.assertContains(resp, 'Wholesale PFI Reg — Wholesale / PFI facility')
        self.assertContains(resp, 'Loan-type details')
        self.assertContains(resp, 'id_district')
        self.assertContains(resp, 'Select district')

    def test_project_registration_opens_project_file(self):
        self.client.force_login(self.officer)
        resp = self.client.post(reverse('create_loan_request'), {
            'applicant_name': 'Horizon Agro Plc',
            'phone_number': '0911555001',
            'category': self.project.id,
            'collateral': self.collateral.id,
            'amount_requested': '8000000',
            'reason': 'Agro-processing plant',
            'customer_history': 'new',
            'district': self.district.id,
            'branch': self.branch.id,
            'intake_project-project_title': 'Horizon mill',
            'intake_project-sector': 'agriculture',
            'intake_project-location': 'Adama',
            'intake_project-debt_equity_policy': '75_25',
            'intake_project-total_project_cost': '10000000',
            'intake_project-promoter_equity': '2500000',
            'intake_project-requested_debt': '7500000',
            'intake_project-equity_plan': 'lump',
        })
        self.assertEqual(resp.status_code, 302)
        loan = LoanRequest.objects.get(applicant_name='Horizon Agro Plc')
        self.assertEqual(loan.category_id, self.project.id)
        self.assertTrue(ProjectProfile.objects.filter(loan_request=loan, project_title='Horizon mill').exists())
        self.assertEqual(resp.url, reverse('project_file', args=[loan.id]))

    def test_wholesale_registration_skips_customer_number(self):
        self.client.force_login(self.officer)
        resp = self.client.post(reverse('create_loan_request'), {
            'applicant_name': 'Tsehay MFI',
            'phone_number': '0911555002',
            'category': self.wholesale.id,
            'amount_requested': '20000000',
            'reason': 'MSME on-lending facility',
            'customer_history': 'existing',
            'district': self.district.id,
            'branch': self.branch.id,
            'intake_wholesale-institution_name': 'Tsehay MFI',
            'intake_wholesale-kind': 'mfi',
            'intake_wholesale-license_number': 'NBE-88',
            'intake_wholesale-facility_amount': '20000000',
            'intake_wholesale-tenor_months': '36',
            'intake_wholesale-facility_purpose': 'wc_onlending',
        })
        self.assertEqual(resp.status_code, 302, resp.content[:500] if resp.status_code == 200 else '')
        loan = LoanRequest.objects.get(applicant_name='Tsehay MFI')
        profile = PfiInstitutionProfile.objects.get(loan_request=loan)
        self.assertEqual(profile.license_number, 'NBE-88')
        self.assertEqual(resp.url, reverse('wholesale_file', args=[loan.id]))

    def test_lease_registration_saves_asset(self):
        self.client.force_login(self.officer)
        resp = self.client.post(reverse('create_loan_request'), {
            'applicant_name': 'Selam Garage',
            'phone_number': '0911555003',
            'category': self.lease.id,
            'collateral': self.collateral.id,
            'amount_requested': '900000',
            'reason': 'CNC hire-purchase',
            'customer_history': 'new',
            'district': self.district.id,
            'branch': self.branch.id,
            'intake_lease-supplier_name': 'Addis Machines',
            'intake_lease-is_new_goods': 'on',
            'intake_lease-asset_description': 'CNC lathe',
            'intake_lease-asset_price': '900000',
            'intake_lease-lessee_contribution': '200000',
            'intake_lease-bank_holds_title': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        loan = LoanRequest.objects.get(applicant_name='Selam Garage')
        asset = LeaseAssetProfile.objects.get(loan_request=loan)
        self.assertEqual(asset.supplier_name, 'Addis Machines')
        self.assertEqual(resp.url, reverse('lease_file', args=[loan.id]))
