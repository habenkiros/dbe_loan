# loans/committee.py
"""Multi-level configurable approval committees (open-ended chain by sequence_order)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.db.models import Q
from django.utils import timezone


def get_appraisal_for_loan(loan_request):
    from loans.models import LoanAppraisal

    return LoanAppraisal.objects.filter(loan_request=loan_request).first()


def _loan_district_id(loan_request) -> Optional[int]:
    if loan_request.district_id:
        return loan_request.district_id
    if loan_request.branch_id:
        return loan_request.branch.district_id
    return None


def _loan_amount_for_routing(loan_request) -> Decimal:
    """Amount used for level routing: Sheet 6 recommended amount when set, else requested."""
    appraisal = get_appraisal_for_loan(loan_request)
    if appraisal and appraisal.amount_approved and appraisal.amount_approved > 0:
        return appraisal.amount_approved
    return loan_request.amount_requested or Decimal('0')


def _routing_amount_source(loan_request) -> str:
    appraisal = get_appraisal_for_loan(loan_request)
    if appraisal and appraisal.amount_approved and appraisal.amount_approved > 0:
        return 'recommended'
    return 'requested'


def get_levels_for_loan(loan_request) -> List:
    """Active levels that apply to this loan (amount thresholds + is_active)."""
    from loans.models import ApprovalCommitteeLevel

    amount = _loan_amount_for_routing(loan_request)
    levels = ApprovalCommitteeLevel.objects.filter(is_active=True).order_by('sequence_order', 'id')
    return [level for level in levels if level.applies_to_amount(amount)]


def get_approval_routing_summary(loan_request) -> Dict[str, Any]:
    """Levels that will run vs skipped, with amount-based reasons (for UI before/after submit)."""
    from loans.models import ApprovalCommitteeLevel

    amount = _loan_amount_for_routing(loan_request)
    all_levels = list(
        ApprovalCommitteeLevel.objects.filter(is_active=True).order_by('sequence_order', 'id')
    )
    applied = get_levels_for_loan(loan_request)
    applied_ids = {level.id for level in applied}
    skipped = []
    for level in all_levels:
        if level.id in applied_ids:
            continue
        skipped.append({
            'level': level,
            'reason': level.skip_reason_for_amount(amount),
        })
    branch_override = None
    if loan_request.branch_id:
        from loans.models import ApprovalCommitteeLevel as Level

        branch_level = next(
            (l for l in applied if l.voter_scope == Level.SCOPE_BRANCH),
            None,
        )
        if branch_level:
            branch_override = get_branch_override(loan_request, branch_level)
    return {
        'amount': amount,
        'amount_source': _routing_amount_source(loan_request),
        'applied_levels': applied,
        'skipped_levels': skipped,
        'branch_override': branch_override,
    }


def get_branch_override(loan_request, level):
    from loans.models import BranchCommitteeOverride, ApprovalCommitteeLevel

    if not loan_request.branch_id or level.voter_scope != ApprovalCommitteeLevel.SCOPE_BRANCH:
        return None
    return (
        BranchCommitteeOverride.objects.filter(
            branch_id=loan_request.branch_id,
            level=level,
            is_active=True,
        )
        .prefetch_related('member_rules')
        .first()
    )


def get_member_rules_for_level(loan_request, level):
    """Return (rules, branch_override or None). Branch rules replace global when configured."""
    from loans.models import ApprovalCommitteeMemberRule

    override = get_branch_override(loan_request, level)
    if override:
        branch_rules = list(override.member_rules.filter(is_active=True))
        if branch_rules:
            return branch_rules, override
    return list(level.member_rules.filter(is_active=True)), None


def get_level_vote_thresholds(loan_request, level):
    """(min_approvals, min_declines) for this loan at this level."""
    override = get_branch_override(loan_request, level)
    if override:
        min_app = (
            override.min_approvals_required
            if override.min_approvals_required is not None
            else level.min_approvals_required
        )
        min_dec = (
            override.min_declines_required
            if override.min_declines_required is not None
            else level.min_declines_required
        )
        return min_app, min_dec
    return level.min_approvals_required, level.min_declines_required


def _user_matches_rule(user, rule, loan_request, level) -> bool:
    from loans.models import ApprovalCommitteeMemberRule, ApprovalCommitteeLevel

    if not rule.is_active or not user.is_active:
        return False
    if rule.participant_type == ApprovalCommitteeMemberRule.PARTICIPANT_USER:
        return rule.user_id == user.id

    if user.role != rule.role:
        return False

    scope = level.voter_scope
    if scope == ApprovalCommitteeLevel.SCOPE_BRANCH:
        return bool(user.branch_id and loan_request.branch_id and user.branch_id == loan_request.branch_id)
    if scope == ApprovalCommitteeLevel.SCOPE_DISTRICT:
        district_id = _loan_district_id(loan_request)
        return bool(district_id and user.district_id == district_id)
    return True


def get_eligible_voters(loan_request, level) -> List:
    from loans.models import CustomUser, ApprovalCommitteeMemberRule, ApprovalCommitteeLevel

    rules, _ = get_member_rules_for_level(loan_request, level)
    users_by_id = {}
    for rule in rules:
        if rule.participant_type == ApprovalCommitteeMemberRule.PARTICIPANT_USER and rule.user_id:
            if _user_matches_rule(rule.user, rule, loan_request, level):
                users_by_id[rule.user_id] = rule.user
        else:
            qs = CustomUser.objects.filter(is_active=True, role=rule.role)
            if level.voter_scope == ApprovalCommitteeLevel.SCOPE_BRANCH:
                qs = qs.filter(branch_id=loan_request.branch_id)
            elif level.voter_scope == ApprovalCommitteeLevel.SCOPE_DISTRICT:
                district_id = _loan_district_id(loan_request)
                if district_id:
                    qs = qs.filter(district_id=district_id)
                else:
                    qs = qs.none()
            for u in qs:
                if _user_matches_rule(u, rule, loan_request, level):
                    users_by_id[u.id] = u
    return list(users_by_id.values())


def user_can_vote_at_level(user, loan_request, level) -> bool:
    if loan_request.committee_status != loan_request.COMMITTEE_PENDING:
        return False
    if loan_request.current_approval_level_id != level.id:
        return False
    from loans.models import LoanCommitteeVote

    if LoanCommitteeVote.objects.filter(
        loan_request=loan_request, member=user, approval_level=level,
    ).exists():
        return False
    return any(u.id == user.id for u in get_eligible_voters(loan_request, level))


def user_is_approval_participant(user) -> bool:
    """True if user appears in any active member rule (global or branch override)."""
    from loans.models import ApprovalCommitteeMemberRule, BranchCommitteeMemberRule

    if not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False) or user.role in ('superadmin', 'admin'):
        return True
    if ApprovalCommitteeMemberRule.objects.filter(
        is_active=True, participant_type=ApprovalCommitteeMemberRule.PARTICIPANT_USER, user=user,
    ).exists():
        return True
    if BranchCommitteeMemberRule.objects.filter(
        is_active=True,
        participant_type=BranchCommitteeMemberRule.PARTICIPANT_USER,
        user=user,
        override__is_active=True,
    ).exists():
        return True
    if ApprovalCommitteeMemberRule.objects.filter(
        is_active=True,
        participant_type=ApprovalCommitteeMemberRule.PARTICIPANT_ROLE,
        role=user.role,
    ).exists():
        return True
    return BranchCommitteeMemberRule.objects.filter(
        is_active=True,
        participant_type=BranchCommitteeMemberRule.PARTICIPANT_ROLE,
        role=user.role,
        override__is_active=True,
    ).exists()


def _user_participates_in_branch_rules(user) -> bool:
    from loans.models import BranchCommitteeMemberRule

    return BranchCommitteeMemberRule.objects.filter(
        is_active=True,
        override__is_active=True,
        override__level__is_active=True,
    ).filter(
        Q(participant_type=BranchCommitteeMemberRule.PARTICIPANT_USER, user=user)
        | Q(participant_type=BranchCommitteeMemberRule.PARTICIPANT_ROLE, role=user.role)
    ).exists()


def _user_active_committee_rules(user):
    from loans.models import ApprovalCommitteeMemberRule

    if not user.is_authenticated:
        return ApprovalCommitteeMemberRule.objects.none()
    if getattr(user, 'is_superuser', False) or user.role in ('superadmin', 'admin'):
        return ApprovalCommitteeMemberRule.objects.filter(is_active=True, level__is_active=True)
    return ApprovalCommitteeMemberRule.objects.filter(
        is_active=True,
        level__is_active=True,
    ).filter(
        Q(participant_type=ApprovalCommitteeMemberRule.PARTICIPANT_USER, user=user)
        | Q(participant_type=ApprovalCommitteeMemberRule.PARTICIPANT_ROLE, role=user.role)
    ).select_related('level')


def _committee_engaged_q():
    from loans.models import LoanRequest

    return ~Q(committee_status=LoanRequest.COMMITTEE_NOT_SUBMITTED) & ~Q(committee_status__isnull=True)


def committee_loan_visibility_q(user) -> Q:
    """
    Loans this user may see in committee lists/detail
    (by branch, district, or current org-scoped level).
    """
    from loans.models import ApprovalCommitteeLevel

    if getattr(user, 'is_superuser', False) or user.role in ('superadmin', 'admin'):
        return _committee_engaged_q()

    rules = _user_active_committee_rules(user)
    if not rules.exists():
        return Q(pk__in=[])

    scopes = set(rules.values_list('level__voter_scope', flat=True))
    org_level_ids = set(
        rules.filter(level__voter_scope=ApprovalCommitteeLevel.SCOPE_ORGANIZATION)
        .values_list('level_id', flat=True)
    )
    visibility = Q()
    has_scope = False
    engaged = _committee_engaged_q()

    if (
        ApprovalCommitteeLevel.SCOPE_BRANCH in scopes or _user_participates_in_branch_rules(user)
    ) and user.branch_id:
        visibility |= Q(branch_id=user.branch_id)
        has_scope = True
    if ApprovalCommitteeLevel.SCOPE_DISTRICT in scopes:
        district_id = user.district_id
        if not district_id and user.branch_id:
            district_id = getattr(user.branch, 'district_id', None)
        if district_id:
            visibility |= Q(district_id=district_id) | Q(branch__district_id=district_id)
            has_scope = True
    if org_level_ids:
        visibility |= Q(current_approval_level_id__in=org_level_ids)
        has_scope = True

    if not has_scope:
        return Q(pk__in=[])
    return engaged & visibility


def committee_loan_requests_queryset(user):
    """All committee loans visible to user in their branch/district/org scope."""
    from loans.models import LoanRequest

    return (
        LoanRequest.objects.filter(committee_loan_visibility_q(user))
        .select_related('branch', 'district', 'current_approval_level', 'category')
        .distinct()
    )


def user_can_view_committee_loan(user, loan_request) -> bool:
    if getattr(user, 'is_superuser', False) or user.role in ('superadmin', 'admin'):
        return True
    if loan_request.committee_status in ('', None):
        return False
    return committee_loan_requests_queryset(user).filter(pk=loan_request.pk).exists()


def committee_filter_districts(user):
    """Districts the user may filter in the committee loan list."""
    from loans.models import District

    if getattr(user, 'is_superuser', False) or user.role in ('superadmin', 'admin'):
        return District.objects.all().order_by('name')
    visible = committee_loan_requests_queryset(user)
    ids = set(visible.exclude(district_id__isnull=True).values_list('district_id', flat=True))
    ids |= set(
        visible.filter(district_id__isnull=True)
        .exclude(branch__district_id__isnull=True)
        .values_list('branch__district_id', flat=True)
    )
    if user.district_id:
        ids.add(user.district_id)
    elif user.branch_id and getattr(user.branch, 'district_id', None):
        ids.add(user.branch.district_id)
    return District.objects.filter(id__in=ids).order_by('name')


def committee_filter_branches(user, district_id=None):
    """Branches the user may filter (optionally within one district)."""
    from loans.models import Branch

    if getattr(user, 'is_superuser', False) or user.role in ('superadmin', 'admin'):
        qs = Branch.objects.all()
        if district_id:
            qs = qs.filter(district_id=district_id)
        return qs.order_by('name')
    if user.branch_id and not district_id:
        return Branch.objects.filter(pk=user.branch_id).order_by('name')
    visible = committee_loan_requests_queryset(user)
    branch_ids = set(visible.exclude(branch_id__isnull=True).values_list('branch_id', flat=True))
    if user.branch_id:
        branch_ids.add(user.branch_id)
    qs = Branch.objects.filter(id__in=branch_ids)
    if district_id:
        qs = qs.filter(district_id=district_id)
    return qs.order_by('name')


def committee_queue_queryset(user):
    """Loans pending committee where user may vote at current level."""
    from loans.models import LoanRequest

    if getattr(user, 'is_superuser', False) or user.role in ('superadmin', 'admin'):
        return LoanRequest.objects.filter(committee_status=LoanRequest.COMMITTEE_PENDING)

    pending = LoanRequest.objects.filter(
        committee_status=LoanRequest.COMMITTEE_PENDING,
        current_approval_level__isnull=False,
    ).select_related('branch', 'current_approval_level', 'category')

    ids = []
    for lr in pending:
        if lr.current_approval_level and user_can_vote_at_level(user, lr, lr.current_approval_level):
            ids.append(lr.pk)
    return LoanRequest.objects.filter(pk__in=ids)


def get_level_tally(loan_request, level, current_user=None) -> Dict[str, Any]:
    from loans.models import LoanCommitteeVote

    votes = list(
        loan_request.committee_votes.filter(approval_level=level).select_related('member')
    )
    approve_count = sum(1 for v in votes if v.vote == LoanCommitteeVote.VOTE_APPROVE)
    decline_count = sum(1 for v in votes if v.vote == LoanCommitteeVote.VOTE_DECLINE)
    eligible = get_eligible_voters(loan_request, level)
    _, branch_override = get_member_rules_for_level(loan_request, level)
    min_approvals, min_declines = get_level_vote_thresholds(loan_request, level)

    user_vote = None
    can_vote = False
    if current_user:
        user_vote = next((v for v in votes if v.member_id == current_user.id), None)
        can_vote = user_can_vote_at_level(current_user, loan_request, level)

    return {
        'level': level,
        'votes': votes,
        'eligible_voters': eligible,
        'eligible_count': len(eligible),
        'approve_count': approve_count,
        'decline_count': decline_count,
        'min_approvals': min_approvals,
        'min_declines': min_declines,
        'approvals_needed': max(0, min_approvals - approve_count),
        'declines_needed': max(0, min_declines - decline_count),
        'uses_branch_override': branch_override is not None,
        'user_vote': user_vote,
        'can_vote': can_vote,
    }


def get_approval_pipeline(loan_request, current_user=None) -> List[Dict[str, Any]]:
    """All levels for loan with progress + tally."""
    from loans.models import LoanApprovalLevelProgress

    progress_map = {
        p.level_id: p
        for p in loan_request.approval_level_progress.select_related('level')
    }
    pipeline = []
    routing = get_approval_routing_summary(loan_request)
    for level in routing['applied_levels']:
        prog = progress_map.get(level.id)
        pipeline.append({
            'level': level,
            'progress': prog,
            'status': prog.status if prog else 'not_started',
            'is_current': loan_request.current_approval_level_id == level.id,
            'tally': get_level_tally(loan_request, level, current_user) if prog else None,
        })
    return pipeline


def get_committee_tally(loan_request, current_user=None) -> Dict[str, Any]:
    """Summary for templates: current level + full pipeline."""
    level = loan_request.current_approval_level
    current_tally = get_level_tally(loan_request, level, current_user) if level else None
    return {
        'current_level': level,
        'current_tally': current_tally,
        'pipeline': get_approval_pipeline(loan_request, current_user),
        'routing': get_approval_routing_summary(loan_request),
        'can_vote': bool(current_tally and current_tally.get('can_vote')),
        'user_vote': current_tally.get('user_vote') if current_tally else None,
    }


def officer_can_submit_to_committee(loan_request) -> Dict[str, Any]:
    errors = []
    if not loan_request.appraisal_completed_at:
        errors.append('Finish the appraisal on Sheet 6 (Summary & decision) before submitting to committee.')
    appraisal = get_appraisal_for_loan(loan_request)
    if not appraisal:
        errors.append('No appraisal record found — complete Sheets 1–6 first.')
    else:
        if not appraisal.amount_approved or appraisal.amount_approved <= 0:
            errors.append('Enter the recommended amount on Sheet 6 (Summary & decision).')
        if appraisal.recommendation not in ('approve', 'escalate'):
            errors.append('Sheet 6 recommendation must be Approve or Escalate to send to committee.')
    if not get_levels_for_loan(loan_request):
        errors.append('No approval committee levels are configured (Settings → Approval committees).')
    if loan_request.committee_status == loan_request.COMMITTEE_PENDING:
        errors.append('This loan is already in the approval committee workflow.')
    if loan_request.committee_status == loan_request.COMMITTEE_APPROVED:
        errors.append('Committee has already approved this loan.')
    if loan_request.committee_status == loan_request.COMMITTEE_DECLINED:
        errors.append('Committee declined this loan — contact an administrator to reopen.')
    routing = get_approval_routing_summary(loan_request)
    return {
        'ok': not errors,
        'errors': errors,
        'appraisal': appraisal,
        'routing': routing,
    }


def user_can_return_to_officer(user, loan_request) -> bool:
    """Eligible voter at current level, or admin, may return loan for corrections."""
    if getattr(user, 'is_superuser', False) or user.role in ('superadmin', 'admin'):
        return loan_request.committee_status == loan_request.COMMITTEE_PENDING
    level = loan_request.current_approval_level
    if not level or loan_request.committee_status != loan_request.COMMITTEE_PENDING:
        return False
    return user_can_vote_at_level(user, loan_request, level)


def return_loan_to_officer(loan_request, returned_by, notes: str) -> None:
    """Send loan back to loan officer; clears active committee state for rework."""
    from loans.models import LoanApprovalLevelProgress, LoanRequest

    loan_request.committee_status = LoanRequest.COMMITTEE_RETURNED
    loan_request.current_approval_level = None
    loan_request.committee_return_notes = notes.strip()
    loan_request.committee_returned_at = timezone.now()
    loan_request.committee_returned_by = returned_by
    # Unlock Sheets 1–7 / scorecard — officer must re-finish before resubmit.
    loan_request.appraisal_completed_at = None
    loan_request.submitted_to_committee_at = None
    loan_request.submitted_to_committee_by = None
    loan_request.save(
        update_fields=[
            'committee_status',
            'current_approval_level',
            'committee_return_notes',
            'committee_returned_at',
            'committee_returned_by',
            'appraisal_completed_at',
            'submitted_to_committee_at',
            'submitted_to_committee_by',
        ]
    )
    loan_request.approval_level_progress.filter(
        status=LoanApprovalLevelProgress.STATUS_PENDING,
    ).update(
        status=LoanApprovalLevelProgress.STATUS_SKIPPED,
        completed_at=timezone.now(),
    )

    from loans.services.notifications import (
        notify_assigned_officer,
        notify_users,
    )

    lr_id = loan_request.loan_request_id
    notify_assigned_officer(
        loan_request,
        kind='returned_to_officer',
        title=f'Loan {lr_id} returned for corrections',
        message=(
            f'The approval committee returned this loan to you for corrections.\n\n'
            f'Feedback: {notes.strip()}'
        ),
    )
    if returned_by != loan_request.assigned_loan_officer:
        notify_users(
            [returned_by],
            loan_request=loan_request,
            kind='returned_to_officer',
            title=f'You returned loan {lr_id} to the officer',
            message=notes.strip(),
        )


def _notify_committee_workflow(loan_request, *, event: str, level=None, next_level=None) -> None:
    from loans.services.notifications import (
        notify_assigned_officer,
        notify_eligible_voters,
        notify_users,
    )
    from loans.models import LoanNotification, LoanRequest

    lr_id = loan_request.loan_request_id

    if event == 'submitted':
        first = loan_request.current_approval_level
        if first:
            notify_eligible_voters(
                loan_request,
                first,
                kind=LoanNotification.KIND_VOTE_NEEDED,
                title=f'Vote needed: {lr_id} — {first.name}',
                message=f'Loan {lr_id} was submitted to the committee. Your vote is needed at {first.name}.',
            )
        notify_assigned_officer(
            loan_request,
            kind=LoanNotification.KIND_LEVEL_ADVANCED,
            title=f'Loan {lr_id} submitted to committee',
            message='Your appraisal package is now in the approval committee workflow.',
        )
        return

    if event == 'advanced' and next_level:
        notify_eligible_voters(
            loan_request,
            next_level,
            kind=LoanNotification.KIND_VOTE_NEEDED,
            title=f'Vote needed: {lr_id} — {next_level.name}',
            message=(
                f'Loan {lr_id} advanced to {next_level.name}. '
                f'Please review and cast your vote.'
            ),
        )
        if level:
            notify_assigned_officer(
                loan_request,
                kind=LoanNotification.KIND_LEVEL_ADVANCED,
                title=f'Loan {lr_id} passed {level.name}',
                message=f'The loan advanced to {next_level.name} in the committee workflow.',
            )
        return

    if event == 'approved':
        from django.urls import reverse

        notify_assigned_officer(
            loan_request,
            kind=LoanNotification.KIND_COMMITTEE_APPROVED,
            title=f'Committee approved loan {lr_id}',
            message=(
                f'All committee levels approved this loan.'
                f'{" Final amount: " + str(loan_request.committee_final_amount) if loan_request.committee_final_amount else ""}'
                ' Complete conditions precedent and confirm the repayment schedule before disbursement.'
            ),
            url=reverse('post_approval_detail', args=[loan_request.pk]),
        )
        return

    if event == 'declined' and level:
        notify_assigned_officer(
            loan_request,
            kind=LoanNotification.KIND_COMMITTEE_DECLINED,
            title=f'Committee declined loan {lr_id}',
            message=f'The loan was declined at {level.name}.',
        )


def start_approval_workflow(loan_request) -> None:
    from loans.models import LoanApprovalLevelProgress, LoanRequest

    if loan_request.committee_status in (
        LoanRequest.COMMITTEE_RETURNED,
        LoanRequest.COMMITTEE_DECLINED,
    ):
        loan_request.committee_votes.all().delete()
        loan_request.approval_level_progress.all().delete()
        loan_request.committee_return_notes = ''
        loan_request.committee_returned_at = None
        loan_request.committee_returned_by = None

    levels = get_levels_for_loan(loan_request)
    now = timezone.now()
    for i, level in enumerate(levels):
        LoanApprovalLevelProgress.objects.update_or_create(
            loan_request=loan_request,
            level=level,
            defaults={
                'status': LoanApprovalLevelProgress.STATUS_PENDING,
                'started_at': now if i == 0 else None,
                'completed_at': None,
            },
        )
    loan_request.committee_status = LoanRequest.COMMITTEE_PENDING
    loan_request.current_approval_level = levels[0] if levels else None
    loan_request.save(
        update_fields=[
            'committee_status',
            'current_approval_level',
            'committee_return_notes',
            'committee_returned_at',
            'committee_returned_by',
        ]
    )
    _notify_committee_workflow(loan_request, event='submitted')


def _resolve_final_amount(loan_request, appraisal, level) -> Optional[Decimal]:
    from loans.models import LoanCommitteeVote

    amounts = [
        v.amount_supported
        for v in loan_request.committee_votes.filter(
            approval_level=level, vote=LoanCommitteeVote.VOTE_APPROVE,
        )
        if v.amount_supported is not None and v.amount_supported > 0
    ]
    if amounts:
        return min(amounts)
    if appraisal and appraisal.amount_approved:
        return appraisal.amount_approved
    return None


def _advance_after_level_decision(loan_request, level, decision: str) -> bool:
    """
    Mark level progress complete; advance to next level or finalize loan.
    Returns True if entire workflow finished.
    """
    from loans.models import LoanApprovalLevelProgress, LoanRequest

    prog = loan_request.approval_level_progress.filter(level=level).first()
    if prog:
        prog.status = (
            LoanApprovalLevelProgress.STATUS_APPROVED
            if decision == 'approve'
            else LoanApprovalLevelProgress.STATUS_DECLINED
        )
        prog.completed_at = timezone.now()
        prog.save(update_fields=['status', 'completed_at'])

    if decision == 'decline':
        loan_request.committee_status = LoanRequest.COMMITTEE_DECLINED
        loan_request.committee_final_decision = 'decline'
        loan_request.committee_decided_at = timezone.now()
        loan_request.date_reviewed = timezone.now()
        loan_request.current_approval_level = None
        loan_request.save(
            update_fields=[
                'committee_status', 'committee_final_decision',
                'committee_decided_at', 'date_reviewed', 'current_approval_level',
            ]
        )
        _notify_committee_workflow(loan_request, event='declined', level=level)
        return True

    levels = get_levels_for_loan(loan_request)
    try:
        idx = next(i for i, l in enumerate(levels) if l.id == level.id)
    except StopIteration:
        idx = -1

    next_level = levels[idx + 1] if idx + 1 < len(levels) else None
    if next_level:
        nprog = loan_request.approval_level_progress.filter(level=next_level).first()
        if nprog:
            nprog.status = LoanApprovalLevelProgress.STATUS_PENDING
            nprog.started_at = timezone.now()
            nprog.save(update_fields=['status', 'started_at'])
        loan_request.current_approval_level = next_level
        loan_request.save(update_fields=['current_approval_level'])
        _notify_committee_workflow(loan_request, event='advanced', level=level, next_level=next_level)
        return False

    appraisal = get_appraisal_for_loan(loan_request)
    loan_request.committee_status = LoanRequest.COMMITTEE_APPROVED
    loan_request.committee_final_decision = 'approve'
    loan_request.committee_final_amount = _resolve_final_amount(loan_request, appraisal, level)
    loan_request.committee_decided_at = timezone.now()
    loan_request.date_reviewed = timezone.now()
    loan_request.current_approval_level = None
    loan_request.save(
        update_fields=[
            'committee_status', 'committee_final_decision', 'committee_final_amount',
            'committee_decided_at', 'date_reviewed', 'current_approval_level',
        ]
    )
    if appraisal and loan_request.committee_final_amount is not None:
        appraisal.amount_approved = loan_request.committee_final_amount
        appraisal.save(update_fields=['amount_approved'])
    from loans.disbursement import start_disbursement_track
    start_disbursement_track(loan_request)
    _notify_committee_workflow(loan_request, event='approved', level=level)
    return True


def try_finalize_level_decision(loan_request, level) -> bool:
    """Check votes at current level; advance or finalize if thresholds met."""
    if loan_request.committee_status != loan_request.COMMITTEE_PENDING:
        return False
    if loan_request.current_approval_level_id != level.id:
        return False

    tally = get_level_tally(loan_request, level)
    if tally['approve_count'] >= tally['min_approvals']:
        return _advance_after_level_decision(loan_request, level, 'approve')
    if tally['decline_count'] >= tally['min_declines']:
        return _advance_after_level_decision(loan_request, level, 'decline')
    return False


def try_finalize_committee_decision(loan_request) -> bool:
    """Backward-compatible wrapper: finalize at current level only."""
    if loan_request.current_approval_level:
        return try_finalize_level_decision(loan_request, loan_request.current_approval_level)
    return False
