"""Phase D — lease asset register + Ijarah Sharia/rent. DECSI general stays ungated."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from loans.engines import IjarahEngine, LeaseEngine, get_engine
from loans.lease_overlay import (
    lease_committee_blockers,
    lease_disbursement_blockers,
)
from loans.models import (
    Branch,
    CollateralType,
    District,
    IjarahRentLine,
    LeaseAssetProfile,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
    LoanRequestBasicInfo,
    ShariaReview,
)
from loans.product_family import FAMILY_GENERAL, FAMILY_IFB_IJARAH, FAMILY_LEASE
from loans.views import _generate_amortization_schedule


User = get_user_model()


class LeaseIjarahTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='LS Dist')
        self.branch = Branch.objects.create(name='LS Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='LS Coll')
        self.officer = User.objects.create_user(
            username='ls_lo', password='pass', phone_number='0911222444', role='loan_officer',
        )
        self.general = LoanCategory.objects.create(
            name='LS MSME', appraisal_mode='msme', product_family=FAMILY_GENERAL,
        )
        self.lease_cat = LoanCategory.objects.create(
            name='LS Lease', appraisal_mode='msme', product_family=FAMILY_LEASE,
        )
        self.ijarah_cat = LoanCategory.objects.create(
            name='LS Ijarah', appraisal_mode='msme', product_family=FAMILY_IFB_IJARAH,
        )

    def _loan(self, category, lid='LR-LS-1', **extra):
        defaults = dict(
            loan_request_id=lid,
            applicant_name='Lessee Co',
            phone_number='0911000222',
            amount_requested=Decimal('2000000'),
            reason='Tractor',
            category=category,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
        )
        defaults.update(extra)
        return LoanRequest.objects.create(**defaults)

    def _ready_asset(self, loan, **extra):
        kwargs = dict(
            loan_request=loan,
            supplier_name='Kombolcha Works',
            asset_description='New tractor',
            is_new_goods=True,
            serial_number='TR-100',
            asset_price=Decimal('2000000'),
            lessee_contribution=Decimal('400000'),
            ancillary_amount=Decimal('200000'),
            price_checked=True,
            delivery_date=date(2026, 3, 1),
            insurance_in_force=True,
            bank_holds_title=True,
        )
        kwargs.update(extra)
        return LeaseAssetProfile.objects.create(**kwargs)

    def test_general_has_no_lease_gates(self):
        loan = self._loan(self.general, lid='LR-LS-G')
        self.assertEqual(get_engine(loan).committee_blockers(), [])
        self.assertEqual(get_engine(loan).disbursement_blockers(), [])
        self.assertIsNone(get_engine(loan).file_summary())

    def test_lease_blocked_without_register(self):
        loan = self._loan(self.lease_cat, lid='LR-LS-NP')
        self.assertIsInstance(get_engine(loan), LeaseEngine)
        blockers = lease_committee_blockers(loan)
        self.assertTrue(any('register' in b.lower() or 'asset' in b.lower() for b in blockers))

    def test_used_goods_and_low_contribution_block_committee(self):
        loan = self._loan(self.lease_cat, lid='LR-LS-POL')
        self._ready_asset(
            loan, is_new_goods=False, lessee_contribution=Decimal('100000'),
        )
        blockers = lease_committee_blockers(loan)
        self.assertTrue(any('new capital' in b.lower() for b in blockers))
        self.assertTrue(any('20%' in b for b in blockers))

    def test_ancillary_over_15_blocks(self):
        loan = self._loan(self.lease_cat, lid='LR-LS-AN')
        self._ready_asset(loan, ancillary_amount=Decimal('500000'))
        self.assertTrue(any('15%' in b for b in lease_committee_blockers(loan)))

    def test_ready_lease_committee_ok_but_draw_needs_identity_and_equity(self):
        loan = self._loan(self.lease_cat, lid='LR-LS-OK')
        self._ready_asset(loan, serial_number='', price_checked=False, delivery_date=None)
        self.assertEqual(lease_committee_blockers(loan), [])
        blockers = lease_disbursement_blockers(loan)
        self.assertTrue(any('serial' in b.lower() for b in blockers))
        self.assertTrue(any('Price-check' in b or 'price' in b.lower() for b in blockers))
        self.assertTrue(any('delivery' in b.lower() or 'commencement' in b.lower() for b in blockers))
        self.assertTrue(any('contribution' in b.lower() for b in blockers))

    def test_first_draw_ok_after_identity_and_verified_contribution(self):
        loan = self._loan(self.lease_cat, lid='LR-LS-1D')
        self._ready_asset(loan)
        loan.own_contribution_verified_at = timezone.now()
        loan.save(update_fields=['own_contribution_verified_at'])
        self.assertEqual(lease_disbursement_blockers(loan), [])

    def test_ijarah_needs_rent_and_sharia_to_confirm(self):
        loan = self._loan(self.ijarah_cat, lid='LR-LS-IJ')
        self.assertIsInstance(get_engine(loan), IjarahEngine)
        self.assertFalse(get_engine(loan).uses_conventional_schedule)
        profile = self._ready_asset(loan)
        loan.own_contribution_verified_at = timezone.now()
        loan.save(update_fields=['own_contribution_verified_at'])
        blockers = lease_disbursement_blockers(loan)
        self.assertTrue(any('rental' in b.lower() or 'rent' in b.lower() for b in blockers))
        self.assertTrue(any('Sharia' in b for b in blockers))
        profile.monthly_rent = Decimal('45000')
        profile.save(update_fields=['monthly_rent'])
        ShariaReview.objects.create(
            loan_request=loan, kind=ShariaReview.KIND_IJARAH,
            status=ShariaReview.STATUS_CLEARED, note='Contract reviewed.',
            reviewed_at=timezone.now(), reviewed_by=self.officer,
        )
        self.assertEqual(lease_disbursement_blockers(loan), [])

    def test_ijarah_does_not_generate_interest_sheet7(self):
        loan = self._loan(self.ijarah_cat, lid='LR-LS-S7')
        appraisal = LoanAppraisal.objects.create(
            loan_request=loan, created_by=self.officer,
            recommendation='approve', amount_approved=Decimal('2000000'),
            term_approved_months=24, rate_approved=Decimal('12'),
        )
        basic = LoanRequestBasicInfo.objects.create(
            loan_request=loan, term_months=24, interest_rate=Decimal('12'),
        )
        _generate_amortization_schedule(appraisal, basic, loan)
        self.assertEqual(appraisal.amortization_entries.count(), 0)

    def test_officer_can_open_and_save_lease_file(self):
        loan = self._loan(self.lease_cat, lid='LR-LS-UI')
        self.client.force_login(self.officer)
        resp = self.client.get(reverse('lease_file', args=[loan.id]))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(reverse('lease_file', args=[loan.id]), {
            'supplier_name': 'Hawassa Motors',
            'asset_description': 'Pickup',
            'is_new_goods': 'on',
            'serial_number': 'PK-9',
            'asset_price': '1500000',
            'lessee_contribution': '300000',
            'ancillary_amount': '100000',
            'price_checked': 'on',
            'delivery_date': '2026-04-01',
            'insurance_in_force': 'on',
            'bank_holds_title': 'on',
            'asset_status': LeaseAssetProfile.STATUS_ON_LEASE,
            'notes': '',
        })
        self.assertEqual(resp.status_code, 302)
        loan.refresh_from_db()
        self.assertEqual(loan.lease_asset.supplier_name, 'Hawassa Motors')

    def test_ijarah_officer_can_add_rent_and_sharia(self):
        loan = self._loan(self.ijarah_cat, lid='LR-LS-RJ')
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get(reverse('lease_file', args=[loan.id])).status_code, 200)
        resp = self.client.post(reverse('lease_add_rent', args=[loan.id]), {
            'period_number': '1',
            'rent_amount': '40000',
            'due_date': '2026-05-01',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(IjarahRentLine.objects.filter(profile__loan_request=loan).exists())
        resp = self.client.post(reverse('lease_sharia_review', args=[loan.id]), {
            'action': 'clear',
            'note': 'Board of scholars cleared the contract.',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            loan.sharia_reviews.filter(status=ShariaReview.STATUS_CLEARED).exists()
        )

    def test_general_cannot_open_lease_page(self):
        loan = self._loan(self.general, lid='LR-LS-NO')
        self.client.force_login(self.officer)
        resp = self.client.get(reverse('lease_file', args=[loan.id]))
        self.assertEqual(resp.status_code, 302)
