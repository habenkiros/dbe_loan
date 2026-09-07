"""DBE spine: KYC gate, CRM appraisal rounds, Pend, consumer desk."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from loans.committee import officer_can_submit_to_committee, try_finalize_level_decision
from loans.consumer_overlay import (
    MAX_DTI_PCT,
    consumer_committee_blockers,
    dti_pct,
    ltv_pct,
)
from loans.crm_cycle import (
    crm_committee_blockers,
    crm_is_cleared,
    crm_respond,
    send_pack_to_crm,
)
from loans.engines import ConsumerEngine, get_engine
from loans.kyc_desk import (
    complete_checklist_payload,
    ensure_intake_screenings,
    kyc_committee_blockers,
    kyc_is_complete,
    set_screening_status,
)
from loans.models import (
    AppraisalCrmRound,
    Branch,
    CollateralType,
    ConsumerProfile,
    CreditDeskScreening,
    District,
    LoanCategory,
    LoanCommitteeVote,
    LoanRequest,
)
from loans.product_family import FAMILY_CONSUMER, FAMILY_GENERAL, FAMILY_PROJECT


User = get_user_model()


class SpineAndConsumerTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='Spine Dist')
        self.branch = Branch.objects.create(name='Spine Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='Spine Coll')
        self.officer = User.objects.create_user(
            username='spine_clo', password='pass', phone_number='0911888001',
            role='credit_loan_officer',
        )
        self.crm = User.objects.create_user(
            username='spine_crm', password='pass', phone_number='0911888002',
            role='credit_head',
        )
        self.engineer = User.objects.create_user(
            username='spine_eng', password='pass', phone_number='0911888003',
            role='engineer',
        )
        self.legal = User.objects.create_user(
            username='spine_leg', password='pass', phone_number='0911888004',
            role='legal_officer',
        )
        self.project_cat = LoanCategory.objects.create(
            name='Spine Project', product_family=FAMILY_PROJECT, appraisal_mode=FAMILY_PROJECT,
        )
        self.general_cat = LoanCategory.objects.create(
            name='Spine MSME', product_family=FAMILY_GENERAL, appraisal_mode='msme',
        )
        self.consumer_cat = LoanCategory.objects.create(
            name='Spine Consumer', product_family=FAMILY_CONSUMER, appraisal_mode=FAMILY_CONSUMER,
        )

    def _loan(self, category, lid):
        return LoanRequest.objects.create(
            loan_request_id=lid,
            applicant_name='Spine Co',
            phone_number='0911000001',
            amount_requested=Decimal('500000'),
            reason='file',
            category=category,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
        )

    def _clear_kyc(self, loan):
        ensure_intake_screenings(loan)
        for desk in ('crm', 'engineering', 'legal'):
            set_screening_status(
                loan, desk, CreditDeskScreening.STATUS_CLEARED, self.officer, 'ok',
                checklist=complete_checklist_payload(desk, loan),
            )

    def test_general_skips_kyc_and_crm_gates(self):
        loan = self._loan(self.general_cat, 'LR-SP-G')
        self.assertEqual(kyc_committee_blockers(loan), [])
        self.assertEqual(crm_committee_blockers(loan), [])

    def test_project_cannot_submit_without_kyc(self):
        loan = self._loan(self.project_cat, 'LR-SP-K')
        check = officer_can_submit_to_committee(loan)
        self.assertFalse(check['ok'])
        self.assertTrue(any('KYC' in e for e in check['errors']))

    def test_project_cannot_submit_until_crm_clears_pack(self):
        loan = self._loan(self.project_cat, 'LR-SP-C')
        self._clear_kyc(loan)
        self.assertTrue(kyc_is_complete(loan))
        check = officer_can_submit_to_committee(loan)
        self.assertTrue(any('CRM' in e for e in check['errors']))
        send_pack_to_crm(loan, self.officer, 'Viability pack ready for CRM.')
        self.assertFalse(crm_is_cleared(loan))
        crm_respond(loan, self.crm, 'clear', 'Pack is complete.')
        self.assertTrue(crm_is_cleared(loan))
        self.assertEqual(crm_committee_blockers(loan), [])
        round_row = AppraisalCrmRound.objects.get(loan_request=loan)
        self.assertEqual(round_row.version, 1)
        self.assertEqual(round_row.status, AppraisalCrmRound.STATUS_CLEARED)

    def test_crm_return_opens_new_version(self):
        loan = self._loan(self.project_cat, 'LR-SP-R')
        self._clear_kyc(loan)
        send_pack_to_crm(loan, self.officer, 'First pack for comment.')
        crm_respond(loan, self.crm, 'return', 'Need NPV and DSCR on the pack.')
        send_pack_to_crm(loan, self.officer, 'Revised pack with NPV.')
        self.assertEqual(AppraisalCrmRound.objects.filter(loan_request=loan).count(), 2)
        latest = AppraisalCrmRound.objects.filter(loan_request=loan).order_by('-version').first()
        self.assertEqual(latest.version, 2)
        self.assertEqual(latest.status, AppraisalCrmRound.STATUS_WITH_CRM)

    def test_pend_keeps_file_in_committee(self):
        from loans.committee import start_approval_workflow
        from loans.models import ApprovalCommitteeLevel, ApprovalCommitteeMemberRule

        level, _ = ApprovalCommitteeLevel.objects.update_or_create(
            key='branch',
            defaults={
                'name': 'Branch Committee',
                'voter_scope': ApprovalCommitteeLevel.SCOPE_BRANCH,
                'sequence_order': 1,
                'is_active': True,
                'min_approvals_required': 2,
                'min_declines_required': 2,
            },
        )
        ApprovalCommitteeMemberRule.objects.filter(level=level).delete()
        ApprovalCommitteeMemberRule.objects.create(
            level=level,
            participant_type=ApprovalCommitteeMemberRule.PARTICIPANT_ROLE,
            role='credit_loan_officer',
        )
        loan = self._loan(self.general_cat, 'LR-SP-P')
        start_approval_workflow(loan)
        loan.refresh_from_db()
        LoanCommitteeVote.objects.create(
            loan_request=loan,
            approval_level=loan.current_approval_level,
            member=self.officer,
            vote=LoanCommitteeVote.VOTE_PEND,
            comments='Need more site evidence.',
        )
        try_finalize_level_decision(loan, loan.current_approval_level)
        loan.refresh_from_db()
        self.assertEqual(loan.committee_status, LoanRequest.COMMITTEE_PENDED)

    def test_consumer_desk_blocks_high_dti(self):
        loan = self._loan(self.consumer_cat, 'LR-SP-H')
        engine = get_engine(loan)
        self.assertIsInstance(engine, ConsumerEngine)
        self.assertFalse(engine.requires_appraisal_sheets())
        profile = ConsumerProfile.objects.create(
            loan_request=loan,
            purpose=ConsumerProfile.PURPOSE_HOUSING,
            employer_name='DBE HR',
            monthly_salary=Decimal('10000'),
            monthly_obligations=Decimal('6000'),
            asset_value=Decimal('1000000'),
        )
        self.assertEqual(dti_pct(profile), Decimal('60.00'))
        self.assertTrue(dti_pct(profile) > MAX_DTI_PCT)
        blockers = consumer_committee_blockers(loan)
        self.assertTrue(any('DTI' in b for b in blockers))
        profile.monthly_obligations = Decimal('3000')
        profile.save()
        self.assertEqual(dti_pct(profile), Decimal('30.00'))
        self.assertEqual(ltv_pct(loan, profile), Decimal('50.00'))
        self.assertEqual(consumer_committee_blockers(loan), [])
