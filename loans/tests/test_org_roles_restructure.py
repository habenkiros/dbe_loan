"""Org roles restructure: Cooperative intake, Finance disbursement, Credit, scoping."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from loans.disbursement import (
    can_approve_finance_disbursement,
    can_mark_disbursed,
    finance_disbursement_queue_queryset,
)
from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanCategory,
    LoanRequest,
)
from loans.reporting import is_org_wide_reporter, reporting_base_queryset, report_scope_kind

User = get_user_model()


class OrgRolesRestructureTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='Org District')
        self.branch = Branch.objects.create(name='Org Branch', district=self.district)
        self.category = LoanCategory.objects.create(name='Org Cat')
        self.collateral = CollateralType.objects.create(name='Org Coll')

        self.coop = User.objects.create_user(
            username='coop1', password='pass', phone_number='0911000001',
            role='cooperative_manager',
        )
        self.fin = User.objects.create_user(
            username='fin1', password='pass', phone_number='0911000002',
            role='finance_manager',
        )
        self.credit_head = User.objects.create_user(
            username='chead', password='pass', phone_number='0911000003',
            role='credit_head',
        )
        self.credit_lo = User.objects.create_user(
            username='clo', password='pass', phone_number='0911000004',
            role='credit_loan_officer',
        )
        self.bm = User.objects.create_user(
            username='bm1', password='pass', phone_number='0911000005',
            role='branch_manager', branch=self.branch, district=self.district,
        )
        self.acct_br = User.objects.create_user(
            username='acctbr', password='pass', phone_number='0911000006',
            role='accountant', branch=self.branch, district=self.district,
        )
        self.acct_ho = User.objects.create_user(
            username='acctho', password='pass', phone_number='0911000007',
            role='accountant',
        )
        self.dlo = User.objects.create_user(
            username='dlo1', password='pass', phone_number='0911000008',
            role='loan_officer', district=self.district,
        )
        self.other_district = District.objects.create(name='Other District')
        self.other_branch = Branch.objects.create(name='Other Branch', district=self.other_district)

    def _loan(self, **kwargs):
        defaults = dict(
            loan_request_id='LR-ORG-1',
            applicant_name='Org Applicant',
            phone_number='0911222333',
            category=self.category,
            collateral=self.collateral,
            amount_requested=Decimal('100000'),
            reason='test',
            branch=self.branch,
            district=self.district,
            origin_level=LoanRequest.ORIGIN_BRANCH,
        )
        defaults.update(kwargs)
        return LoanRequest.objects.create(**defaults)

    def test_cooperative_only_intake_gate(self):
        loan = self._loan()
        self.assertFalse(loan.managers_queue_approved())
        loan.operation_manager_approval = True
        loan.finance_approval = False
        loan.save()
        loan.refresh_from_db()
        self.assertTrue(loan.queue_approved)
        self.assertEqual(loan.status, 'Approved')

    def test_ho_credit_loan_skips_cooperative(self):
        loan = self._loan(
            loan_request_id='LR-ORG-HO',
            origin_level=LoanRequest.ORIGIN_HEAD_OFFICE,
            operation_manager_approval=False,
        )
        loan.refresh_from_db()
        self.assertTrue(loan.managers_queue_approved())
        self.assertTrue(loan.queue_approved)
        self.assertTrue(loan.operation_manager_approval)

    def test_finance_disbursement_gate(self):
        loan = self._loan(
            loan_request_id='LR-ORG-DISB',
            operation_manager_approval=True,
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            disbursement_status=LoanRequest.DISBURSE_READY,
        )
        self.assertTrue(can_approve_finance_disbursement(self.fin, loan))
        self.assertFalse(can_mark_disbursed(self.bm, loan))
        qs = finance_disbursement_queue_queryset(self.fin)
        self.assertTrue(qs.filter(pk=loan.pk).exists())

        loan.finance_disbursement_approval = True
        loan.save(update_fields=['finance_disbursement_approval'])
        self.assertFalse(can_approve_finance_disbursement(self.fin, loan))
        self.assertTrue(can_mark_disbursed(self.bm, loan))

    def test_accountant_scoped_reports(self):
        self._loan(loan_request_id='LR-ORG-A1')
        self._loan(
            loan_request_id='LR-ORG-A2',
            branch=self.other_branch,
            district=self.other_district,
        )
        self.assertEqual(report_scope_kind(self.acct_br), 'branch')
        self.assertFalse(is_org_wide_reporter(self.acct_br))
        self.assertTrue(is_org_wide_reporter(self.acct_ho))
        ids = set(reporting_base_queryset(self.acct_br).values_list('loan_request_id', flat=True))
        self.assertIn('LR-ORG-A1', ids)
        self.assertNotIn('LR-ORG-A2', ids)

    def test_credit_head_can_open_committee_settings(self):
        client = Client()
        client.force_login(self.credit_head)
        resp = client.get(reverse('manage_approval_committees'))
        self.assertEqual(resp.status_code, 200)

    def test_cooperative_queue_access(self):
        client = Client()
        client.force_login(self.coop)
        resp = client.get(reverse('view_loan_requests_operation_manager'))
        self.assertEqual(resp.status_code, 200)

    def test_credit_lo_create_ho_loan(self):
        client = Client()
        client.force_login(self.credit_lo)
        resp = client.post(reverse('create_loan_request'), {
            'applicant_name': 'HO Client',
            'phone_number': '0911555666',
            'customer_number': '2000050041',
            'category': self.category.id,
            'collateral': self.collateral.id,
            'amount_requested': '2500000',
            'reason': 'HO credit facility',
            'customer_history': 'new',
            'district': self.branch.district_id,
            'branch': self.branch.id,
        })
        self.assertEqual(resp.status_code, 302)
        loan = LoanRequest.objects.get(applicant_name='HO Client')
        self.assertEqual(loan.origin_level, LoanRequest.ORIGIN_HEAD_OFFICE)
        self.assertTrue(loan.queue_approved)
        self.assertEqual(loan.assigned_loan_officer_id, self.credit_lo.id)

    def test_district_lo_sees_district_loans(self):
        from loans.views import (
            _loan_browse_queryset_for_user,
            _loan_requests_queryset_for_user,
        )

        assigned = self._loan(
            loan_request_id='LR-ORG-DLO',
            operation_manager_approval=True,
            assigned_loan_officer=self.dlo,
        )
        unassigned = self._loan(
            loan_request_id='LR-ORG-DLO2',
            operation_manager_approval=True,
            assigned_loan_officer=None,
        )
        personal = _loan_requests_queryset_for_user(self.dlo)
        self.assertTrue(personal.filter(pk=assigned.pk).exists())
        self.assertFalse(personal.filter(pk=unassigned.pk).exists())

        browse = _loan_browse_queryset_for_user(self.dlo, branch_id=str(self.branch.id))
        self.assertTrue(browse.filter(pk=unassigned.pk).exists())

    def test_credit_head_browses_branch_via_filter(self):
        from loans.views import (
            _loan_browse_queryset_for_user,
            _loan_requests_queryset_for_user,
        )

        branch_loan = self._loan(loan_request_id='LR-ORG-BR', origin_level=LoanRequest.ORIGIN_BRANCH)
        ho_loan = self._loan(
            loan_request_id='LR-ORG-HO',
            origin_level=LoanRequest.ORIGIN_HEAD_OFFICE,
            assigned_loan_officer=self.credit_lo,
        )
        personal = _loan_requests_queryset_for_user(self.credit_head)
        self.assertFalse(personal.filter(pk=branch_loan.pk).exists())
        self.assertFalse(personal.filter(pk=ho_loan.pk).exists())

        by_branch = _loan_browse_queryset_for_user(self.credit_head, branch_id=str(self.branch.id))
        self.assertTrue(by_branch.filter(pk=branch_loan.pk).exists())
        search_ho = _loan_browse_queryset_for_user(self.credit_head)
        self.assertTrue(search_ho.filter(pk=ho_loan.pk).exists())

    def test_credit_committee_role_not_in_active_choices(self):
        from loans.forms import ACTIVE_USER_ROLE_CHOICES

        keys = {k for k, _ in ACTIVE_USER_ROLE_CHOICES}
        self.assertNotIn('credit_committee', keys)
        self.assertIn('vp_operations', keys)
        self.assertIn('credit_head', keys)

    def test_departments_seeded_and_assignable(self):
        from loans.models import Department

        dept, _ = Department.objects.get_or_create(
            key=Department.KEY_CREDIT,
            defaults={'name': 'Credit', 'sort_order': 3},
        )
        self.credit_head.department = dept
        self.credit_head.save(update_fields=['department'])
        self.credit_head.refresh_from_db()
        self.assertEqual(self.credit_head.department.key, 'credit')
        su = User.objects.create_user(
            username='su_dept', password='pass', phone_number='0911999000',
            role='superadmin', is_superuser=True, is_staff=True,
        )
        client = Client()
        client.force_login(su)
        resp = client.get(reverse('manage_departments'))
        self.assertEqual(resp.status_code, 200)
