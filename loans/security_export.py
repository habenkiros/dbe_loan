"""Security audit filtering + CSV/Excel export helpers."""
from __future__ import annotations

import csv
import json
from datetime import datetime, time
from io import BytesIO, StringIO
from typing import Optional

from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from openpyxl import Workbook
from openpyxl.styles import Font

from .models import SecurityAuditLog


def parse_audit_filters(params):
    """Return (queryset, filter_meta) from request.GET-like mapping."""
    qs = SecurityAuditLog.objects.all()
    meta = {
        'event_type': (params.get('event_type') or '').strip(),
        'username': (params.get('username') or '').strip(),
        'date_from': (params.get('date_from') or '').strip(),
        'date_to': (params.get('date_to') or '').strip(),
        'ip_address': (params.get('ip_address') or '').strip(),
    }
    if meta['event_type']:
        qs = qs.filter(event_type=meta['event_type'])
    if meta['username']:
        qs = qs.filter(username__icontains=meta['username'])
    if meta['ip_address']:
        qs = qs.filter(ip_address=meta['ip_address'])
    if meta['date_from']:
        d = parse_date(meta['date_from'])
        if d:
            start = timezone.make_aware(datetime.combine(d, time.min))
            qs = qs.filter(created_at__gte=start)
    if meta['date_to']:
        d = parse_date(meta['date_to'])
        if d:
            end = timezone.make_aware(datetime.combine(d, time.max))
            qs = qs.filter(created_at__lte=end)
    return qs, meta


def audit_csv_response(queryset, filename: Optional[str] = None) -> HttpResponse:
    filename = filename or f"security_audit_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['created_at', 'event_type', 'username', 'ip_address', 'user_agent', 'detail_json'])
    for row in queryset:
        writer.writerow([
            row.created_at.isoformat() if row.created_at else '',
            row.event_type,
            row.username,
            row.ip_address or '',
            row.user_agent,
            json.dumps(row.detail or {}, ensure_ascii=False),
        ])
    response = HttpResponse(buffer.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def audit_xlsx_response(queryset, filename: Optional[str] = None) -> HttpResponse:
    filename = filename or f"security_audit_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = 'Security audit'
    headers = ['When', 'Event', 'Username', 'IP', 'User-Agent', 'Detail JSON']
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in queryset:
        ws.append([
            row.created_at.isoformat() if row.created_at else '',
            row.get_event_type_display(),
            row.username,
            row.ip_address or '',
            row.user_agent,
            json.dumps(row.detail or {}, ensure_ascii=False),
        ])
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    response = HttpResponse(
        bio.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
