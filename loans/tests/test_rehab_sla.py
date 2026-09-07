"""Phase F — named rehab path + 45-day SLA. DECSI general not forced onto a stage."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from loans.book_ops import set_watchlist
from loans.engines import get_engine
from loans.models import (
    Branch,
    CollateralType,
    District,
    InsurancePolicy,
    LoanAppeal,
    LoanCategory,
    LoanRequest,
    RehabCase,
)
from loans.product_family import FAMILY_GENERAL, FAMILY_PROJECT
from loans.rehab import (
    TARGET_DAYS,
    can_move_rehab,
    get_rehab_case,
    postbook_summary,
    set_rehab_stage,
    sla_clock,
)


User = get_user_model()


class RehabSlaTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='RF Dist')
        self.branch = Branch.objects.create(name='RF Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='RF Coll')
        self.officer = User.objects.create_user(
            username='rf_lo', password='pass', phone_number='0911222666', role='loan_officer',
        )
        self.credit_head = User.objects.create_user(
            username='rf_ch', password='pass', phone_number='0911222667', role='credit_head',
        )
        self.general = LoanCategory.objects.create(
            name='RF MSME', appraisal_mode='msme', product_family=FAMILY_GENERAL,
        )
        self.project_cat = LoanCategory.objects.create(
            name='RF Project', appraisal_mode='corporate', product_family=FAMILY_PROJECT,
        )

    def _loan(self, category, lid='LR-RF-1', **extra):
        defaults = dict(
            loan_request_id=lid,
            applicant_name='Mill Co',
            phone_number='0911000888',
            amount_requested=Decimal('500000'),
            reason='Plant',
            category=category,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
        )
        defaults.update(extra)
        return LoanRequest.objects.create(**defaults)

    def test_general_not_forced_into_rehab(self):
        loan = self._loan(self.general, lid='LR-RF-G')
        self.assertIsNone(get_rehab_case(loan))
        summary = postbook_summary(loan)
        self.assertFalse(summary['has_rehab'])
        self.assertEqual(get_engine(loan).committee_blockers(), [])
        self.assertEqual(get_engine(loan).disbursement_blockers(), [])

    def test_sla_is_informational_not_a_gate(self):
        loan = self._loan(
            self.general, lid='LR-RF-SLOW',
            date_requested=timezone.now() - timedelta(days=TARGET_DAYS + 10),
        )
        clock = sla_clock(loan)
        self.assertTrue(clock['breached'])
        self.assertEqual(clock['status'], 'breached')
        self.assertGreater(clock['elapsed_days'], TARGET_DAYS)
        self.assertEqual(get_engine(loan).committee_blockers(), [])

    def test_delayed_project_shows_breach_and_named_stage(self):
        loan = self._loan(
            self.project_cat, lid='LR-RF-P',
            date_requested=timezone.now() - timedelta(days=60),
        )
        set_watchlist(loan, self.officer, flagged=True, reason='Implementation slipped past grace.')
        loan.refresh_from_db()
        case = get_rehab_case(loan)
        self.assertIsNotNone(case)
        self.assertEqual(case.stage, RehabCase.STAGE_WATCHLIST)
        clock = sla_clock(loan)
        self.assertTrue(clock['breached'])
        self.assertEqual(clock['status_label'], 'SLA breach')

        client = Client()
        client.login(username='rf_lo', password='pass')
        project_page = client.get(reverse('project_file', args=[loan.id]))
        self.assertEqual(project_page.status_code, 200)
        self.assertContains(project_page, 'SLA breach')
        rehab_page = client.get(reverse('rehab_loan', args=[loan.id]))
        self.assertEqual(rehab_page.status_code, 200)
        self.assertContains(rehab_page, 'SLA breach')
        self.assertContains(rehab_page, 'Watchlist')

    def test_foreclosure_blocked_from_watchlist(self):
        loan = self._loan(self.project_cat, lid='LR-RF-FC')
        set_rehab_stage(loan, RehabCase.STAGE_WATCHLIST, self.officer, 'Early warning')
        ok, err = can_move_rehab(RehabCase.STAGE_WATCHLIST, RehabCase.STAGE_FORECLOSURE)
        self.assertFalse(ok)
        self.assertIn('last', err.lower())
        case, err = set_rehab_stage(loan, RehabCase.STAGE_FORECLOSURE, self.officer)
        self.assertIsNone(case)
        self.assertIn('last', err.lower())
        self.assertEqual(get_rehab_case(loan).stage, RehabCase.STAGE_WATCHLIST)

    def test_named_path_to_foreclosure(self):
        loan = self._loan(self.project_cat, lid='LR-RF-PATH')
        set_rehab_stage(loan, RehabCase.STAGE_WATCHLIST, self.officer)
        set_rehab_stage(loan, RehabCase.STAGE_RESTRUCTURE, self.officer, 'TA / reschedule first')
        set_rehab_stage(loan, RehabCase.STAGE_RECOVER, self.officer)
        case, err = set_rehab_stage(loan, RehabCase.STAGE_FORECLOSURE, self.officer, 'Last resort')
        self.assertIsNone(err)
        self.assertEqual(case.stage, RehabCase.STAGE_FORECLOSURE)
        self.assertEqual(case.events.count(), 4)

    def test_insurance_overdue_listed(self):
        loan = self._loan(self.general, lid='LR-RF-INS')
        InsurancePolicy.objects.create(
            loan_request=loan,
            insurer='Nile Insurance',
            dbe_co_beneficiary=True,
            expires_on=timezone.localdate() - timedelta(days=3),
        )
        overdue = postbook_summary(loan)['insurance_overdue']
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0].insurer, 'Nile Insurance')

    def test_appeal_president(self):
        loan = self._loan(self.general, lid='LR-RF-AP')
        client = Client()
        client.login(username='rf_lo', password='pass')
        resp = client.post(reverse('rehab_file_appeal', args=[loan.id]), {
            'level': LoanAppeal.LEVEL_PRESIDENT,
            'grounds': 'Committee declined despite a viable mill and equity already in.',
        })
        self.assertEqual(resp.status_code, 302)
        appeal = loan.appeals.get()
        self.assertEqual(appeal.level, LoanAppeal.LEVEL_PRESIDENT)
        self.assertEqual(appeal.status, LoanAppeal.STATUS_OPEN)
        client.logout()
        client.login(username='rf_ch', password='pass')
        client.post(reverse('rehab_decide_appeal', args=[loan.id, appeal.id]), {
            'action': LoanAppeal.STATUS_UPHELD,
            'decision_note': 'Return to committee with a new amount.',
        })
        appeal.refresh_from_db()
        self.assertEqual(appeal.status, LoanAppeal.STATUS_UPHELD)

    def test_workout_opens_restructure_not_foreclosure(self):
        loan = self._loan(
            self.general, lid='LR-RF-WO',
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            disbursement_status=LoanRequest.DISBURSE_DISBURSED,
            disbursed_at=timezone.now(),
        )
        client = Client()
        client.login(username='rf_lo', password='pass')
        client.post(reverse('collections_workout', args=[loan.id]), {
            'action': 'request',
            'workout_note': 'Reschedule remaining term after a crop failure.',
        })
        loan.refresh_from_db()
        self.assertEqual(loan.workout_status, LoanRequest.WORKOUT_REQUESTED)
        self.assertEqual(get_rehab_case(loan).stage, RehabCase.STAGE_RESTRUCTURE)
