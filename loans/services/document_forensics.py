"""Heuristic document quality, near-duplicate, and authenticity scoring.

Scores are officer aids, not a court-grade authenticator.
"""

from __future__ import annotations

import hashlib
import io
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_IMAGE_EXTS = ('jpg', 'jpeg', 'png', 'gif', 'webp')
_SCAN_EXTS = _IMAGE_EXTS + ('pdf',)


def _ext(filename: str) -> str:
    name = filename or ''
    if '.' not in name:
        return ''
    return name.rsplit('.', 1)[-1].lower().lstrip('.')


def _open_preview_image(raw: bytes, ext: str):
    """First page / image as RGB PIL Image, or None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    ext = (ext or '').lower()
    try:
        if ext in _IMAGE_EXTS:
            img = Image.open(io.BytesIO(raw))
            return img.convert('RGB')
        if ext == 'pdf':
            try:
                from pdf2image import convert_from_bytes
                pages = convert_from_bytes(raw, first_page=1, last_page=1, dpi=110)
                if pages:
                    return pages[0].convert('RGB')
            except Exception:
                return None
    except Exception:
        return None
    return None


def perceptual_hash_hex(raw: bytes, ext: str) -> str:
    """16×16 average hash as 64 hex chars. Empty string if not an image/PDF."""
    img = _open_preview_image(raw, ext)
    if img is None:
        return ''
    try:
        from PIL import Image
        small = img.convert('L').resize((16, 16), Image.Resampling.LANCZOS)
        pixels = list(small.getdata())
        if not pixels:
            return ''
        avg = sum(pixels) / len(pixels)
        bits = ''.join('1' if p >= avg else '0' for p in pixels)
        return format(int(bits, 2), '064x')
    except Exception:
        return ''


def hamming_hex(a: str, b: str) -> int:
    if not a or not b or len(a) != len(b):
        return 64
    try:
        return bin(int(a, 16) ^ int(b, 16)).count('1')
    except ValueError:
        return 64


def quality_report(raw: bytes, ext: str, extracted_text: str = '') -> Dict[str, Any]:
    """Scan quality 0–100 with reason codes."""
    reasons: List[str] = []
    score = 100
    width = height = 0
    variance = None
    img = _open_preview_image(raw, ext) if ext in _SCAN_EXTS else None
    if img is not None:
        width, height = img.size
        min_side = min(width, height)
        if min_side < 80:
            score -= 45
            reasons.append('blur')
        elif min_side < 400:
            score -= 20
            reasons.append('low_resolution')
        try:
            from PIL import Image
            gray = img.convert('L').resize((64, 64), Image.Resampling.BILINEAR)
            px = list(gray.getdata())
            mean = sum(px) / len(px)
            variance = sum((p - mean) ** 2 for p in px) / len(px)
            if variance < 80:
                score -= 25
                if 'blur' not in reasons:
                    reasons.append('blur')
            elif variance < 180:
                score -= 10
        except Exception:
            pass
    elif ext in _SCAN_EXTS:
        score -= 15
        reasons.append('unreadable_preview')

    text = (extracted_text or '').strip()
    if ext in _SCAN_EXTS and len(text) < 8:
        score -= 30
        reasons.append('empty_ocr')

    if not raw:
        score = 0
        reasons = ['empty_file']

    score = max(0, min(100, score))
    return {
        'score': score,
        'reasons': reasons,
        'width': width,
        'height': height,
        'variance': round(variance, 1) if variance is not None else None,
        'ocr_chars': len(text),
    }


def find_near_duplicates(phash: str, *, exclude_loan_id=None, exclude_pk=None) -> List[Dict[str, Any]]:
    """Other loans whose perceptual hash is close (Hamming ≤ 10). Cap at 5.

    Strategy: exact hash (indexed) → same 8-hex prefix bucket → recent scan.
    """
    if not phash:
        return []
    from django.conf import settings
    from loans.models import LoanRequestDocument

    scan_limit = int(getattr(settings, 'DOCUMENT_NEAR_DUP_SCAN_LIMIT', 800) or 800)
    qs = LoanRequestDocument.objects.exclude(perceptual_hash='').select_related('loan_request')
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    hits: List[Dict[str, Any]] = []
    seen_pks = set()

    def _consider(row, dist: int):
        if row.pk in seen_pks:
            return
        if dist > 10:
            return
        if exclude_loan_id and row.loan_request_id == exclude_loan_id and dist == 0:
            return
        seen_pks.add(row.pk)
        hits.append({
            'document_id': row.pk,
            'loan_request_id': getattr(row.loan_request, 'loan_request_id', ''),
            'distance': dist,
            'same_loan': row.loan_request_id == exclude_loan_id,
        })

    for row in qs.filter(perceptual_hash=phash)[:10]:
        _consider(row, 0)
        if len(hits) >= 5:
            return hits

    prefix = phash[:8]
    if len(prefix) >= 4:
        for row in qs.filter(perceptual_hash__startswith=prefix).exclude(perceptual_hash=phash)[:200]:
            dist = hamming_hex(phash, row.perceptual_hash)
            _consider(row, dist)
            if len(hits) >= 5:
                return hits

    for row in qs.order_by('-id')[:scan_limit]:
        if row.pk in seen_pks:
            continue
        dist = hamming_hex(phash, row.perceptual_hash)
        _consider(row, dist)
        if len(hits) >= 5:
            break
    return hits


def authenticity_score(
    *,
    base_passed: bool,
    quality: int,
    identity_passed: Optional[bool],
    duplicate_other: bool,
    near_dup_other: bool,
    content_failed: bool,
    layout_fail: bool,
    extra_reasons: Optional[List[str]] = None,
) -> Tuple[int, List[str]]:
    score = 100 if base_passed else 45
    reasons: List[str] = list(extra_reasons or [])
    if quality < 40:
        score -= 25
        if 'blur' not in reasons:
            reasons.append('blur')
    elif quality < 60:
        score -= 10
    if identity_passed is False:
        score -= 35
        reasons.append('identity_mismatch')
    if duplicate_other:
        score -= 20
        reasons.append('reuse_other_loan')
    if near_dup_other and 'reuse_other_loan' not in reasons:
        score -= 12
        reasons.append('reuse_other_loan')
    if content_failed:
        score -= 25
        reasons.append('layout_fail')
    if layout_fail and 'layout_fail' not in reasons:
        score -= 15
        reasons.append('layout_fail')
    score = max(0, min(100, score))
    return score, reasons


def applicant_facing(report: Dict[str, Any]) -> Dict[str, Any]:
    """Short messages for Digital Apply — no forensic internals."""
    checks = report or {}
    quality = (checks.get('forensics') or {}).get('quality') or {}
    identity = checks.get('identity_match') or {}
    reasons = list((checks.get('forensics') or {}).get('reasons') or [])
    raw_score = quality.get('score')
    qscore = int(100 if raw_score is None else raw_score)
    auth_status = checks.get('auth_status') or ''
    readable = qscore >= 40
    match = identity.get('passed')
    retake = False
    message = 'Document received.'
    if qscore < 40 or 'empty_file' in reasons:
        retake = True
        message = 'Retake a clearer photo or scan — this file is not readable.'
    elif auth_status == 'rejected':
        retake = True
        message = 'This file was rejected. Upload a different scan of the original.'
    elif match is False:
        message = 'Name or ID on this scan may not match — the branch will review it.'
    elif match is True:
        message = 'Identity details match this document.'
    elif readable:
        message = 'Document looks readable.'
    return {
        'readable': readable,
        'identity_match': match,
        'retake': retake,
        'message': message,
        'block_fee': bool(retake),
    }


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw or b'').hexdigest()
