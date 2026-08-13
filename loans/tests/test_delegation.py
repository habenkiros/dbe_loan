"""Staff authority delegation (request → admin approve)."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from loans.committee import user_can_vote_at_level, _user_can_vote_as_member
from loans.delegation import (
    SCOPE_APPRAISAL,
    SCOPE_ASSIGN_OFFICER,
    SCOPE_COMMITTEE,
    SCOPE_COOPERATIVE,
    SCOPE_FINANCE,
    can_access_loan_as_officer,
    eligible_delegates_queryset,
    native_scopes_for,
    principals_for,
    user_can_manage_delegations,
    user_has_cooperative_authority,
)
from loans.forms_delegation import StaffDelegationForm
from loans.models import (
    ApprovalCommitteeLevel,
    ApprovalCommitteeMemberRule,
    Branch,
    CollateralType,
    District,
    LoanCategory,
    LoanRequest,
    StaffDelegation,
)

User = get_user_model()


class DelegationTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='Del District')
        self.branch = Branch.objects.create(name='Del Branch', district=self.district)
        self.category = LoanCategory.objects.create(name='Del Cat')
        self.collateral = CollateralType.objects.create(name='Del Coll')

        self.principal = User.objects.create_user(
            username='lo_principal', password='x', role='loan_officer',
            phone_number='0911000001', branch=self.branch, district=self.district,
        )
        self.delegate = User.objects.create_user(
            username='lo_delegate', password='x', role='branch_manager',
            phone_number='0911000002', branch=self.branch, district=self.district,
        )
        self.coop = User.objects.create_user(
            username='coop_p', password='x', role='cooperative_manager',
            phone_number='0911000003', branch=self.branch,
        )
        self.coop_cover = User.objects.create_user(
            username='coop_d', password='x', role='loan_officer',
            phone_number='0911000004', branch=self.branch,
        )
        self.admin = User.objects.create_user(
            username='del_admin', password='x', role='admin',
            phone_number='0911000005',
        )

        now = timezone.now()
        StaffDelegation.objects.create(
            principal=self.principal,
            delegate=self.delegate,
            scopes=[SCOPE_APPRAISAL, SCOPE_COMMITTEE],
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=3),
            created_by=self.principal,
            status=StaffDelegation.STATUS_APPROVED,
            is_active=True,
            reviewed_by=self.admin,
            reviewed_at=now,
        )
        StaffDelegation.objects.create(
            principal=self.coop,
            delegate=self.coop_cover,
            scopes=[SCOPE_COOPERATIVE],
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=3),
            created_by=self.coop,
            status=StaffDelegation.STATUS_APPROVED,
            is_active=True,
            reviewed_by=self.admin,
            reviewed_at=now,
        )

        self.loan = LoanRequest.objects.create(
            loan_request_id='HK-DEL00001',
            applicant_name='Del Applicant',
            phone_number='0911222333',
            category=self.category,
            collateral=self.collateral,
            amount_requested=Decimal('20000'),
            reason='test',
            branch=self.branch,
            district=self.district,
            status='Approved',
            queue_approved=True,
            operation_manager_approval=True,
            assigned_loan_officer=self.principal,
            committee_status=LoanRequest.COMMITTEE_PENDING,
        )

    def test_appraisal_delegate_can_access_loan(self):
        ok, p = can_access_loan_as_officer(self.delegate, self.loan)
        self.assertTrue(ok)
        self.assertEqual(p.id, self.principal.id)
        ok2, _ = can_access_loan_as_officer(self.coop_cover, self.loan)
        self.assertFalse(ok2)

    def test_cooperative_delegate_authority(self):
        self.assertFalse(user_has_cooperative_authority(self.delegate))
        self.assertTrue(user_has_cooperative_authority(self.coop_cover))
        self.assertTrue(user_has_cooperative_authority(self.coop))

    def test_committee_vote_via_delegation(self):
        level, _ = ApprovalCommitteeLevel.objects.update_or_create(
            key='branch',
            defaults={
                'name': 'Branch Committee',
                'voter_scope': ApprovalCommitteeLevel.SCOPE_BRANCH,
                'sequence_order': 1,
                'is_active': True,
                'min_approvals_required': 1,
                'min_declines_required': 1,
            },
        )
        ApprovalCommitteeMemberRule.objects.filter(level=level).delete()
        ApprovalCommitteeMemberRule.objects.create(
            level=level,
            participant_type=ApprovalCommitteeMemberRule.PARTICIPANT_USER,
            user=self.principal,
            is_active=True,
        )
        self.loan.current_approval_level = level
        self.loan.save(update_fields=['current_approval_level'])

        self.assertTrue(_user_can_vote_as_member(self.principal, self.loan, level))
        self.assertFalse(_user_can_vote_as_member(self.delegate, self.loan, level))
        self.assertTrue(user_can_vote_at_level(self.delegate, self.loan, level))
        self.assertEqual(
            [p.id for p in principals_for(self.delegate, SCOPE_COMMITTEE)],
            [self.principal.id],
        )

    def test_pending_request_grants_no_authority(self):
        now = timezone.now()
        cover = User.objects.create_user(
            username='pending_cover', password='x', role='loan_officer',
            phone_number='0911000099', branch=self.branch,
        )
        StaffDelegation.objects.create(
            principal=self.principal,
            delegate=cover,
            scopes=[SCOPE_APPRAISAL],
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=2),
            created_by=self.principal,
            status=StaffDelegation.STATUS_PENDING,
            is_active=False,
        )
        ok, _ = can_access_loan_as_officer(cover, self.loan)
        self.assertFalse(ok)

    def test_staff_request_admin_approve_signs_delegate(self):
        client = Client()
        client.force_login(self.principal)
        now = timezone.now()
        resp = client.post(reverse('manage_delegations'), {
            'delegate': self.coop_cover.id,
            'scopes': [SCOPE_APPRAISAL],
            'starts_at': (now - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M'),
            'ends_at': (now + timedelta(days=5)).strftime('%Y-%m-%dT%H:%M'),
            'reason': 'Leave cover',
        })
        self.assertEqual(resp.status_code, 302)
        d = StaffDelegation.objects.filter(
            principal=self.principal,
            delegate=self.coop_cover,
            status=StaffDelegation.STATUS_PENDING,
        ).latest('id')
        self.assertFalse(d.is_active)
        ok, _ = can_access_loan_as_officer(self.coop_cover, self.loan)
        self.assertFalse(ok)

        admin_client = Client()
        admin_client.force_login(self.admin)
        resp2 = admin_client.post(reverse('approve_delegation', args=[d.id]))
        self.assertEqual(resp2.status_code, 302)
        d.refresh_from_db()
        self.assertEqual(d.status, StaffDelegation.STATUS_APPROVED)
        self.assertTrue(d.is_active)
        self.assertEqual(d.reviewed_by_id, self.admin.id)
        ok2, p = can_access_loan_as_officer(self.coop_cover, self.loan)
        self.assertTrue(ok2)
        self.assertEqual(p.id, self.principal.id)

    def test_all_staff_can_manage_delegations(self):
        engineer = User.objects.create_user(
            username='eng_del', password='x', role='engineer',
            phone_number='0911000088', branch=self.branch,
        )
        accountant = User.objects.create_user(
            username='acc_del', password='x', role='accountant',
            phone_number='0911000089', branch=self.branch,
        )
        self.assertTrue(user_can_manage_delegations(self.principal))
        self.assertTrue(user_can_manage_delegations(self.delegate))
        self.assertTrue(user_can_manage_delegations(engineer))
        self.assertTrue(user_can_manage_delegations(accountant))

    def test_scopes_limited_to_permissions_held(self):
        # LO: appraisal only (unless on a committee)
        lo_scopes = set(native_scopes_for(self.principal))
        self.assertIn(SCOPE_APPRAISAL, lo_scopes)
        self.assertNotIn(SCOPE_FINANCE, lo_scopes)
        self.assertNotIn(SCOPE_ASSIGN_OFFICER, lo_scopes)
        self.assertNotIn(SCOPE_COOPERATIVE, lo_scopes)

        # BM: assign officer; not finance / coop / appraisal
        bm_scopes = set(native_scopes_for(self.delegate))
        self.assertIn(SCOPE_ASSIGN_OFFICER, bm_scopes)
        self.assertNotIn(SCOPE_FINANCE, bm_scopes)
        self.assertNotIn(SCOPE_APPRAISAL, bm_scopes)

        form = StaffDelegationForm(
            data={
                'delegate': self.coop_cover.id,
                'scopes': [SCOPE_FINANCE],
                'starts_at': timezone.now().strftime('%Y-%m-%dT%H:%M'),
                'ends_at': (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),
                'reason': 'try out of scope',
            },
            principal=self.principal,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('scopes', form.errors)

    def test_branch_manager_delegate_list_is_branch_only(self):
        other_district = District.objects.create(name='Other Dist')
        other_branch = Branch.objects.create(name='Other Branch', district=other_district)
        same_branch_user = User.objects.create_user(
            username='same_br', password='x', role='loan_officer',
            phone_number='0911000071', branch=self.branch, district=self.district,
        )
        other_branch_user = User.objects.create_user(
            username='other_br', password='x', role='loan_officer',
            phone_number='0911000072', branch=other_branch, district=other_district,
        )
        ids = set(eligible_delegates_queryset(self.delegate).values_list('id', flat=True))
        self.assertIn(same_branch_user.id, ids)
        self.assertIn(self.principal.id, ids)
        self.assertNotIn(other_branch_user.id, ids)
        self.assertNotIn(self.delegate.id, ids)

    def test_engineering_head_delegate_list_not_all_users(self):
        eng_head = User.objects.create_user(
            username='eng_head', password='x', role='engineering_head',
            phone_number='0911000060',
        )
        eng = User.objects.create_user(
            username='eng_a', password='x', role='engineer',
            phone_number='0911000061', branch=self.branch,
        )
        random_lo = User.objects.create_user(
            username='random_lo', password='x', role='loan_officer',
            phone_number='0911000062', branch=self.branch,
        )
        ids = set(eligible_delegates_queryset(eng_head).values_list('id', flat=True))
        self.assertIn(eng.id, ids)
        self.assertNotIn(random_lo.id, ids)
        self.assertNotIn(self.delegate.id, ids)

    def test_accountant_receives_assign_officer_access(self):
        from loans.delegation import user_has_assign_officer_authority, user_can_access_loan_for_assign
        from loans.views import _loan_requests_queryset_for_user, _user_can_view_loan_list

        accountant = User.objects.create_user(
            username='acc_assign', password='x', role='accountant',
            phone_number='0911000077', branch=self.branch, district=self.district,
        )
        now = timezone.now()
        StaffDelegation.objects.create(
            principal=self.delegate,  # branch manager
            delegate=accountant,
            scopes=[SCOPE_ASSIGN_OFFICER],
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=3),
            created_by=self.delegate,
            status=StaffDelegation.STATUS_APPROVED,
            is_active=True,
            reviewed_by=self.admin,
            reviewed_at=now,
        )
        self.assertTrue(user_has_assign_officer_authority(accountant))
        self.assertTrue(_user_can_view_loan_list(accountant))
        self.assertTrue(user_can_access_loan_for_assign(accountant, self.loan))
        ids = set(_loan_requests_queryset_for_user(accountant).values_list('id', flat=True))
        self.assertIn(self.loan.id, ids)

        client = Client()
        client.force_login(accountant)
        resp = client.get(reverse('assign_loan_officer', args=[self.loan.id]))
        self.assertEqual(resp.status_code, 200)
        resp_list = client.get(reverse('view_loan_requests'))
        self.assertEqual(resp_list.status_code, 200)

    def test_only_admin_can_revoke_approved_delegation(self):
        now = timezone.now()
        d = StaffDelegation.objects.create(
            principal=self.principal,
            delegate=self.delegate,
            scopes=[SCOPE_APPRAISAL],
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=2),
            created_by=self.principal,
            status=StaffDelegation.STATUS_APPROVED,
            is_active=True,
            reviewed_by=self.admin,
            reviewed_at=now,
        )
        client = Client()
        client.force_login(self.principal)
        resp = client.post(reverse('revoke_delegation', args=[d.id]))
        self.assertEqual(resp.status_code, 302)
        d.refresh_from_db()
        self.assertEqual(d.status, StaffDelegation.STATUS_APPROVED)
        self.assertTrue(d.is_active)

        admin_client = Client()
        admin_client.force_login(self.admin)
        resp2 = admin_client.post(reverse('revoke_delegation', args=[d.id]))
        self.assertEqual(resp2.status_code, 302)
        d.refresh_from_db()
        self.assertEqual(d.status, StaffDelegation.STATUS_REVOKED)
        self.assertFalse(d.is_active)
