"""Loan-level compliance audit export pack (ZIP).

Assembles documents, appraisal PDF, committee votes, closing legal scans,
signed agreement evidence, and CBS booking attempts into one reconstructable archive.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from django.utils import timezone


SCHEMA_VERSION = '1.0'


def _json_default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, 'pk'):
        return str(obj)
    raise TypeError(f'Object of type {type(obj).__name__} is not JSON serializable')


def _dumps(data: Any) -> bytes:
    return json.dumps(data, default=_json_default, indent=2, ensure_ascii=False).encode('utf-8')


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _safe_slug(text: str, fallback: str = 'item') -> str:
    raw = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in (text or '').strip())[:60]
    return raw.strip('_') or fallback


def _user_ref(user) -> Optional[Dict[str, Any]]:
    if not user:
        return None
    return {
        'id': user.pk,
        'username': user.username,
        'full_name': user.get_full_name() or user.username,
        'role': getattr(user, 'role', ''),
    }


def _add_bytes(zf: zipfile.ZipFile, path: str, blob: bytes, file_hashes: Dict[str, str]) -> None:
    zf.writestr(path, blob)
    file_hashes[path] = _sha256_bytes(blob)


def build_loan_summary(loan_request) -> Dict[str, Any]:
    appraisal = getattr(loan_request, 'appraisal', None)
    if appraisal is None:
        from loans.models import LoanAppraisal
        appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    return {
        'loan_request_id': loan_request.loan_request_id,
        'applicant_name': loan_request.applicant_name,
        'phone_number': loan_request.phone_number,
        'customer_number': loan_request.customer_number or '',
        'branch': loan_request.branch.name if loan_request.branch_id else '',
        'amount_requested': loan_request.amount_requested,
        'status': loan_request.status,
        'committee_status': loan_request.committee_status,
        'committee_final_amount': getattr(loan_request, 'committee_final_amount', None),
        'submitted_to_committee_at': loan_request.submitted_to_committee_at,
        'committee_decided_at': getattr(loan_request, 'committee_decided_at', None),
        'disbursement_status': loan_request.disbursement_status,
        'disbursed_at': loan_request.disbursed_at,
        'cbs': {
            'booking_status': loan_request.cbs_booking_status or '',
            'booking_ref': loan_request.cbs_booking_ref or '',
            'loan_account': loan_request.cbs_loan_account or '',
            'booked_at': loan_request.cbs_booked_at,
            'outstanding_at_booking': loan_request.cbs_outstanding_at_booking,
        },
        'appraisal': {
            'recommendation': getattr(appraisal, 'recommendation', None),
            'amount_approved': getattr(appraisal, 'amount_approved', None),
            'credit_score_total': getattr(appraisal, 'credit_score_total', None),
            'credit_score_band': getattr(appraisal, 'credit_score_band', None),
            'collateral_coverage_ratio': getattr(appraisal, 'collateral_coverage_ratio', None),
        } if appraisal else None,
    }


def build_votes_payload(loan_request) -> Dict[str, Any]:
    from loans.models import LoanApprovalLevelProgress, LoanCommitteeVote

    votes = []
    for v in LoanCommitteeVote.objects.filter(loan_request=loan_request).select_related(
        'approval_level', 'member', 'cast_by',
    ).order_by('voted_at', 'id'):
        votes.append({
            'id': v.pk,
            'level': v.approval_level.name if v.approval_level_id else '',
            'level_key': getattr(v.approval_level, 'key', '') if v.approval_level_id else '',
            'member': _user_ref(v.member),
            'cast_by': _user_ref(v.cast_by),
            'vote': v.vote,
            'vote_display': v.get_vote_display(),
            'amount_supported': v.amount_supported,
            'comments': v.comments or '',
            'voted_at': v.voted_at,
        })
    progress = []
    for p in LoanApprovalLevelProgress.objects.filter(loan_request=loan_request).select_related(
        'level',
    ).order_by('level__sequence_order', 'id'):
        progress.append({
            'level': p.level.name if p.level_id else '',
            'status': p.status,
            'started_at': p.started_at,
            'completed_at': p.completed_at,
        })
    return {
        'committee_status': loan_request.committee_status,
        'committee_final_amount': getattr(loan_request, 'committee_final_amount', None),
        'votes': votes,
        'level_progress': progress,
    }


def build_signatures_meta(agreement) -> Dict[str, Any]:
    sigs = []
    for s in agreement.signatures.filter(is_valid=True).order_by('signed_at'):
        sigs.append({
            'role': s.role,
            'role_display': s.get_role_display(),
            'signer_name': s.signer_name,
            'typed_name': s.typed_name or '',
            'signer_id_number': s.signer_id_number or '',
            'declaration_accepted': s.declaration_accepted,
            'signer_user': _user_ref(s.signer_user),
            'signature_method': getattr(s, 'signature_method', 'drawn_hash') or 'drawn_hash',
            'content_hash_at_sign': s.content_hash_at_sign,
            'signature_image_sha256': getattr(s, 'signature_image_sha256', '') or '',
            'signed_at': s.signed_at,
            'ip_address': s.ip_address,
            'user_agent': s.user_agent or '',
            'pki_certificate_serial': getattr(s, 'pki_certificate_serial', '') or '',
            'has_pki_timestamp': bool(getattr(s, 'pki_timestamp_token', '') or ''),
        })
    return {
        'agreement_id': agreement.pk,
        'kind': agreement.kind,
        'title': agreement.title,
        'status': agreement.status,
        'content_hash': agreement.content_hash,
        'generated_at': agreement.generated_at,
        'generated_by': _user_ref(agreement.generated_by),
        'signature_disclaimer': (
            'Signatures use drawn mark + SHA-256 content binding (signature_method=drawn_hash). '
            'This is electronic signature evidence for branch operations — not a PKI / qualified '
            'e-signature. Fields pki_* are reserved for future CA/TSP integration.'
        ),
        'signatures': sigs,
    }


def build_cbs_attempts_payload(loan_request) -> Dict[str, Any]:
    from loans.models import CbsBookingAttempt

    rows = []
    for a in CbsBookingAttempt.objects.filter(loan_request=loan_request).order_by('attempted_at'):
        rows.append({
            'id': a.pk,
            'attempted_at': a.attempted_at,
            'attempted_by': _user_ref(a.attempted_by),
            'provider': a.provider,
            'status': a.status,
            'booking_ref': a.booking_ref,
            'loan_account': a.loan_account,
            'message': a.message,
            'idempotency_key': a.idempotency_key,
        })
    return {
        'current': {
            'booking_status': loan_request.cbs_booking_status or '',
            'booking_ref': loan_request.cbs_booking_ref or '',
            'loan_account': loan_request.cbs_loan_account or '',
            'booked_at': loan_request.cbs_booked_at,
        },
        'attempts': rows,
    }


def build_loan_audit_pack_zip(
    loan_request,
    *,
    exported_by=None,
    include_collateral_dossier: bool = True,
) -> Tuple[bytes, Dict[str, Any]]:
    """
    Build the compliance ZIP. Returns (zip_bytes, manifest_dict).
    """
    from loans.models import LoanAgreement, LoanCollateralLegalDocument, LoanRequestDocument

    root = f'DECSI-audit-{_safe_slug(loan_request.loan_request_id, "loan")}'
    file_hashes: Dict[str, str] = {}
    notes: List[str] = []
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        readme = (
            'DECSI Loan Hub — loan audit / compliance export pack\n'
            f'Schema: {SCHEMA_VERSION}\n'
            f'Loan: {loan_request.loan_request_id}\n'
            f'Exported: {timezone.now().isoformat()}\n\n'
            'Contents are for internal audit reconstructability.\n'
            'Agreement signatures are drawn_hash evidence (not PKI/qualified e-sign).\n'
            'CBS section may be mock or live depending on bank configuration.\n'
            'Verify file integrity using manifest.json → files_sha256.\n'
        )
        _add_bytes(zf, f'{root}/README.txt', readme.encode('utf-8'), file_hashes)

        summary = build_loan_summary(loan_request)
        _add_bytes(zf, f'{root}/01_summary/loan_summary.json', _dumps(summary), file_hashes)

        # Documents
        docs_index = []
        for doc in LoanRequestDocument.objects.filter(loan_request=loan_request).select_related(
            'document_type', 'uploaded_by',
        ).order_by('document_type__order', 'id'):
            entry = {
                'id': doc.pk,
                'document_type': doc.document_type.name if doc.document_type_id else '',
                'auth_status': doc.auth_status,
                'uploaded_at': doc.uploaded_at,
                'uploaded_by': _user_ref(doc.uploaded_by),
                'original_filename': doc.get_display_filename() if hasattr(doc, 'get_display_filename') else '',
                'file_sha256': doc.file_sha256 or '',
                'relative_path': '',
            }
            if doc.file:
                ext = Path(doc.file.name).suffix or '.bin'
                arc = (
                    f'{root}/02_documents/'
                    f'{_safe_slug(doc.document_type.name if doc.document_type_id else "doc")}_{doc.pk}{ext}'
                )
                try:
                    with doc.file.open('rb') as fh:
                        blob = fh.read()
                    _add_bytes(zf, arc, blob, file_hashes)
                    entry['relative_path'] = arc[len(root) + 1:]
                    if not entry['file_sha256']:
                        entry['file_sha256'] = _sha256_bytes(blob)
                except Exception as exc:
                    notes.append(f'Document {doc.pk} skipped: {exc}')
            docs_index.append(entry)
        _add_bytes(zf, f'{root}/02_documents/documents_index.json', _dumps(docs_index), file_hashes)

        # Appraisal PDF
        try:
            from loans.appraisal_pack_pdf import build_appraisal_pack_pdf
            pdf_bytes, engine = build_appraisal_pack_pdf(loan_request)
            _add_bytes(zf, f'{root}/03_appraisal/appraisal_pack.pdf', pdf_bytes, file_hashes)
            _add_bytes(
                zf,
                f'{root}/03_appraisal/engine.txt',
                f'{engine}\n'.encode('utf-8'),
                file_hashes,
            )
        except Exception as exc:
            notes.append(f'Appraisal PDF unavailable: {exc}')
            _add_bytes(
                zf,
                f'{root}/03_appraisal/ERROR.txt',
                f'Could not build appraisal PDF: {exc}\n'.encode('utf-8'),
                file_hashes,
            )

        # Committee
        votes = build_votes_payload(loan_request)
        _add_bytes(zf, f'{root}/04_committee/votes.json', _dumps(votes), file_hashes)

        # Closing legal
        legal_index = []
        for legal in LoanCollateralLegalDocument.objects.filter(
            loan_request=loan_request,
        ).select_related('uploaded_by', 'verified_by').order_by('kind', 'id'):
            kind = legal.kind or 'legal'
            entry = {
                'id': legal.pk,
                'doc_kind': kind,
                'status': legal.status,
                'reference_number': legal.reference_number or '',
                'verified_at': getattr(legal, 'verified_at', None),
                'verified_by': _user_ref(getattr(legal, 'verified_by', None)),
                'uploaded_at': getattr(legal, 'created_at', None),
                'uploaded_by': _user_ref(getattr(legal, 'uploaded_by', None)),
                'relative_path': '',
            }
            if legal.file:
                ext = Path(legal.file.name).suffix or '.bin'
                arc = f'{root}/05_closing_legal/{_safe_slug(kind)}_{legal.pk}{ext}'
                try:
                    with legal.file.open('rb') as fh:
                        blob = fh.read()
                    _add_bytes(zf, arc, blob, file_hashes)
                    entry['relative_path'] = arc[len(root) + 1:]
                except Exception as exc:
                    notes.append(f'Legal doc {legal.pk} skipped: {exc}')
            legal_index.append(entry)
        _add_bytes(zf, f'{root}/05_closing_legal/legal_index.json', _dumps(legal_index), file_hashes)

        # Agreement
        agreement = (
            LoanAgreement.objects.filter(loan_request=loan_request)
            .exclude(status='void')
            .order_by('-generated_at')
            .first()
        )
        if agreement:
            _add_bytes(
                zf,
                f'{root}/06_agreement/agreement_body.txt',
                (agreement.body_text or '').encode('utf-8'),
                file_hashes,
            )
            meta = build_signatures_meta(agreement)
            _add_bytes(zf, f'{root}/06_agreement/signatures_meta.json', _dumps(meta), file_hashes)
            try:
                from loans.agreement_pdf import build_agreement_pdf
                pdf_bytes, _engine = build_agreement_pdf(agreement)
                _add_bytes(zf, f'{root}/06_agreement/agreement.pdf', pdf_bytes, file_hashes)
            except Exception as exc:
                notes.append(f'Agreement PDF unavailable: {exc}')
            for s in agreement.signatures.filter(is_valid=True):
                if not s.signature_image:
                    continue
                ext = Path(s.signature_image.name).suffix or '.png'
                arc = f'{root}/06_agreement/signatures/{_safe_slug(s.role)}_{s.pk}{ext}'
                try:
                    with s.signature_image.open('rb') as fh:
                        blob = fh.read()
                    _add_bytes(zf, arc, blob, file_hashes)
                except Exception as exc:
                    notes.append(f'Signature image {s.pk} skipped: {exc}')
        else:
            _add_bytes(
                zf,
                f'{root}/06_agreement/NOTE.txt',
                b'No non-void agreement generated for this loan yet.\n',
                file_hashes,
            )

        # CBS attempts
        cbs = build_cbs_attempts_payload(loan_request)
        _add_bytes(zf, f'{root}/07_cbs/booking.json', _dumps(cbs), file_hashes)

        # Optional collateral dossier
        if include_collateral_dossier:
            try:
                from collateral.dossier import dossier_zip_bytes
                coll_zip = dossier_zip_bytes(loan_request)
                _add_bytes(zf, f'{root}/08_collateral/dossier.zip', coll_zip, file_hashes)
            except Exception as exc:
                notes.append(f'Collateral dossier skipped: {exc}')

        if notes:
            _add_bytes(
                zf,
                f'{root}/EXPORT_NOTES.txt',
                ('\n'.join(notes) + '\n').encode('utf-8'),
                file_hashes,
            )

        manifest = {
            'schema_version': SCHEMA_VERSION,
            'exported_at': timezone.now().isoformat(),
            'exported_by': _user_ref(exported_by),
            'loan_request_id': loan_request.loan_request_id,
            'loan_pk': loan_request.pk,
            'root_folder': root,
            'files_sha256': file_hashes,
            'notes': notes,
        }
        # Write manifest last (without hashing itself into files_sha256 circularly —
        # include files_sha256 of other files only)
        zf.writestr(f'{root}/manifest.json', _dumps(manifest))

    return buf.getvalue(), manifest


def user_can_export_audit_pack(user, loan_request) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    role = getattr(user, 'role', None)
    if role in ('superadmin', 'admin', 'auditor', 'risk_compliance'):
        return True
    from loans.models import LoanRequest
    if loan_request.committee_status == LoanRequest.COMMITTEE_APPROVED:
        from loans.disbursement import (
            can_manage_conditions, can_mark_disbursed, can_mark_ready,
        )
        if (
            can_manage_conditions(user, loan_request)
            or can_mark_ready(user, loan_request)
            or can_mark_disbursed(user, loan_request)
        ):
            return True
    try:
        from loans.committee import user_can_view_committee_loan
        if user_can_view_committee_loan(user, loan_request):
            return True
    except Exception:
        pass
    return False
