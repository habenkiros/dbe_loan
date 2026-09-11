"""A–Z factory walkthrough rows on top of seed_sample_data loans.

Fills desks that a thin KYC-only sample never reaches: committee votes,
legal, agreements, disbursement, monitoring, collections, rehab, IFB,
Seqela Market, compliance, CRM, and a submitted Digital Apply file.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.utils import timezone


def seed_full_factory_tour(*, stdout, style, loans, users, geo):
    now = timezone.now()
    by_cn = {loan.customer_number: loan for loan in loans if loan.customer_number}

    _committee_votes(by_cn, users, now)
    _risk_and_crm(by_cn, users, now)
    _book_happy_path(by_cn.get('1010'), users, now)
    _project_depth(by_cn.get('3010'), users, now)
    _wholesale_util(by_cn.get('3011'), users)
    _collections_rehab(by_cn.get('4018'), users, now)
    _compliance_and_sanctions(by_cn, users, now)
    _collateral_photos(by_cn, users, now)
    _seqela_market(users, geo, now)
    _link_online_apply(by_cn.get('4019'))

    stdout.write(style.SUCCESS('  Factory tour desks filled'))
    _print_tour_map(stdout, style, by_cn)


def _print_tour_map(stdout, style, by_cn):
    rows = [
        ('Queue / MSME pending', '1001', 'Abebe Kebede'),
        ('Collateral + appraisal', '1004', 'Frehiwot Desta'),
        ('Committee (1 of 2 votes)', '1009', 'Hiwot Gebrehiwot'),
        ('Booked + agreement + disbursed', '1010', 'Yared Manufacturing'),
        ('Project + plant desks', '3010', 'Mekelle Cement Plant PLC'),
        ('Wholesale / PFI utilization', '3011', 'Tigray Microfinance S.C.'),
        ('Idea / cap table', '3012', 'Axum AgriTech Start-up'),
        ('Lease financing', '4013', 'Adwa Workshop Lease'),
        ('IFB Ijarah', '4014', 'Shire Ijarah Transport'),
        ('IFB Murabaha', '4015', 'Mekelle Murabaha Traders'),
        ('Consumer housing', '4016', 'Selam Housing Consumer'),
        ('External fund window', '4017', 'Youth Climate MSME'),
        ('Collections + rehab NPL', '4018', 'Wukro Collections Sample'),
        ('Digital Apply → Scan inbox', '4019', 'Portal Submitted Applicant'),
        ('Open AML / PEP case', '1011', 'Rediet Alemu'),
    ]
    stdout.write('')
    stdout.write(style.MIGRATE_HEADING('Walk the factory (open these files)'))
    for desk, cn, name in rows:
        loan = by_cn.get(cn)
        lid = loan.loan_request_id if loan else '(missing — re-seed)'
        stdout.write(f'  {desk:32} {lid:12}  {name}')
    stdout.write('  Seqela Market: dealers Mekelle Cement Depot / Adigrat Steel (portal 0912111901)')
    stdout.write('  Digital Apply extra: 0912111804 submitted · 0912111805 fee-paid')


def _committee_votes(by_cn, users, now):
    from loans.models import ApprovalCommitteeLevel, LoanCommitteeVote

    bm = users.get('bm1')
    acct = users.get('acct1')
    branch = ApprovalCommitteeLevel.objects.filter(
        key=ApprovalCommitteeLevel.LEVEL_BRANCH,
    ).first()
    if not branch:
        return

    pending = by_cn.get('1009')
    if pending and bm:
        LoanCommitteeVote.objects.get_or_create(
            loan_request=pending,
            member=bm,
            approval_level=branch,
            defaults={
                'vote': LoanCommitteeVote.VOTE_APPROVE,
                'amount_supported': pending.amount_requested,
                'comments': 'Clinic file is complete. Second vote still needed.',
                'voted_at': now - timedelta(hours=6),
            },
        )

    approved = by_cn.get('1010')
    if approved and bm and acct:
        for member, comment in (
            (bm, 'CNC acquisition approved at branch committee.'),
            (acct, 'Capacity and collateral coverage acceptable.'),
        ):
            LoanCommitteeVote.objects.get_or_create(
                loan_request=approved,
                member=member,
                approval_level=branch,
                defaults={
                    'vote': LoanCommitteeVote.VOTE_APPROVE,
                    'amount_supported': approved.amount_requested,
                    'comments': comment,
                    'voted_at': now - timedelta(days=4),
                },
            )


def _risk_and_crm(by_cn, users, now):
    from loans.crm_pack import default_crm_clear_note, default_crm_send_note
    from loans.models import AppraisalCrmRound, LoanRequest

    risk = users.get('risk')
    crm = users.get('credit_lo') or users.get('lo1')
    target = by_cn.get('1004')
    if target and risk:
        LoanRequest.objects.filter(pk=target.pk).update(
            risk_reviewed_at=now - timedelta(days=2),
            risk_reviewed_by=risk,
            risk_review_note='E&S screening clear. Coverage adequate for bakery machinery.',
        )
        target.refresh_from_db()
    if target and crm:
        AppraisalCrmRound.objects.get_or_create(
            loan_request=target,
            version=1,
            defaults={
                'status': AppraisalCrmRound.STATUS_CLEARED,
                'appraisal_note': 'Pack sent for CRM comment.',
                'crm_note': 'KYC and banking history consistent. Cleared for committee.',
                'sent_by': target.assigned_loan_officer,
                'sent_at': now - timedelta(days=3),
                'crm_by': crm,
                'crm_at': now - timedelta(days=2),
                'cleared_at': now - timedelta(days=2),
            },
        )

    # Product-desk demo files: modality pack cleared for CRM walkthrough.
    modality_cns = ('3010', '3011', '3012', '4013', '4014', '4015', '4016')
    for cn in modality_cns:
        loan = by_cn.get(cn)
        if loan is None or crm is None:
            continue
        officer = loan.assigned_loan_officer or crm
        AppraisalCrmRound.objects.get_or_create(
            loan_request=loan,
            version=1,
            defaults={
                'status': AppraisalCrmRound.STATUS_CLEARED,
                'appraisal_note': default_crm_send_note(loan),
                'crm_note': default_crm_clear_note(loan),
                'sent_by': officer,
                'sent_at': now - timedelta(days=2),
                'crm_by': crm,
                'crm_at': now - timedelta(days=1),
                'cleared_at': now - timedelta(days=1),
            },
        )
        if risk and not loan.risk_reviewed_at:
            LoanRequest.objects.filter(pk=loan.pk).update(
                risk_reviewed_at=now - timedelta(days=1),
                risk_reviewed_by=risk,
                risk_review_note='Product-desk demo — risk clear for committee walkthrough.',
            )


def _book_happy_path(loan, users, now):
    if loan is None:
        return
    from loans.models import (
        InsurancePolicy,
        LoanAgreement,
        LoanAgreementSignature,
        LoanDisbursementTranche,
        LoanMonitoringVisit,
        LoanRequest,
        RevaluationDiary,
    )

    legal = users.get('legal')
    officer = loan.assigned_loan_officer or users.get('lo2')
    bm = users.get('bm1')
    fin = users.get('fin')
    amount = loan.amount_requested

    LoanRequest.objects.filter(pk=loan.pk).update(
        legal_cleared_at=now - timedelta(days=2),
        legal_cleared_by=legal,
        legal_clearance_note='Stamp duty paid. Machinery pledge registered. Cleared for booking.',
        schedule_confirmed_at=now - timedelta(days=2),
        schedule_confirmed_by=fin,
        ready_for_disbursement_at=now - timedelta(days=1),
        ready_for_disbursement_by=fin,
        disbursement_status=LoanRequest.DISBURSE_DISBURSED,
        disbursed_at=now - timedelta(days=1),
        disbursed_by=fin,
        disbursement_notes='Single draw booked to CBS mock account.',
        cbs_loan_account='CBS-DEMO-1010',
        cbs_booked_at=now - timedelta(days=1),
        cbs_booking_status=LoanRequest.CBS_BOOK_MOCK,
    )
    loan.refresh_from_db()

    body = (
        f'Loan agreement for {loan.applicant_name} ({loan.loan_request_id}).\n'
        f'Amount ETB {amount}. Machinery pledge. Demo factory tour snapshot.'
    )
    digest = hashlib.sha256(body.encode()).hexdigest()
    agreement, _ = LoanAgreement.objects.get_or_create(
        loan_request=loan,
        kind=LoanAgreement.KIND_LOAN,
        defaults={
            'title': f'Loan agreement — {loan.applicant_name}',
            'body_text': body,
            'content_hash': digest,
            'status': LoanAgreement.STATUS_SIGNED,
            'require_borrower': True,
            'require_officer': True,
            'require_branch_manager': True,
            'generated_by': officer,
        },
    )
    if not agreement.content_hash:
        agreement.content_hash = digest
        agreement.body_text = agreement.body_text or body
        agreement.save(update_fields=['content_hash', 'body_text'])
    h = agreement.content_hash
    signers = [
        (LoanAgreementSignature.ROLE_BORROWER, loan.applicant_name, None, 'ID-YARED-1010'),
        (LoanAgreementSignature.ROLE_OFFICER, officer.get_full_name() if officer else 'Officer', officer, 'STAFF-LO'),
        (LoanAgreementSignature.ROLE_BRANCH_MANAGER, bm.get_full_name() if bm else 'Branch manager', bm, 'STAFF-BM'),
    ]
    for role, name, user, sid in signers:
        LoanAgreementSignature.objects.get_or_create(
            agreement=agreement,
            role=role,
            defaults={
                'signer_name': name,
                'typed_name': name,
                'signer_id_number': sid,
                'declaration_accepted': True,
                'signer_user': user,
                'signature_method': LoanAgreementSignature.METHOD_REMOTE_OTP,
                'content_hash_at_sign': h,
                'ip_address': '127.0.0.1',
                'user_agent': 'factory-tour-seed',
                'is_valid': True,
            },
        )
    agreement.refresh_status()
    agreement.save(update_fields=['status'])

    tranche, _ = LoanDisbursementTranche.objects.get_or_create(
        loan_request=loan,
        sequence=1,
        defaults={
            'amount': amount,
            'note': 'Full facility draw',
            'status': LoanDisbursementTranche.STATUS_DISBURSED,
            'purpose_code': 'machinery',
            'disbursed_at': now - timedelta(days=1),
            'disbursed_by': fin,
        },
    )
    if tranche.status != LoanDisbursementTranche.STATUS_DISBURSED:
        tranche.status = LoanDisbursementTranche.STATUS_DISBURSED
        tranche.disbursed_at = now - timedelta(days=1)
        tranche.disbursed_by = fin
        tranche.save()

    if not loan.monitoring_visits.exists():
        LoanMonitoringVisit.objects.create(
            loan_request=loan,
            visited_at=(now - timedelta(days=5)).date(),
            notes='Machine installed at industrial park. Production trial observed.',
            gps_lat=Decimal('13.49670000'),
            gps_lon=Decimal('39.47530000'),
            visit_kind=LoanMonitoringVisit.KIND_FOLLOWUP,
            recorded_by=officer,
        )

    InsurancePolicy.objects.get_or_create(
        loan_request=loan,
        policy_number='NIC-CNC-1010',
        defaults={
            'kind': InsurancePolicy.KIND_ASSET,
            'insurer': 'Nyala Insurance',
            'dbe_co_beneficiary': True,
            'starts_on': (now - timedelta(days=20)).date(),
            'expires_on': (now + timedelta(days=345)).date(),
            'note': 'Machinery all-risk; bank co-beneficiary.',
            'recorded_by': officer,
        },
    )
    RevaluationDiary.objects.get_or_create(
        loan_request=loan,
        due_on=date(now.year, 12, 15) if now.month < 12 else date(now.year + 1, 6, 15),
        defaults={'note': 'Annual machinery revaluation', 'recorded_by': officer},
    )


def _project_depth(loan, users, now):
    if loan is None:
        return
    from loans.models import (
        InsurancePolicy,
        LoanDisbursementTranche,
        LoanMonitoringVisit,
        LoanRequest,
        ProjectCashflowYear,
        ProjectSourceUseLine,
        ProjectTechnicalReview,
    )

    try:
        profile = loan.project_profile
    except Exception:
        return

    officer = loan.assigned_loan_officer or users.get('credit_lo')
    eng = users.get('eng1')
    fin = users.get('fin')
    amount = loan.amount_requested
    equity = (amount * Decimal('0.35')).quantize(Decimal('0.01'))

    if not profile.lines.exists():
        ProjectSourceUseLine.objects.create(
            profile=profile, side=ProjectSourceUseLine.SIDE_SOURCE,
            purpose=ProjectSourceUseLine.PURPOSE_PROMOTER, label='Promoter equity',
            amount=equity, sequence=1,
        )
        ProjectSourceUseLine.objects.create(
            profile=profile, side=ProjectSourceUseLine.SIDE_SOURCE,
            purpose=ProjectSourceUseLine.PURPOSE_DBE, label='DBE project loan',
            amount=amount, sequence=2,
        )
        ProjectSourceUseLine.objects.create(
            profile=profile, side=ProjectSourceUseLine.SIDE_USE,
            purpose=ProjectSourceUseLine.PURPOSE_CIVIL, label='Civil works',
            amount=(amount * Decimal('0.40')).quantize(Decimal('0.01')), sequence=1,
        )
        ProjectSourceUseLine.objects.create(
            profile=profile, side=ProjectSourceUseLine.SIDE_USE,
            purpose=ProjectSourceUseLine.PURPOSE_MACHINERY, label='Plant and mill',
            amount=(amount * Decimal('0.50')).quantize(Decimal('0.01')), sequence=2,
        )
        ProjectSourceUseLine.objects.create(
            profile=profile, side=ProjectSourceUseLine.SIDE_USE,
            purpose=ProjectSourceUseLine.PURPOSE_WC, label='Commissioning WC',
            amount=(amount * Decimal('0.10')).quantize(Decimal('0.01')), sequence=3,
        )

    if not profile.cashflows.exists():
        for year in range(1, 6):
            ProjectCashflowYear.objects.create(
                profile=profile,
                year_number=year,
                operating_cf=(Decimal('8000000') + amount * Decimal('0.04') * year).quantize(Decimal('0.01')),
                debt_service=(amount * Decimal('0.18')).quantize(Decimal('0.01')),
            )

    for desk, note in (
        (ProjectTechnicalReview.DESK_CIVIL, 'Foundations and mill building cleared.'),
        (ProjectTechnicalReview.DESK_MECH, 'Kiln and mill package accepted.'),
        (ProjectTechnicalReview.DESK_ELEC, '33kV incoming and MCC cleared.'),
    ):
        review, _ = ProjectTechnicalReview.objects.get_or_create(
            profile=profile, desk=desk,
        )
        review.status = ProjectTechnicalReview.STATUS_CLEARED
        review.note = note
        review.reviewed_at = now - timedelta(days=4)
        review.reviewed_by = eng
        review.save()

    t1, _ = LoanDisbursementTranche.objects.get_or_create(
        loan_request=loan, sequence=1,
        defaults={
            'amount': (amount * Decimal('0.40')).quantize(Decimal('0.01')),
            'note': 'Civil works draw',
            'status': LoanDisbursementTranche.STATUS_DISBURSED,
            'purpose_code': 'civil',
            'disbursed_at': now - timedelta(days=20),
            'disbursed_by': fin,
            'utilization_note': 'Foundation and mill hall 40% complete.',
            'utilization_recorded_at': now - timedelta(days=5),
        },
    )
    t2, _ = LoanDisbursementTranche.objects.get_or_create(
        loan_request=loan, sequence=2,
        defaults={
            'amount': (amount * Decimal('0.40')).quantize(Decimal('0.01')),
            'note': 'Machinery LC draw — pending implementation visit',
            'status': LoanDisbursementTranche.STATUS_PENDING,
            'purpose_code': 'machinery',
            'lc_status': 'opened',
        },
    )
    LoanRequest.objects.filter(pk=loan.pk).update(
        disbursement_status=LoanRequest.DISBURSE_PARTIAL,
        disbursed_at=now - timedelta(days=20),
        disbursed_by=fin,
        disbursement_notes='Civil tranche booked. Machinery draw awaits plant visit.',
        legal_cleared_at=now - timedelta(days=25),
        legal_cleared_by=users.get('legal'),
        legal_clearance_note='Land title and construction permit on file.',
    )

    if not loan.monitoring_visits.filter(visit_kind=LoanMonitoringVisit.KIND_IMPLEMENTATION).exists():
        LoanMonitoringVisit.objects.create(
            loan_request=loan,
            visited_at=(now - timedelta(days=5)).date(),
            notes='Civil works 42% complete. Ready to unlock machinery tranche after mill erection.',
            gps_lat=Decimal('13.50010000'),
            gps_lon=Decimal('39.47000000'),
            visit_kind=LoanMonitoringVisit.KIND_IMPLEMENTATION,
            percent_complete=Decimal('42.00'),
            purpose_code='civil',
            unlocks_next_tranche=True,
            unlocked_tranche=t2,
            recorded_by=officer,
        )

    InsurancePolicy.objects.get_or_create(
        loan_request=loan,
        policy_number='EIC-CEMENT-3010',
        defaults={
            'kind': InsurancePolicy.KIND_PROJECT,
            'insurer': 'Ethiopian Insurance Corporation',
            'dbe_co_beneficiary': True,
            'starts_on': (now - timedelta(days=40)).date(),
            'expires_on': (now + timedelta(days=325)).date(),
            'note': 'Contractors all-risk during construction.',
            'recorded_by': officer,
        },
    )


def _wholesale_util(loan, users):
    if loan is None:
        return
    from loans.models import PfiUtilizationReport

    try:
        profile = loan.pfi_profile
    except Exception:
        return
    PfiUtilizationReport.objects.get_or_create(
        profile=profile,
        as_of=date(timezone.now().year, 6, 30),
        defaults={
            'amount_onlent': Decimal('18500000'),
            'pfi_repaid_to_dbe': Decimal('2100000'),
            'sub_par30_pct': Decimal('5.40'),
            'sub_par90_pct': Decimal('3.10'),
            'women_onlent_pct': Decimal('32.00'),
            'youth_onlent_pct': Decimal('18.00'),
            'note': 'Mid-year sub-portfolio report — demo.',
            'recorded_by': users.get('credit_lo') or users.get('lo1'),
        },
    )


def _collections_rehab(loan, users, now):
    if loan is None:
        return
    from loans.models import (
        LoanCollectionAction,
        LoanDisbursementTranche,
        LoanRequest,
        RehabCase,
        RehabEvent,
    )

    officer = loan.assigned_loan_officer or users.get('lo3')
    fin = users.get('fin')
    legal = users.get('legal')
    LoanRequest.objects.filter(pk=loan.pk).update(
        legal_cleared_at=now - timedelta(days=80),
        legal_cleared_by=legal,
        legal_clearance_note='Cleared at booking. Now in recovery.',
        disbursement_status=LoanRequest.DISBURSE_DISBURSED,
        disbursed_at=now - timedelta(days=75),
        disbursed_by=fin,
        cbs_loan_account='CBS-DEMO-4018',
        cbs_booked_at=now - timedelta(days=75),
        cbs_booking_status=LoanRequest.CBS_BOOK_MOCK,
        watchlist=True,
        watchlist_reason='90+ days past due after equipment stall.',
        watchlist_at=now - timedelta(days=20),
        watchlist_by=officer,
        arrears_status=LoanRequest.ARREARS_NPL,
        workout_status=LoanRequest.WORKOUT_REQUESTED,
    )
    LoanDisbursementTranche.objects.get_or_create(
        loan_request=loan,
        sequence=1,
        defaults={
            'amount': loan.amount_requested,
            'note': 'Booked before arrears',
            'status': LoanDisbursementTranche.STATUS_DISBURSED,
            'disbursed_at': now - timedelta(days=75),
            'disbursed_by': fin,
        },
    )
    if not loan.collection_actions.exists():
        LoanCollectionAction.objects.create(
            loan_request=loan,
            kind=LoanCollectionAction.KIND_REMINDER,
            notes='SMS and call reminder after 15 DPD.',
            recorded_by=officer,
        )
        LoanCollectionAction.objects.create(
            loan_request=loan,
            kind=LoanCollectionAction.KIND_DEMAND,
            notes='Formal demand notice issued at 45 DPD.',
            recorded_by=officer,
        )
        LoanCollectionAction.objects.create(
            loan_request=loan,
            kind=LoanCollectionAction.KIND_VISIT,
            notes='Site visit: mill idle, operator seeking reschedule.',
            recorded_by=officer,
        )
    rehab, created = RehabCase.objects.get_or_create(
        loan_request=loan,
        defaults={
            'stage': RehabCase.STAGE_RESTRUCTURE,
            'note': 'Named rehabilitation before foreclosure.',
            'updated_by': officer,
        },
    )
    if created or not rehab.events.exists():
        RehabEvent.objects.create(
            case=rehab,
            from_stage=RehabCase.STAGE_WATCHLIST,
            to_stage=RehabCase.STAGE_RESTRUCTURE,
            note='Moved to restructure after demand notice.',
            recorded_by=officer,
        )


def _compliance_and_sanctions(by_cn, users, now):
    from loans.models import (
        ComplianceCase,
        ComplianceCaseEvent,
        SanctionsScreeningResult,
    )

    risk = users.get('risk')
    rediet = by_cn.get('1011')
    abebe = by_cn.get('1001')
    if rediet:
        case, made = ComplianceCase.objects.get_or_create(
            case_number='DEMO-PEP-0001',
            defaults={
                'case_type': ComplianceCase.TYPE_SANCTIONS,
                'status': ComplianceCase.STATUS_INVESTIGATING,
                'priority': ComplianceCase.PRIORITY_HIGH,
                'source': ComplianceCase.SOURCE_NAME_SCREEN,
                'summary': 'Possible PEP match on related-party name — sample investigation.',
                'loan_request': rediet,
                'assigned_to': risk,
                'blocks_origination': True,
                'blocks_disbursement': True,
                'opened_by': risk,
            },
        )
        if made:
            ComplianceCaseEvent.objects.create(
                case=case,
                event_type=ComplianceCaseEvent.TYPE_OPENED,
                notes='Opened from name-screen demo seed.',
                recorded_by=risk,
            )
            ComplianceCaseEvent.objects.create(
                case=case,
                event_type=ComplianceCaseEvent.TYPE_NOTE,
                notes='Awaiting enhanced due diligence pack from CRM.',
                recorded_by=risk,
            )
        SanctionsScreeningResult.objects.get_or_create(
            loan_request=rediet,
            hit=True,
            defaults={
                'score': 78,
                'match_types': ['pep'],
                'matches': [{'name': 'Rediet Alemu', 'list': 'demo-pep'}],
                'provider': 'mock',
                'subject': {'name': rediet.applicant_name},
                'compliance_case': case,
            },
        )
    if abebe:
        SanctionsScreeningResult.objects.get_or_create(
            loan_request=abebe,
            hit=False,
            defaults={
                'score': 4,
                'match_types': [],
                'matches': [],
                'provider': 'mock',
                'subject': {'name': abebe.applicant_name},
            },
        )
    genet = by_cn.get('1006')
    if genet:
        ComplianceCase.objects.get_or_create(
            case_number='DEMO-FRAUD-0002',
            defaults={
                'case_type': ComplianceCase.TYPE_FRAUD,
                'status': ComplianceCase.STATUS_FALSE_POSITIVE,
                'priority': ComplianceCase.PRIORITY_MEDIUM,
                'source': ComplianceCase.SOURCE_DOCUMENT,
                'summary': 'ID image quality alert — closed as false positive.',
                'loan_request': genet,
                'assigned_to': risk,
                'blocks_origination': False,
                'blocks_disbursement': False,
                'opened_by': risk,
                'closed_by': risk,
                'closed_at': now - timedelta(days=1),
                'resolution_note': 'Retake accepted. No fraud.',
            },
        )


def _collateral_photos(by_cn, users, now):
    from collateral.models import Building, BuildingImage, LandValuation, LandValuationImage
    from loans.management.commands.seed_sample_data import _demo_png

    officer = users.get('eng1') or users.get('lo1')
    png = _demo_png('field-visit')
    for cn in ('1004', '1009', '3010'):
        loan = by_cn.get(cn)
        if not loan:
            continue
        building = Building.objects.filter(loan_request=loan).first()
        if building and not BuildingImage.objects.filter(building=building).exists():
            img = BuildingImage(
                building=building,
                caption='Front elevation — field visit',
                photo_type=BuildingImage.PHOTO_FRONT,
                captured_at=now - timedelta(days=8),
                gps_lat=Decimal('13.49670000'),
                gps_lon=Decimal('39.47530000'),
                gps_accuracy_m=Decimal('6.50'),
                uploaded_by=officer,
            )
            img.image.save(f'{loan.loan_request_id}-front.png', ContentFile(png), save=True)
        land = LandValuation.objects.filter(loan_request=loan).first()
        if land and not LandValuationImage.objects.filter(land_valuation=land).exists():
            limg = LandValuationImage(
                land_valuation=land,
                caption='Plot overview',
                photo_type=LandValuationImage.PHOTO_PLOT,
                captured_at=now - timedelta(days=8),
                gps_lat=Decimal('13.50010000'),
                gps_lon=Decimal('39.47000000'),
                gps_accuracy_m=Decimal('8.00'),
                uploaded_by=officer,
            )
            limg.image.save(f'{loan.loan_request_id}-plot.png', ContentFile(png), save=True)


def _seqela_market(users, geo, now):
    from partners.market_bands import recompute_all_bands
    from partners.models import MarketActor, MarketObservation

    branch = geo['branches']['Mekelle Main Branch']
    city = geo['cities']['Mekelle']
    officer = users.get('eng1') or users.get('lo1')

    depot, _ = MarketActor.objects.get_or_create(
        branch=branch,
        name='Mekelle Cement Depot',
        defaults={
            'actor_kind': MarketActor.KIND_DEALER,
            'phone_number': '0912111901',
            'contact_person': 'Haftu Dealer',
            'address': 'Industrial park road, Mekelle',
            'product_focus': MarketActor.FOCUS_BUILDING,
            'product_lines': 'cement, HCB, steel',
            'trust_status': MarketActor.TRUST_TRUSTED,
            'is_active': True,
            'primary_city': city,
            'created_by': officer,
            'portal_enabled': True,
            'portal_username': '0912111901',
            'portal_password': make_password('Demo@12345'),
        },
    )
    if not depot.portal_enabled:
        depot.portal_enabled = True
        depot.portal_username = depot.portal_username or '0912111901'
        depot.portal_password = make_password('Demo@12345')
        depot.trust_status = MarketActor.TRUST_TRUSTED
        depot.save()

    steel, _ = MarketActor.objects.get_or_create(
        branch=geo['branches']['Adigrat Branch'],
        name='Adigrat Steel Yard',
        defaults={
            'actor_kind': MarketActor.KIND_SUPPLIER,
            'phone_number': '0912111902',
            'contact_person': 'Meron Supplier',
            'product_focus': MarketActor.FOCUS_BUILDING,
            'product_lines': 'rebar, mesh',
            'trust_status': MarketActor.TRUST_TRUSTED,
            'is_active': True,
            'primary_city': geo['cities']['Adigrat'],
            'created_by': officer,
        },
    )

    quotes = [
        (depot, city, 'Cement 50kg bag', 'bag', Decimal('1250'), Decimal('13.4967'), Decimal('39.4753')),
        (depot, city, 'Cement 50kg bag', 'bag', Decimal('1280'), Decimal('13.4968'), Decimal('39.4754')),
        (depot, city, 'Cement 50kg bag', 'bag', Decimal('1220'), Decimal('13.4966'), Decimal('39.4752')),
        (depot, city, 'HCB 20cm', 'piece', Decimal('28'), Decimal('13.4967'), Decimal('39.4753')),
        (depot, city, 'HCB 20cm', 'piece', Decimal('30'), Decimal('13.4967'), Decimal('39.4753')),
        (depot, city, 'HCB 20cm', 'piece', Decimal('29'), Decimal('13.4967'), Decimal('39.4753')),
        (steel, geo['cities']['Adigrat'], 'Rebar 12mm', 'ton', Decimal('92000'), None, None),
        (steel, geo['cities']['Adigrat'], 'Rebar 12mm', 'ton', Decimal('90500'), None, None),
        (steel, geo['cities']['Adigrat'], 'Rebar 12mm', 'ton', Decimal('94000'), None, None),
    ]
    if MarketObservation.objects.filter(market_actor=depot).count() < 3:
        for i, (actor, cty, label, unit, price, lat, lon) in enumerate(quotes):
            MarketObservation.objects.create(
                market_actor=actor,
                branch=actor.branch,
                city=cty,
                asset_class=MarketObservation.ASSET_BUILDING,
                item_label=label,
                unit=unit,
                unit_price_etb=price,
                quantity=Decimal('1'),
                condition=MarketObservation.CONDITION_NEW,
                observed_at=(now - timedelta(days=2 + i)).date(),
                channel=MarketObservation.CHANNEL_STAFF if i % 2 == 0 else MarketObservation.CHANNEL_PORTAL,
                status=MarketObservation.STATUS_ACTIVE,
                notes='Factory tour price feed',
                site_lat=lat,
                site_lon=lon,
                recorded_by=officer,
            )
    recompute_all_bands()


def _link_online_apply(loan):
    if loan is None:
        return
    from applicant_portal.models import OnlineApplication
    from loans.models import LoanRequest

    LoanRequest.objects.filter(pk=loan.pk).update(source_channel=LoanRequest.SOURCE_ONLINE)
    app = OnlineApplication.objects.filter(phone_number='0912111804').first()
    if app and app.loan_request_id != loan.pk:
        app.loan_request = loan
        app.queue_id = loan.loan_request_id
        app.status = OnlineApplication.STATUS_SUBMITTED
        app.payment_status = OnlineApplication.PAY_PAID
        if not app.submitted_at:
            app.submitted_at = timezone.now() - timedelta(days=1)
        app.save()
