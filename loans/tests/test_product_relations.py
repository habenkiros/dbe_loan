"""District→branch, fund eligibility, product desks, collateral by loan type."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from loans.engines import get_engine
from loans.models import (
    Branch,
    CollateralType,
    District,
    FinancingFund,
    LoanCategory,
    LoanRequest,
)
from loans.product_family import FAMILY_GENERAL, FAMILY_LEASE, FAMILY_PROJECT, FAMILY_WHOLESALE
from loans.registration import collateral_for_category, funds_for_category


User = get_user_model()


class ProductRelationTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='Rel Dist')
        self.other_district = District.objects.create(name='Other Dist')
        self.branch = Branch.objects.create(name='Rel Branch', district=self.district)
        self.other_branch = Branch.objects.create(name='Other Branch', district=self.other_district)
        self.land = CollateralType.objects.create(name='Rel Land')
        self.machine = CollateralType.objects.create(name='Rel Machine')
        self.own = FinancingFund.objects.create(
            code='OWNREL', name='Own book rel', kind=FinancingFund.KIND_OWN,
        )
        self.kfw = FinancingFund.objects.create(
            code='KFWREL', name='KfW rel', kind=FinancingFund.KIND_DONOR,
        )
        self.general = LoanCategory.objects.create(
            name='MSME Rel', appraisal_mode='msme', product_family=FAMILY_GENERAL,
        )
        self.project = LoanCategory.objects.create(
            name='Project Rel', appraisal_mode=FAMILY_PROJECT, product_family=FAMILY_PROJECT,
        )
        self.wholesale = LoanCategory.objects.create(
            name='Wholesale Rel', appraisal_mode=FAMILY_WHOLESALE, product_family=FAMILY_WHOLESALE,
        )
        self.lease = LoanCategory.objects.create(
            name='Lease Rel', appraisal_mode=FAMILY_LEASE, product_family=FAMILY_LEASE,
        )
        self.project.allowed_collateral.add(self.land)
        self.lease.allowed_collateral.add(self.machine)
        self.wholesale.allowed_funds.add(self.kfw)
        self.officer = User.objects.create_user(
            username='rel_clo', password='pass', phone_number='0911888222',
            role='credit_loan_officer', branch=self.branch, district=self.district,
        )

    def test_unrestricted_fund_is_universal_donor_is_not(self):
        own_ids = set(funds_for_category(self.general).values_list('id', flat=True))
        self.assertIn(self.own.id, own_ids)
        self.assertNotIn(self.kfw.id, own_ids)
        wholesale_ids = set(funds_for_category(self.wholesale).values_list('id', flat=True))
        self.assertIn(self.own.id, wholesale_ids)
        self.assertIn(self.kfw.id, wholesale_ids)

    def test_collateral_restricted_to_loan_type(self):
        project_ids = set(collateral_for_category(self.project).values_list('id', flat=True))
        self.assertEqual(project_ids, {self.land.id})
        general_ids = set(collateral_for_category(self.general).values_list('id', flat=True))
        self.assertIn(self.land.id, general_ids)
        self.assertIn(self.machine.id, general_ids)

    def test_credit_create_requires_district_then_its_branch(self):
        client = Client()
        client.force_login(self.officer)
        bad = client.post(reverse('create_loan_request'), {
            'applicant_name': 'Wrong Geo',
            'phone_number': '0911555111',
            'category': self.general.id,
            'collateral': self.land.id,
            'amount_requested': '10000',
            'reason': 'WC',
            'customer_history': 'new',
            'customer_number': '2000050041',
            'district': self.district.id,
            'branch': self.other_branch.id,
        })
        self.assertEqual(bad.status_code, 200)
        self.assertFalse(LoanRequest.objects.filter(applicant_name='Wrong Geo').exists())

        ok = client.post(reverse('create_loan_request'), {
            'applicant_name': 'Right Geo',
            'phone_number': '0911555112',
            'category': self.general.id,
            'collateral': self.land.id,
            'amount_requested': '10000',
            'reason': 'WC',
            'customer_history': 'new',
            'customer_number': '2000050041',
            'district': self.district.id,
            'branch': self.branch.id,
        })
        self.assertEqual(ok.status_code, 302)
        loan = LoanRequest.objects.get(applicant_name='Right Geo')
        self.assertEqual(loan.district_id, self.district.id)
        self.assertEqual(loan.branch_id, self.branch.id)

    def test_kfw_rejected_on_msme_product(self):
        client = Client()
        client.force_login(self.officer)
        resp = client.post(reverse('create_loan_request'), {
            'applicant_name': 'MSME KfW',
            'phone_number': '0911555113',
            'category': self.general.id,
            'collateral': self.land.id,
            'financing_fund': self.kfw.id,
            'amount_requested': '10000',
            'reason': 'WC',
            'customer_history': 'new',
            'customer_number': '2000050041',
            'district': self.district.id,
            'branch': self.branch.id,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(LoanRequest.objects.filter(applicant_name='MSME KfW').exists())

    def test_lease_rejects_land_collateral(self):
        client = Client()
        client.force_login(self.officer)
        resp = client.post(reverse('create_loan_request'), {
            'applicant_name': 'Lease Land',
            'phone_number': '0911555114',
            'category': self.lease.id,
            'collateral': self.land.id,
            'amount_requested': '900000',
            'reason': 'CNC',
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
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(LoanRequest.objects.filter(applicant_name='Lease Land').exists())

    def test_ajax_branches_follow_district(self):
        client = Client()
        client.force_login(self.officer)
        resp = client.get(
            reverse('ajax_staff_registration_options'),
            {'district_id': self.district.id, 'category_id': self.wholesale.id},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        branch_ids = {row['id'] for row in data['branches']}
        self.assertIn(self.branch.id, branch_ids)
        self.assertNotIn(self.other_branch.id, branch_ids)
        fund_ids = {row['id'] for row in data['funds']}
        self.assertIn(self.kfw.id, fund_ids)
        self.assertIn(self.own.id, fund_ids)

    def test_project_appraisal_opens_project_desk(self):
        loan = LoanRequest.objects.create(
            loan_request_id='LR-REL-P',
            applicant_name='Desk Co',
            phone_number='0911555115',
            amount_requested=Decimal('1000000'),
            reason='Plant',
            category=self.project,
            branch=self.branch,
            district=self.district,
            collateral=self.land,
            assigned_loan_officer=self.officer,
        )
        self.assertFalse(get_engine(loan).requires_appraisal_sheets())
        client = Client()
        client.force_login(self.officer)
        resp = client.get(reverse('loan_appraisal_edit', args=[loan.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('project_file', args=[loan.id]))
