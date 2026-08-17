"""Risk & Compliance desk views."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from loans.ci_workspaces import build_risk_alerts
from loans.models import LoanRequest
from loans.risk_desk import (
    QUEUE_CHOICES,
    risk_desk_counts,
    risk_queue_queryset,
    user_can_access_risk_desk,
)


@login_required
@user_passes_test(user_can_access_risk_desk)
def risk_desk(request):
    queue = (request.GET.get('queue') or 'alerts').strip()
    if queue not in dict(QUEUE_CHOICES):
        queue = 'alerts'

    alerts = build_risk_alerts(request.user, limit=20)
    counts = risk_desk_counts(request.user)
    page_obj = None
    scope_label = ''
    if queue != 'alerts':
        qs, scope_label = risk_queue_queryset(request.user, queue)
        paginator = Paginator(qs, 10)
        page_obj = paginator.get_page(request.GET.get('page'))
    else:
        _, scope_label = risk_queue_queryset(request.user, 'unreviewed')

    return render(request, 'loans/risk_desk.html', {
        'queue': queue,
        'queue_choices': QUEUE_CHOICES,
        'counts': counts,
        'alerts': alerts,
        'page_obj': page_obj,
        'scope_label': scope_label,
    })


@login_required
@user_passes_test(lambda u: getattr(u, 'role', None) == 'risk_compliance' or getattr(u, 'is_superuser', False))
@require_POST
def save_risk_review(request, loan_request_id):
    loan = get_object_or_404(LoanRequest, pk=loan_request_id)
    note = (request.POST.get('risk_review_note') or '').strip()
    loan.risk_review_note = note
    loan.risk_reviewed_at = timezone.now()
    loan.risk_reviewed_by = request.user
    loan.save(update_fields=['risk_review_note', 'risk_reviewed_at', 'risk_reviewed_by'])
    messages.success(request, 'Risk review saved.')
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('loan_request_detail', loan_request_id=loan.id)
