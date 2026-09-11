"""Appraisal, ITS, and PM & MIS directorate inboxes."""

from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.shortcuts import render

from loans.dbe_desks import DESK_APPRAISAL, DESK_ITS, DESK_MIS
from loans.directorate import (
    DESK_TITLES,
    counts_for,
    default_queue,
    directorate_queue,
    user_can_access_directorate,
)


def _can_appraisal(user):
    return user_can_access_directorate(user, DESK_APPRAISAL)


def _can_its(user):
    return user_can_access_directorate(user, DESK_ITS)


def _can_mis(user):
    return user_can_access_directorate(user, DESK_MIS)


def _desk(request, desk: str):
    queue = (request.GET.get('queue') or default_queue(desk)).strip()
    rows, label, row_kind, choices = directorate_queue(desk, queue, request.user)
    counts = counts_for(desk, request.user)
    tabs = [(key, qlabel, counts.get(key, 0)) for key, qlabel in choices]
    page_obj = Paginator(rows, 20).get_page(request.GET.get('page'))
    return render(request, 'loans/directorate_desk.html', {
        'desk': desk,
        'desk_title': DESK_TITLES.get(desk, desk),
        'queue': queue,
        'queue_tabs': tabs,
        'page_obj': page_obj,
        'scope_label': label,
        'row_kind': row_kind,
    })


@login_required
@user_passes_test(_can_appraisal)
def appraisal_desk(request):
    return _desk(request, DESK_APPRAISAL)


@login_required
@user_passes_test(_can_its)
def its_desk(request):
    return _desk(request, DESK_ITS)


@login_required
@user_passes_test(_can_mis)
def mis_desk(request):
    return _desk(request, DESK_MIS)
