"""Scan/Admin and parallel KYC inboxes."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from loans.kyc_desk import (
    QUEUE_CHOICES,
    KycClearBlocked,
    checklist_from_post,
    kyc_is_complete,
    kyc_queue_queryset,
    set_screening_status,
    user_can_access_kyc_desk,
    user_can_see_kyc_loan,
    user_can_work_desk,
    user_desk_for_kyc,
)
from loans.kyc_identity import delete_related_party, save_related_party
from loans.crm_cycle import (
    can_crm_comment,
    can_send_to_crm,
    crm_respond,
    send_pack_to_crm,
)
from loans.models import CreditDeskScreening, LoanRequest


@login_required
@user_passes_test(user_can_access_kyc_desk)
def kyc_desk(request):
    queue = (request.GET.get('queue') or 'mine').strip()
    if queue not in dict(QUEUE_CHOICES):
        queue = 'mine'
    qs, label = kyc_queue_queryset(request.user, queue)
    page_obj = Paginator(qs, 20).get_page(request.GET.get('page'))
    counts = {}
    for key, _ in QUEUE_CHOICES:
        counts[key] = kyc_queue_queryset(request.user, key)[0].count()
    return render(request, 'loans/kyc_desk.html', {
        'queue': queue,
        'queue_choices': QUEUE_CHOICES,
        'page_obj': page_obj,
        'scope_label': label,
        'counts': counts,
        'my_desk': user_desk_for_kyc(request.user),
    })


@login_required
@user_passes_test(user_can_access_kyc_desk)
@require_POST
def kyc_screening_action(request, loan_request_id):
    loan = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not user_can_see_kyc_loan(request.user, loan):
        messages.error(request, 'You do not have access to this KYC file.')
        return redirect('kyc_desk')
    desk = (request.POST.get('desk') or '').strip()
    action = (request.POST.get('action') or 'clear').strip()
    note = (request.POST.get('note') or '').strip()
    valid_desks = {c[0] for c in CreditDeskScreening.DESK_CHOICES}
    if desk not in valid_desks:
        messages.error(request, 'Unknown KYC desk.')
        return redirect('kyc_desk')
    if not user_can_work_desk(request.user, desk):
        messages.error(request, 'That pack belongs to another work unit.')
        return redirect('kyc_desk')
    status = CreditDeskScreening.STATUS_CLEARED
    if action == 'return':
        status = CreditDeskScreening.STATUS_RETURNED
        if len(note) < 8:
            messages.error(request, 'Explain the return (at least 8 characters).')
            return redirect('loan_request_detail', loan_request_id=loan.id)
    checklist = checklist_from_post(request.POST, desk, loan)
    try:
        set_screening_status(loan, desk, status, request.user, note, checklist=checklist)
    except KycClearBlocked as exc:
        messages.error(request, str(exc))
        nxt = request.POST.get('next') or request.GET.get('next')
        if nxt:
            return redirect(nxt)
        return redirect('loan_request_detail', loan_request_id=loan.id)
    if kyc_is_complete(loan):
        messages.success(request, 'KYC packs are complete — Appraisal can take the file.')
    else:
        messages.success(request, f'{desk.replace("_", " ").title()} pack updated.')
    nxt = request.POST.get('next') or request.GET.get('next')
    if nxt:
        return redirect(nxt)
    return redirect('loan_request_detail', loan_request_id=loan.id)


@login_required
@user_passes_test(user_can_access_kyc_desk)
@require_POST
def kyc_party_action(request, loan_request_id):
    loan = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not user_can_see_kyc_loan(request.user, loan):
        messages.error(request, 'You do not have access to this KYC file.')
        return redirect('kyc_desk')
    action = (request.POST.get('action') or 'add').strip()
    nxt = request.POST.get('next') or request.GET.get('next')
    if action == 'delete':
        try:
            pid = int(request.POST.get('party_id') or 0)
        except (TypeError, ValueError):
            pid = 0
        if delete_related_party(loan_request=loan, party_id=pid):
            messages.success(request, 'Related party removed from the identity case.')
        else:
            messages.error(request, 'Could not remove that party.')
    else:
        name = (request.POST.get('legal_name_en') or '').strip()
        if not name:
            messages.error(request, 'Enter the related party name.')
        else:
            save_related_party(
                loan_request=loan,
                role=request.POST.get('role') or '',
                legal_name_en=name,
                legal_name_am=request.POST.get('legal_name_am') or '',
                identity_kind=request.POST.get('identity_kind') or '',
                fan=request.POST.get('fan') or '',
                tin=request.POST.get('tin') or '',
                id_number=request.POST.get('id_number') or '',
                share_percent=request.POST.get('share_percent') or '',
                capacity=request.POST.get('capacity') or '',
                date_of_birth=request.POST.get('date_of_birth') or '',
                verify=True,
            )
            messages.success(request, 'Related party saved on the identity case.')
    if nxt:
        return redirect(nxt)
    return redirect('loan_request_detail', loan_request_id=loan.id)


@login_required
@require_POST
def crm_cycle_action(request, loan_request_id):
    loan = get_object_or_404(LoanRequest, pk=loan_request_id)
    if not user_can_see_kyc_loan(request.user, loan):
        messages.error(request, 'You do not have access to this KYC file.')
        return redirect('kyc_desk')
    action = (request.POST.get('action') or '').strip()
    note = (request.POST.get('note') or '').strip()
    nxt = request.POST.get('next') or request.GET.get('next')

    if action == 'send':
        if not can_send_to_crm(request.user, loan):
            messages.error(request, 'Finish KYC first, then send the pack from Appraisal.')
        elif len(note) < 8:
            messages.error(request, 'Summarise the pack for CRM (at least 8 characters).')
        else:
            send_pack_to_crm(loan, request.user, note)
            messages.success(request, 'Appraisal pack sent to CRM.')
    elif action in ('clear', 'return'):
        if not can_crm_comment(request.user, loan):
            messages.error(request, 'This pack is not waiting on your CRM desk.')
        elif action == 'return' and len(note) < 8:
            messages.error(request, 'Explain the return (at least 8 characters).')
        else:
            crm_respond(loan, request.user, action, note)
            if action == 'return':
                messages.warning(request, 'Pack returned to Appraisal.')
            else:
                messages.success(request, 'CRM cleared the pack — officer can submit to committee.')
    else:
        messages.error(request, 'Unknown CRM action.')
    if nxt:
        return redirect(nxt)
    return redirect('loan_request_detail', loan_request_id=loan.id)
