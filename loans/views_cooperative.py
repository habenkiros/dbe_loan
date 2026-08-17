"""Branch Cooperative performance dashboard."""

from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render

from loans.cooperative_performance import (
    cooperative_performance_stats,
    user_can_access_cooperative_performance,
)
from loans.reporting import filter_choices_for_user, filtered_reporting_queryset


@login_required
@user_passes_test(user_can_access_cooperative_performance)
def cooperative_performance(request):
    params = request.GET
    qs = filtered_reporting_queryset(request.user, params)
    stats = cooperative_performance_stats(qs)
    choices = filter_choices_for_user(request.user, district_id=params.get('district_id') or None)
    return render(request, 'loans/cooperative_performance.html', {
        'stats': stats,
        'filters': {
            'status': params.get('status', ''),
            'branch_id': params.get('branch_id', ''),
            'district_id': params.get('district_id', ''),
            'date_from': params.get('date_from', ''),
            'date_to': params.get('date_to', ''),
        },
        'querystring': request.GET.urlencode(),
        **choices,
    })
