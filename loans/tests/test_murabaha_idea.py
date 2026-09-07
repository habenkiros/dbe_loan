"""Phase E — Murabaha cost-plus + idea cap table. Consumer skipped. DECSI general ungated."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from loans.engines import IdeaEngine, MurabahaEngine, get_engine
from loans.idea_overlay import idea_committee_blockers, idea_disbursement_blockers
from loans.models import (
    Branch,
    CapTableEntry,
    CollateralType,
    District,
    IdeaProfile,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
    LoanRequestBasicInfo,
    MurabahaContract,
    ShariaReview,
)
from loans.murabaha_overlay import murabaha_committee_blockers, murabaha_disbursement_blockers
from loans.product_family import FAMILY_GENERAL, FAMILY_IDEA_EQUITY, FAMILY_IFB_MURABAHA
from loans.views import _generate_amortization_schedule


User = get_user_model()


class MurabahaIdeaTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='EI Dist')
        self.branch = Branch.objects.create(name='EI Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='EI Coll')
        self.officer = User.objects.create_user(
            username='ei_lo', password='pass', phone_number='0911222111', role='loan_officer',
        )
        self.general = LoanCategory.objects.create(
            name='EI MSME', appraisal_mode='msme', product_family=FAMILY_GENERAL,
        )
        self.mur_cat = LoanCategory.objects.create(
            name='EI Murabaha', appraisal_mode='corporate', product_family=FAMILY_IFB_MURABAHA,
        )
        self.idea_cat = LoanCategory.objects.create(
            name='EI Idea', appraisal_mode='corporate', product_family=FAMILY_IDEA_EQUITY,
        )

    def _loan(self, category, lid='LR-EI-1', **extra):
        defaults = dict(
            loan_request_id=lid,
            applicant_name='Venture Co',
            phone_number='0911000333',
            amount_requested=Decimal('2000000'),
            reason='Goods / idea',
            category=category,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
        )
        defaults.update(extra)
        return LoanRequest.objects.create(**defaults)

    def test_general_ungated(self):
        loan = self._loan(self.general, lid='LR-EI-G')
        self.assertEqual(get_engine(loan).committee_blockers(), [])
        self.assertEqual(get_engine(loan).disbursement_blockers(), [])
        self.assertIsNone(get_engine(loan).file_summary())

    def test_murabaha_blocked_without_contract(self):
        loan = self._loan(self.mur_cat, lid='LR-EI-NP')
        self.assertIsInstance(get_engine(loan), MurabahaEngine)
        self.assertTrue(any('Murabaha' in b or 'cost' in b.lower() for b in murabaha_committee_blockers(loan)))

    def test_project_scale_needs_ho_routing(self):
        loan = self._loan(self.mur_cat, lid='LR-EI-HO')
        MurabahaContract.objects.create(
            loan_request=loan,
            goods_description='Plant equipment',
            supplier_name='Gulf Capital Goods',
            supplier_offer_ref='OFF-120',
            tenor_months=24,
            cost_price=Decimal('12000000'),
            markup_pct=Decimal('8'),
            selling_price=Decimal('12960000'),
            routed_to_ifb_ho=False,
        )
        self.assertTrue(any('IFB Directorate' in b for b in murabaha_committee_blockers(loan)))

    def test_ready_murabaha_committee_ok_sharia_blocks_confirm(self):
        loan = self._loan(self.mur_cat, lid='LR-EI-OK')
        MurabahaContract.objects.create(
            loan_request=loan,
            goods_description='Export coffee',
            supplier_name='Jeddah Trading',
            supplier_offer_ref='OFF-200',
            tenor_months=12,
            cost_price=Decimal('2000000'),
            markup_pct=Decimal('6'),
            scope=MurabahaContract.SCOPE_EXPORT,
            selling_price=Decimal('2120000'),
            delivery_status=MurabahaContract.DELIVERY_RECEIVED,
        )
        self.assertEqual(murabaha_committee_blockers(loan), [])
        self.assertTrue(any('Sharia' in b for b in murabaha_disbursement_blockers(loan)))
        ShariaReview.objects.create(
            loan_request=loan, kind=ShariaReview.KIND_MURABAHA,
            status=ShariaReview.STATUS_CLEARED, note='Cost-plus cleared.',
            reviewed_at=timezone.now(), reviewed_by=self.officer,
        )
        self.assertEqual(murabaha_disbursement_blockers(loan), [])

    def test_ordered_goods_block_murabaha_release(self):
        loan = self._loan(self.mur_cat, lid='LR-EI-ORD')
        MurabahaContract.objects.create(
            loan_request=loan,
            goods_description='Spare parts',
            supplier_name='Jeddah Trading',
            supplier_offer_ref='OFF-9',
            tenor_months=12,
            cost_price=Decimal('500000'),
            markup_pct=Decimal('7'),
            selling_price=Decimal('535000'),
            delivery_status=MurabahaContract.DELIVERY_ORDERED,
        )
        ShariaReview.objects.create(
            loan_request=loan, kind=ShariaReview.KIND_MURABAHA,
            status=ShariaReview.STATUS_CLEARED, note='Cleared.',
            reviewed_at=timezone.now(), reviewed_by=self.officer,
        )
        self.assertEqual(murabaha_committee_blockers(loan), [])
        self.assertTrue(any('received' in b.lower() or 'sold' in b.lower() for b in murabaha_disbursement_blockers(loan)))

    def test_murabaha_does_not_generate_sheet7(self):
        loan = self._loan(self.mur_cat, lid='LR-EI-S7')
        appraisal = LoanAppraisal.objects.create(
            loan_request=loan, created_by=self.officer,
            recommendation='approve', amount_approved=Decimal('2000000'),
            term_approved_months=12, rate_approved=Decimal('12'),
        )
        basic = LoanRequestBasicInfo.objects.create(
            loan_request=loan, term_months=12, interest_rate=Decimal('12'),
        )
        _generate_amortization_schedule(appraisal, basic, loan)
        self.assertEqual(appraisal.amortization_entries.count(), 0)

    def test_officer_can_save_murabaha(self):
        loan = self._loan(self.mur_cat, lid='LR-EI-UI')
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get(reverse('murabaha_file', args=[loan.id])).status_code, 200)
        resp = self.client.post(reverse('murabaha_file', args=[loan.id]), {
            'goods_description': 'Spare parts',
            'supplier_name': 'Jeddah Trading',
            'supplier_offer_ref': 'OFF-18',
            'delivery_status': MurabahaContract.DELIVERY_ORDERED,
            'cost_price': '1500000',
            'markup_pct': '7',
            'scope': MurabahaContract.SCOPE_DOMESTIC,
            'tenor_months': '18',
            'notes': '',
        })
        self.assertEqual(resp.status_code, 302)
        loan.refresh_from_db()
        self.assertEqual(loan.murabaha.goods_description, 'Spare parts')
        self.assertEqual(loan.murabaha.selling_price, Decimal('1605000.00'))

    def test_idea_gates_block_committee(self):
        loan = self._loan(self.idea_cat, lid='LR-EI-IG')
        self.assertIsInstance(get_engine(loan), IdeaEngine)
        self.assertTrue(any('idea file' in b.lower() or 'gates' in b.lower() for b in idea_committee_blockers(loan)))
        IdeaProfile.objects.create(
            loan_request=loan, venture_name='Old Co', founded_year=2010,
            implements_in_ethiopia=False, proposed_dbe_share_pct=Decimal('0'),
        )
        blockers = idea_committee_blockers(loan)
        self.assertTrue(any('5 years' in b for b in blockers))
        self.assertTrue(any('Ethiopia' in b for b in blockers))
        self.assertTrue(any('IP' in b or 'MoLS' in b or 'label' in b for b in blockers))
        self.assertTrue(any('share' in b.lower() for b in blockers))

    def test_idea_ready_for_committee_needs_cap_table_to_release(self):
        loan = self._loan(self.idea_cat, lid='LR-EI-CAP')
        profile = IdeaProfile.objects.create(
            loan_request=loan,
            venture_name='Fresh Lab',
            founded_year=timezone.now().year - 2,
            implements_in_ethiopia=True,
            has_startup_label=True,
            proposed_dbe_share_pct=Decimal('20'),
        )
        self.assertEqual(idea_committee_blockers(loan), [])
        self.assertTrue(any('cap table' in b.lower() for b in idea_disbursement_blockers(loan)))
        CapTableEntry.objects.create(
            profile=profile, holder_name='Founder', role=CapTableEntry.ROLE_FOUNDER,
            share_pct=Decimal('80'),
        )
        CapTableEntry.objects.create(
            profile=profile, holder_name='DBE', role=CapTableEntry.ROLE_DBE,
            share_pct=Decimal('20'),
        )
        self.assertEqual(idea_disbursement_blockers(loan), [])

    def test_idea_does_not_generate_sheet7(self):
        loan = self._loan(self.idea_cat, lid='LR-EI-NS7')
        appraisal = LoanAppraisal.objects.create(
            loan_request=loan, created_by=self.officer,
            recommendation='approve', amount_approved=Decimal('500000'),
            term_approved_months=12, rate_approved=Decimal('0'),
        )
        basic = LoanRequestBasicInfo.objects.create(
            loan_request=loan, term_months=12, interest_rate=Decimal('0'),
        )
        _generate_amortization_schedule(appraisal, basic, loan)
        self.assertEqual(appraisal.amortization_entries.count(), 0)

    def test_officer_can_save_idea_and_cap_table(self):
        loan = self._loan(self.idea_cat, lid='LR-EI-IUI')
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get(reverse('idea_file', args=[loan.id])).status_code, 200)
        resp = self.client.post(reverse('idea_file', args=[loan.id]), {
            'venture_name': 'AgriBot',
            'founded_year': str(timezone.now().year - 1),
            'implements_in_ethiopia': 'on',
            'has_ip': 'on',
            'proposed_dbe_share_pct': '15',
            'sector': 'Agri-tech',
            'notes': '',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(loan.idea_profile.venture_name, 'AgriBot')
        resp = self.client.post(reverse('idea_add_cap_row', args=[loan.id]), {
            'holder_name': 'DBE',
            'role': CapTableEntry.ROLE_DBE,
            'share_pct': '15',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(loan.idea_profile.cap_table.filter(role=CapTableEntry.ROLE_DBE).exists())

    def test_general_cannot_open_murabaha_or_idea(self):
        loan = self._loan(self.general, lid='LR-EI-NO')
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get(reverse('murabaha_file', args=[loan.id])).status_code, 302)
        self.assertEqual(self.client.get(reverse('idea_file', args=[loan.id])).status_code, 302)
