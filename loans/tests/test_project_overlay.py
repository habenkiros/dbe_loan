"""DBE Phase 1 project overlay — DECSI general files stay ungated."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from loans.disbursement import (
    add_disbursement_tranche,
    disbursement_readiness,
    mark_disbursed,
    start_disbursement_track,
    verify_own_contribution,
)
from loans.models import (
    AppraisalAmortizationEntry,
    Branch,
    CollateralType,
    District,
    LoanAppraisal,
    LoanCategory,
    LoanRequest,
    LoanRequestBasicInfo,
    ProjectProfile,
    ProjectSourceUseLine,
)
from loans.product_family import FAMILY_GENERAL, FAMILY_PROJECT
from loans.project_overlay import (
    is_project_file,
    profile_blockers,
    project_disbursement_blockers,
    record_implementation_visit,
)


User = get_user_model()


class ProjectOverlayTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='PO Dist')
        self.branch = Branch.objects.create(name='PO Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='PO Collateral')
        self.officer = User.objects.create_user(
            username='po_officer', password='pass', phone_number='0911222991', role='loan_officer',
        )
        self.general = LoanCategory.objects.create(
            name='PO MSME', appraisal_mode='msme', product_family=FAMILY_GENERAL,
        )
        self.project_cat = LoanCategory.objects.create(
            name='PO Project', appraisal_mode='corporate', product_family=FAMILY_PROJECT,
        )

    def _loan(self, category, **extra):
        defaults = dict(
            loan_request_id='LR-PO-001',
            applicant_name='Plant Co',
            phone_number='0911000555',
            amount_requested=Decimal('80000'),
            reason='Factory',
            category=category,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
        )
        defaults.update(extra)
        return LoanRequest.objects.create(**defaults)

    def _approved(self, category, lid='LR-PO-010'):
        loan = self._loan(
            category,
            loan_request_id=lid,
            appraisal_completed_at=timezone.now(),
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            committee_final_amount=Decimal('80000'),
            require_collateral_restriction=False,
            require_agreement_signatures=False,
            customer_number='2001',
        )
        appraisal = LoanAppraisal.objects.create(
            loan_request=loan, created_by=self.officer,
            recommendation='approve', amount_approved=Decimal('80000'),
            term_approved_months=12, rate_approved=Decimal('12'),
        )
        LoanRequestBasicInfo.objects.create(loan_request=loan, term_months=12, interest_rate=Decimal('12'))
        AppraisalAmortizationEntry.objects.create(
            appraisal=appraisal, period_number=1, payment_amount=Decimal('80000'),
            principal=Decimal('80000'), interest=Decimal('0'), balance_after=Decimal('0'),
        )
        start_disbursement_track(loan)
        loan.schedule_confirmed_at = timezone.now()
        loan.save(update_fields=['schedule_confirmed_at'])
        return loan

    def _fill_balanced_profile(self, loan):
        profile = ProjectProfile.objects.create(
            loan_request=loan,
            project_title='Agro plant',
            sector=ProjectProfile.SECTOR_AGRI,
            total_project_cost=Decimal('100000'),
            promoter_equity=Decimal('25000'),
            requested_debt=Decimal('75000'),
            current_account_opened=True,
        )
        ProjectSourceUseLine.objects.create(
            profile=profile, side=ProjectSourceUseLine.SIDE_SOURCE,
            purpose=ProjectSourceUseLine.PURPOSE_PROMOTER, amount=Decimal('25000'),
        )
        ProjectSourceUseLine.objects.create(
            profile=profile, side=ProjectSourceUseLine.SIDE_SOURCE,
            purpose=ProjectSourceUseLine.PURPOSE_DBE, amount=Decimal('75000'),
        )
        ProjectSourceUseLine.objects.create(
            profile=profile, side=ProjectSourceUseLine.SIDE_USE,
            purpose=ProjectSourceUseLine.PURPOSE_CIVIL, amount=Decimal('60000'),
        )
        ProjectSourceUseLine.objects.create(
            profile=profile, side=ProjectSourceUseLine.SIDE_USE,
            purpose=ProjectSourceUseLine.PURPOSE_MACHINERY, amount=Decimal('40000'),
        )
        return profile

    def test_general_file_has_no_project_gates(self):
        loan = self._approved(self.general, lid='LR-PO-GEN')
        self.assertFalse(is_project_file(loan))
        self.assertEqual(project_disbursement_blockers(loan), [])
        readiness = disbursement_readiness(loan)
        self.assertFalse(any('project' in b.lower() or 'tranche' in b.lower() for b in readiness['blockers']))

    def test_project_file_blocked_without_profile(self):
        loan = self._approved(self.project_cat, lid='LR-PO-NP')
        self.assertTrue(is_project_file(loan))
        self.assertTrue(profile_blockers(loan))
        blockers = project_disbursement_blockers(loan)
        self.assertTrue(any('project file' in b.lower() or 'title' in b.lower() for b in blockers))
        self.assertTrue(any('equity' in b.lower() for b in blockers))

    def test_first_draw_ok_after_profile_and_equity(self):
        loan = self._approved(self.project_cat, lid='LR-PO-1D')
        self._fill_balanced_profile(loan)
        verify_own_contribution(loan, self.officer, amount=Decimal('20000'), note='Promoter cash')
        blockers = project_disbursement_blockers(loan)
        self.assertEqual(blockers, [])

    def test_second_tranche_needs_implementation_visit(self):
        loan = self._approved(self.project_cat, lid='LR-PO-2T')
        self._fill_balanced_profile(loan)
        verify_own_contribution(loan, self.officer, amount=Decimal('20000'), note='Promoter cash')
        add_disbursement_tranche(loan, Decimal('30000'), note='civil', purpose_code='civil')
        add_disbursement_tranche(loan, Decimal('50000'), note='machinery', purpose_code='machinery')
        loan.disbursement_status = loan.DISBURSE_READY
        loan.finance_disbursement_approval = True
        loan.save(update_fields=['disbursement_status', 'finance_disbursement_approval'])
        ok, errors = mark_disbursed(loan, self.officer, notes='draw 1')
        self.assertTrue(ok, errors)
        loan.refresh_from_db()
        self.assertEqual(loan.disbursement_status, loan.DISBURSE_PARTIAL)
        first = loan.disbursement_tranches.get(sequence=1)
        first.utilization_note = 'Civil invoice paid, slab complete.'
        first.save(update_fields=['utilization_note'])
        blockers = project_disbursement_blockers(loan)
        self.assertTrue(any('implementation visit' in b.lower() for b in blockers))
        ok, errors = mark_disbursed(loan, self.officer, notes='too soon')
        self.assertFalse(ok)
        self.assertTrue(any('implementation visit' in e.lower() for e in errors))
        record_implementation_visit(
            loan, self.officer,
            notes='Civil slab complete, machinery on site.',
            visited_at=timezone.localdate(),
            percent_complete=Decimal('90'),
            purpose_code='civil',
            unlocks_next_tranche=True,
        )
        self.assertEqual(project_disbursement_blockers(loan), [])
        ok, errors = mark_disbursed(loan, self.officer, notes='draw 2')
        self.assertTrue(ok, errors)
        loan.refresh_from_db()
        self.assertEqual(loan.disbursement_status, loan.DISBURSE_DISBURSED)
        visit = loan.monitoring_visits.first()
        self.assertIsNotNone(visit.unlocked_tranche_id)

    def test_low_progress_blocks_next_draw(self):
        loan = self._approved(self.project_cat, lid='LR-PO-LOW')
        self._fill_balanced_profile(loan)
        verify_own_contribution(loan, self.officer, amount=Decimal('20000'), note='Promoter cash')
        add_disbursement_tranche(loan, Decimal('30000'), note='civil', purpose_code='civil')
        add_disbursement_tranche(loan, Decimal('50000'), note='machinery', purpose_code='machinery')
        loan.disbursement_status = loan.DISBURSE_READY
        loan.finance_disbursement_approval = True
        loan.save(update_fields=['disbursement_status', 'finance_disbursement_approval'])
        ok, errors = mark_disbursed(loan, self.officer, notes='draw 1')
        self.assertTrue(ok, errors)
        first = loan.disbursement_tranches.get(sequence=1)
        first.utilization_note = 'Slab started only.'
        first.save(update_fields=['utilization_note'])
        record_implementation_visit(
            loan, self.officer,
            notes='Works barely started.',
            visited_at=timezone.localdate(),
            percent_complete=Decimal('20'),
            purpose_code='civil',
            unlocks_next_tranche=True,
        )
        blockers = project_disbursement_blockers(loan)
        self.assertTrue(any('progress' in b.lower() or 'facility' in b.lower() for b in blockers))
        ok, errors = mark_disbursed(loan, self.officer, notes='too much vs progress')
        self.assertFalse(ok)

    def test_officer_can_open_and_save_project_file(self):
        loan = self._loan(self.project_cat, loan_request_id='LR-PO-UI')
        self.client.force_login(self.officer)
        resp = self.client.get(reverse('project_file', args=[loan.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'DBE project financing')
        self.assertContains(resp, 'Cost &amp; equity')
        self.assertContains(resp, 'Plant desks')
        resp = self.client.post(reverse('project_file', args=[loan.id]), {
            'project_title': 'Oil mill',
            'sector': ProjectProfile.SECTOR_INDUSTRY,
            'location': 'Mekelle',
            'implementation_months': '18',
            'grace_months': '12',
            'debt_equity_policy': ProjectProfile.DE_75_25,
            'total_project_cost': '100000',
            'promoter_equity': '25000',
            'requested_debt': '75000',
            'equity_plan': ProjectProfile.EQUITY_LUMP,
            'purpose_summary': 'New mill',
            'notes': '',
        })
        self.assertEqual(resp.status_code, 302)
        loan.refresh_from_db()
        self.assertEqual(loan.project_profile.project_title, 'Oil mill')
        resp = self.client.post(reverse('project_add_line', args=[loan.id]), {
            'side': 'source',
            'purpose': ProjectSourceUseLine.PURPOSE_PROMOTER,
            'amount': '25000',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(loan.project_profile.lines.count(), 1)

    def test_seed_lines_from_saved_profile(self):
        loan = self._loan(self.project_cat, loan_request_id='LR-PO-SEED')
        ProjectProfile.objects.create(
            loan_request=loan,
            project_title='Mill',
            total_project_cost=Decimal('100000'),
            promoter_equity=Decimal('25000'),
            requested_debt=Decimal('75000'),
        )
        self.client.force_login(self.officer)
        resp = self.client.post(reverse('project_seed_lines', args=[loan.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(loan.project_profile.lines.count(), 3)

    def test_general_file_cannot_open_project_page(self):
        loan = self._loan(self.general, loan_request_id='LR-PO-NO')
        self.client.force_login(self.officer)
        resp = self.client.get(reverse('project_file', args=[loan.id]))
        self.assertEqual(resp.status_code, 302)
