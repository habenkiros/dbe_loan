"""Automated + optional AI/external checks for loan application documents."""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def _ocr_lang() -> str:
    return getattr(settings, 'DOCUMENT_OCR_LANG', 'eng+amh') or 'eng'


def _ocr_image(img) -> str:
    import pytesseract
    return pytesseract.image_to_string(img, lang=_ocr_lang())


_MAGIC = {
    "pdf": (b"%PDF",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "gif": (b"GIF87a", b"GIF89a"),
}


def get_document_auth_policy():
    try:
        from loans.models import DocumentAuthenticationPolicy
    except Exception:
        return None
    obj = DocumentAuthenticationPolicy.objects.first()
    if obj:
        return obj
    return DocumentAuthenticationPolicy()


def _read_upload_bytes(uploaded_file) -> bytes:
    """Read full upload content once without using chunks() on a closed handle."""
    if isinstance(uploaded_file, (bytes, bytearray)):
        return bytes(uploaded_file)

    from django.core.files.uploadedfile import TemporaryUploadedFile, InMemoryUploadedFile

    if isinstance(uploaded_file, TemporaryUploadedFile):
        try:
            with open(uploaded_file.temporary_file_path(), 'rb') as fp:
                return fp.read()
        except (ValueError, OSError, FileNotFoundError):
            pass

    if isinstance(uploaded_file, InMemoryUploadedFile):
        try:
            uploaded_file.open()
            uploaded_file.seek(0)
            data = uploaded_file.read()
            return data if isinstance(data, bytes) else (data or '').encode()
        except (ValueError, OSError, AttributeError):
            pass

    if hasattr(uploaded_file, 'read'):
        try:
            if hasattr(uploaded_file, 'seek'):
                try:
                    uploaded_file.seek(0)
                except (ValueError, OSError):
                    pass
            data = uploaded_file.read()
            return data if isinstance(data, bytes) else (data or '').encode()
        except (ValueError, OSError, AttributeError):
            pass
    return b''


def validate_upload_bytes(
    raw: bytes,
    filename: str,
    doc_type,
    loan_request=None,
) -> Tuple[bool, List[str]]:
    """Validate pre-read upload bytes (extension, size, magic, content, identity)."""
    errors: List[str] = []
    name = filename or ''
    ext = (os.path.splitext(name)[1] or '').lower().lstrip('.')
    if not ext:
        errors.append('File has no extension.')
    allowed = set(doc_type.get_allowed_extensions_list())
    if ext and ext not in allowed:
        errors.append(
            f'Extension ".{ext}" is not allowed for "{doc_type.name}" '
            f'(allowed: {", ".join(sorted(allowed))}).'
        )

    size = len(raw)
    max_mb = doc_type.get_max_file_size_mb()
    max_bytes = int(max_mb) * 1024 * 1024
    if size == 0:
        errors.append('File is empty.')
    elif size > max_bytes:
        errors.append(f'File is too large ({size / (1024 * 1024):.1f} MB). Maximum for this type is {max_mb} MB.')

    if not errors and ext and raw:
        head = raw[:16]
        if ext in _MAGIC or ext in ('doc', 'docx'):
            if not _mime_magic_ok(ext, head):
                errors.append(
                    f'File content does not match extension ".{ext}" '
                    '(possible wrong type or renamed file).'
                )

    extracted_text = ''
    needs_text = (
        (not errors and doc_type.has_content_validation() and raw)
        or (not errors and loan_request and doc_type.enable_ocr_match and raw and _is_content_scannable(ext))
    )
    if needs_text:
        extracted_text = (_extract_text_from_bytes(raw, ext).get('text') or '')

    if not errors and doc_type.has_content_validation() and raw:
        content_ok, content_errors, _ = validate_upload_content_from_bytes(
            raw, doc_type, ext, pre_extracted_text=extracted_text,
        )
        if not content_ok and doc_type.content_validation_strict:
            errors.extend(content_errors)

    if not errors and loan_request and doc_type.enable_ocr_match:
        if not extracted_text and raw and _is_content_scannable(ext):
            extracted_text = (_extract_text_from_bytes(raw, ext).get('text') or '')
        if not extracted_text.strip():
            if doc_type.identity_match_strict:
                errors.append(
                    f'"{doc_type.name}": could not read text for identity check — use a clearer scan or JPG/PNG.'
                )
        else:
            identity = _loan_identity_match(
                loan_request,
                extracted_text,
                doc_type.get_identity_match_field_list(),
            )
            if not identity.get('passed') and doc_type.identity_match_strict:
                failed = [
                    f'{k} ({v.get("detail", "no match")})'
                    for k, v in (identity.get('checks') or {}).items()
                    if v.get('matched') is False
                ]
                errors.append(
                    f'"{doc_type.name}": identity check failed — document does not match loan data. '
                    f'Failed: {"; ".join(failed) or identity.get("summary", "see checks")}.'
                )

    return (not errors, errors)


def validate_upload_file(uploaded_file, doc_type, loan_request=None) -> Tuple[bool, List[str], bytes]:
    """Read upload once, then validate."""
    raw = _read_upload_bytes(uploaded_file)
    ok, errors = validate_upload_bytes(
        raw, getattr(uploaded_file, 'name', '') or '', doc_type, loan_request=loan_request,
    )
    return ok, errors, raw


def _peek_upload_head(uploaded_file, nbytes: int = 16) -> bytes:
    """Read file header and rewind so Django can save the upload."""
    return _read_upload_bytes(uploaded_file)[:nbytes]


def replace_documents_for_type(loan_request, doc_type) -> int:
    """Remove existing uploads for this loan + document type (one file per type)."""
    from loans.models import LoanRequestDocument

    removed = 0
    for old in LoanRequestDocument.objects.filter(loan_request=loan_request, document_type=doc_type):
        if old.file:
            old.file.delete(save=False)
        old.delete()
        removed += 1
    return removed


def get_type_auth_rules(document) -> Dict[str, Any]:
    """Per document-type rules with bank-wide fallback."""
    doc_type = document.document_type
    policy = get_document_auth_policy()
    return {
        'allowed_extensions': set(doc_type.get_allowed_extensions_list()),
        'max_file_size_mb': doc_type.get_max_file_size_mb(),
        'require_officer_verification': doc_type.require_officer_verification,
        'enable_ocr_match': doc_type.enable_ocr_match,
        'identity_match_fields': doc_type.get_identity_match_field_list(),
        'identity_match_strict': getattr(doc_type, 'identity_match_strict', False),
        'enable_llm_check': doc_type.enable_llm_check,
        'enable_external_id': doc_type.enable_external_id,
        'content_validation': doc_type.has_content_validation(),
        'content_validation_strict': doc_type.content_validation_strict,
        'require_verified_for_collateral': getattr(
            policy, 'require_verified_documents_for_collateral', True,
        ),
        'document_type_name': doc_type.name,
    }


def _read_file_head_and_hash(file_field, chunk_size: int = 65536) -> Tuple[str, bytes]:
    hasher = hashlib.sha256()
    head = b""
    file_field.open("rb")
    try:
        first = True
        while True:
            chunk = file_field.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
            if first:
                head = chunk[:16]
                first = False
    finally:
        file_field.close()
    return hasher.hexdigest(), head


def _mime_magic_ok(ext: str, head: bytes) -> bool:
    ext = (ext or "").lower()
    if ext in ("doc", "docx"):
        return head[:2] == b"PK" or head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    sigs = _MAGIC.get(ext, ())
    if not sigs:
        return False
    return any(head.startswith(s) for s in sigs)


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _is_pdf_or_image(ext: str) -> bool:
    return (ext or "").lower() in ("pdf", "jpg", "jpeg", "png", "gif", "webp")


def _is_content_scannable(ext: str) -> bool:
    return _is_pdf_or_image(ext) or (ext or "").lower() in ("doc", "docx")


def _extract_docx_text(raw: bytes) -> str:
    import zipfile
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        xml_bytes = archive.read('word/document.xml')
    root = ET.fromstring(xml_bytes)
    parts: List[str] = []
    for elem in root.iter():
        if elem.tag.endswith('}t') and elem.text:
            parts.append(elem.text)
    return ' '.join(parts)


def _ocr_pdf_pages(raw: bytes, max_pages: int = 5) -> Tuple[str, Optional[str]]:
    """OCR scanned PDF pages via poppler + tesseract."""
    try:
        from pdf2image import convert_from_bytes
        from PIL import Image
    except ImportError:
        return '', 'pdf2image not installed'
    try:
        images = convert_from_bytes(raw, first_page=1, last_page=max_pages, dpi=200)
    except Exception as exc:
        return '', f'PDF to image failed (is poppler installed?): {exc}'
    parts: List[str] = []
    for img in images:
        if not isinstance(img, Image.Image):
            continue
        parts.append(_ocr_image(img))
    text = '\n'.join(parts)
    return text, None if text.strip() else 'OCR returned empty text for PDF pages.'


def _extract_text_from_bytes(raw: bytes, ext: str) -> Dict[str, Any]:
    result = {"text": "", "method": None, "error": None, "char_count": 0}
    ext = (ext or "").lower()

    if ext == "pdf":
        text = ''
        method = None
        error = None
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            parts: List[str] = []
            for page in reader.pages[:15]:
                parts.append(page.extract_text() or "")
            text = "\n".join(parts)
            if text.strip():
                method = 'pypdf'
        except Exception as exc:
            error = f"PDF text extraction failed: {exc}"
        if not text.strip():
            ocr_text, ocr_err = _ocr_pdf_pages(raw)
            if ocr_text.strip():
                text = ocr_text
                method = 'pdf_ocr'
                error = None
            elif ocr_err:
                error = ocr_err
            elif not error:
                error = "PDF has no extractable text and OCR found nothing."
        result.update({"text": text, "method": method, "char_count": len(text), "error": error})
        return result

    if ext in ("jpg", "jpeg", "png", "gif", "webp"):
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(raw))
            text = _ocr_image(img)
            result.update({"text": text, "method": "pytesseract", "char_count": len(text)})
            if not text.strip():
                result["error"] = "OCR returned empty text — image may be blank or unreadable."
            return result
        except Exception as exc:
            result["error"] = f"Image OCR failed/unavailable: {exc}"
            return result

    if ext in ("doc", "docx"):
        try:
            text = _extract_docx_text(raw)
            result.update({"text": text, "method": "docx_xml", "char_count": len(text)})
            if not text.strip():
                result["error"] = "DOCX has no readable text."
            return result
        except Exception as exc:
            result["error"] = f"DOCX text extraction failed: {exc}"
            return result

    result["error"] = f"Text extraction not supported for .{ext} files."
    return result


def _extract_text_best_effort(file_field, ext: str) -> Dict[str, Any]:
    file_field.open("rb")
    try:
        raw = file_field.read()
    finally:
        file_field.close()
    return _extract_text_from_bytes(raw, ext)


def _match_content_phrases(text: str, phrases: List[str], min_matches: int) -> Dict[str, Any]:
    text_norm = _normalize(text)
    matched: List[str] = []
    missing: List[str] = []
    for phrase in phrases:
        p_norm = _normalize(phrase)
        if len(p_norm) < 2:
            continue
        if p_norm in text_norm:
            matched.append(phrase)
        else:
            missing.append(phrase)
    required = max(1, min(min_matches, len(phrases)))
    return {
        'passed': len(matched) >= required,
        'min_matches': required,
        'matched': matched,
        'missing': missing,
        'total_phrases': len(phrases),
        'match_count': len(matched),
    }


def validate_upload_content_from_bytes(
    raw: bytes,
    doc_type,
    ext: str,
    pre_extracted_text: str = '',
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Check extracted document text against phrases and/or reference sample."""
    phrases = doc_type.get_effective_validation_phrases()
    uses_reference = bool(
        doc_type.use_reference_sample_validation
        and (doc_type.reference_sample_profile or {}).get('validation_phrases'),
    )
    report: Dict[str, Any] = {
        'enabled': bool(phrases) or uses_reference,
        'phrases': phrases,
        'uses_reference_sample': uses_reference,
        'min_matches': doc_type.content_validation_min_matches,
        'passed': True,
    }
    if not phrases and not uses_reference:
        return True, [], report

    ext = (ext or '').lower().lstrip('.')
    if not _is_content_scannable(ext):
        msg = (
            f'"{doc_type.name}" requires content validation but .{ext} cannot be scanned. '
            'Upload PDF, image, or DOCX.'
        )
        report.update({'passed': False, 'error': msg})
        return False, [msg], report

    if pre_extracted_text:
        extraction = {
            'text': pre_extracted_text,
            'method': 'pre_extracted',
            'error': None,
            'char_count': len(pre_extracted_text),
        }
    else:
        extraction = _extract_text_from_bytes(raw, ext)
    report['extract'] = {
        'method': extraction.get('method'),
        'error': extraction.get('error'),
        'char_count': extraction.get('char_count'),
    }
    text = extraction.get('text') or ''
    if extraction.get('error') and not text.strip():
        msg = (
            f'Could not read text from "{doc_type.name}" for content validation: '
            f'{extraction["error"]}'
        )
        report.update({'passed': False, 'error': msg})
        return False, [msg], report

    errors: List[str] = []
    if phrases:
        match = _match_content_phrases(text, phrases, doc_type.content_validation_min_matches)
        report['phrase_match'] = match
        if not match['passed']:
            missing_preview = ', '.join(match['missing'][:5])
            if len(match['missing']) > 5:
                missing_preview += ', …'
            errors.append(
                f'"{doc_type.name}" does not match expected phrases — '
                f'found {match["match_count"]}/{match["min_matches"]} required. '
                f'Missing: {missing_preview or "—"}.'
            )

    if uses_reference:
        from loans.services.reference_sample import compare_text_to_reference
        ref_match = compare_text_to_reference(text, doc_type)
        report['reference_match'] = ref_match
        if ref_match.get('enabled') and not ref_match.get('passed'):
            errors.append(
                f'"{doc_type.name}" does not match the official reference sample '
                f'({ref_match.get("phrase_match", {}).get("match_count", 0)} phrases, '
                f'similarity {ref_match.get("text_similarity", 0)}).'
            )

    if errors:
        report.update({'passed': False, 'error': errors[0]})
        return False, errors, report

    return True, [], report


def validate_upload_content(uploaded_file, doc_type, ext: str) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Check upload file content (reads bytes once)."""
    raw = _read_upload_bytes(uploaded_file)
    return validate_upload_content_from_bytes(raw, doc_type, ext)


def _get_loan_basic_info(loan_request):
    try:
        from loans.models import LoanRequestBasicInfo
        return LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()
    except Exception:
        return None


def _match_name_tokens(name: str, text_norm: str) -> Tuple[bool, str]:
    if not name:
        return False, 'No name provided.'
    tokens = [t for t in _normalize(name).split() if len(t) > 2]
    if tokens:
        hits = sum(1 for t in tokens if t in text_norm)
        matched = hits >= max(1, len(tokens) // 2)
        return matched, f'Matched {hits}/{len(tokens)} name tokens.'
    matched = _normalize(name) in text_norm
    return matched, 'Full-name substring match.' if matched else 'Name not found in document.'


def _loan_identity_match(loan_request, extracted_text: str, field_names: Optional[List[str]] = None) -> Dict[str, Any]:
    """Compare loan registration data against OCR text from an upload."""
    fields = field_names or ['applicant_name', 'phone_number', 'tin_number']
    text_norm = _normalize(extracted_text)
    text_digits = _digits_only(extracted_text)
    basic_info = _get_loan_basic_info(loan_request)

    checks: Dict[str, Any] = {}
    for field in fields:
        if field == 'applicant_name':
            value = getattr(loan_request, 'applicant_name', '') or ''
            if not value:
                checks[field] = {'matched': None, 'skipped': True, 'detail': 'No applicant name on loan request.', 'value': None}
            else:
                matched, detail = _match_name_tokens(value, text_norm)
                checks[field] = {'matched': matched, 'skipped': False, 'detail': detail, 'value': value}
        elif field == 'phone_number':
            value = getattr(loan_request, 'phone_number', '') or ''
            digits = _digits_only(value)
            if not digits or len(digits) < 8:
                checks[field] = {'matched': None, 'skipped': True, 'detail': 'No phone number on loan request.', 'value': value or None}
            else:
                matched = digits in text_digits
                checks[field] = {
                    'matched': matched,
                    'skipped': False,
                    'detail': 'Phone digits found in document.' if matched else 'Phone number not found in document.',
                    'value': value,
                }
        elif field == 'tin_number':
            value = getattr(basic_info, 'tin_number', '') if basic_info else ''
            value = value or ''
            digits = _digits_only(value)
            if not digits:
                checks[field] = {'matched': None, 'skipped': True, 'detail': 'No TIN on loan request.', 'value': None}
            else:
                matched = digits in text_digits
                checks[field] = {
                    'matched': matched,
                    'skipped': False,
                    'detail': 'TIN found in document.' if matched else 'TIN not found in document.',
                    'value': value,
                }
        elif field == 'business_name':
            value = ''
            if basic_info:
                value = getattr(basic_info, 'business_name', '') or ''
            if not value:
                value = getattr(loan_request, 'applicant_name', '') or ''
            if not value:
                checks[field] = {'matched': None, 'skipped': True, 'detail': 'No business name on loan request.', 'value': None}
            else:
                matched, detail = _match_name_tokens(value, text_norm)
                checks[field] = {'matched': matched, 'skipped': False, 'detail': detail, 'value': value}
        else:
            checks[field] = {'matched': None, 'skipped': True, 'detail': f'Unknown field "{field}".', 'value': None}

    active = [f for f in fields if f in checks and not checks[f].get('skipped')]
    if not active:
        passed = True
        summary = 'No identity data on loan request to compare.'
    else:
        passed = all(checks[f].get('matched') for f in active)
        failed = [f for f in active if not checks[f].get('matched')]
        matched = [f for f in active if checks[f].get('matched')]
        summary = f'Matched {len(matched)}/{len(active)} fields'
        if failed:
            summary += f' — failed: {", ".join(failed)}'

    score = 0
    if checks.get('applicant_name', {}).get('matched'):
        score += 60
    if checks.get('tin_number', {}).get('matched'):
        score += 40
    if checks.get('phone_number', {}).get('matched'):
        score += 25
    if checks.get('business_name', {}).get('matched'):
        score += 35
    min_score = int(getattr(settings, 'DOCUMENT_OCR_MATCH_MIN_SCORE', 60) or 60)

    return {
        'fields': fields,
        'checks': checks,
        'passed': passed,
        'summary': summary,
        'match_score': score,
        'min_score': min_score,
        'applicant_name': getattr(loan_request, 'applicant_name', '') or None,
        'tin_number': (getattr(basic_info, 'tin_number', '') if basic_info else '') or None,
        'name_match': checks.get('applicant_name', {}).get('matched'),
        'name_detail': checks.get('applicant_name', {}).get('detail'),
        'tin_match': checks.get('tin_number', {}).get('matched'),
    }


def _sheet1_identity_match(document, extracted_text: str) -> Dict[str, Any]:
    doc_type = document.document_type
    fields = doc_type.get_identity_match_field_list() if hasattr(doc_type, 'get_identity_match_field_list') else None
    return _loan_identity_match(document.loan_request, extracted_text, fields)


def _llm_bank_statement_plausibility(document, ocr_text_preview: str) -> Dict[str, Any]:
    provider = (getattr(settings, "DOCUMENT_LLM_PROVIDER", "") or "openai").lower()
    openai_key = getattr(settings, "OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
    gemini_key = getattr(settings, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")

    if provider == "openai" and not openai_key:
        return {"enabled": False, "error": "OPENAI_API_KEY not configured.", "provider": "openai"}
    if provider == "gemini" and not gemini_key:
        return {"enabled": False, "error": "GEMINI_API_KEY not configured.", "provider": "gemini"}

    lr = document.loan_request
    prompt = f"""You are a bank document reviewer.
Question: Does the following text look like a real bank statement? Answer for a human officer.
Return JSON only.

Applicant name (Sheet 1): {getattr(lr, "applicant_name", "")}
Loan request ID: {getattr(lr, "loan_request_id", lr.pk)}
Document type: {document.document_type.name}

Text (truncated):
{(ocr_text_preview or "")[:3500]}

JSON format:
{{
  "plausible": true|false|null,
  "confidence": 0.0-1.0,
  "summary": "2-4 sentences",
  "red_flags": ["..."]
}}
"""
    try:
        if provider == "gemini":
            model = getattr(settings, "GEMINI_DOCUMENT_MODEL", "gemini-1.5-flash")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
            resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=60)
            if resp.status_code != 200:
                return {"enabled": True, "provider": "gemini", "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            model = getattr(settings, "OPENAI_DOCUMENT_MODEL", "gpt-4o-mini")
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You respond with valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                },
                timeout=60,
            )
            if resp.status_code != 200:
                return {"enabled": True, "provider": "openai", "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
            data = resp.json()
            text = data["choices"][0]["message"]["content"]

        import json
        content = (text or "").strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        parsed = json.loads(content)
        parsed.update({"enabled": True, "provider": provider, "checked_at": timezone.now().isoformat()})
        return parsed
    except Exception as exc:
        return {"enabled": True, "provider": provider, "error": str(exc), "checked_at": timezone.now().isoformat()}


def _external_id_verification(document) -> Dict[str, Any]:
    lr = document.loan_request
    tin = ""
    try:
        from loans.models import LoanRequestBasicInfo
        bi = LoanRequestBasicInfo.objects.filter(loan_request=lr).first()
        tin = getattr(bi, "tin_number", "") or ""
    except Exception:
        tin = ""

    url = getattr(settings, "EXTERNAL_ID_VERIFY_URL", "") or os.getenv("EXTERNAL_ID_VERIFY_URL", "")
    if url:
        payload = {
            "loan_request_id": getattr(lr, "loan_request_id", lr.pk),
            "document_type": document.document_type.name,
            "document_sha256": getattr(document, "file_sha256", ""),
            "tin": tin,
            "applicant_name": getattr(lr, "applicant_name", ""),
            "filename": getattr(document, "original_filename", ""),
        }
        try:
            resp = requests.post(url, json=payload, timeout=45)
            if resp.status_code != 200:
                return {
                    "enabled": True,
                    "provider": "external_id_service",
                    "status": "error",
                    "http_status": resp.status_code,
                    "error": resp.text[:300],
                }
            try:
                body = resp.json()
            except ValueError:
                body = {"raw": resp.text[:500]}
            return {
                "enabled": True,
                "provider": "external_id_service",
                "status": body.get("status", "ok"),
                "verified": body.get("verified"),
                "detail": body,
                "checked_at": timezone.now().isoformat(),
            }
        except Exception as exc:
            return {"enabled": True, "provider": "external_id_service", "status": "error", "error": str(exc)}

    try:
        from .customer import fetch_customer_by_number
        lookup_id = _digits_only(tin) or str(getattr(lr, "customer_number", "") or "")
        if not lookup_id:
            return {"enabled": True, "provider": "decsi_party_api", "skipped": True, "reason": "No TIN/customer number."}
        customer = fetch_customer_by_number(lookup_id)
        return {
            "enabled": True,
            "provider": "decsi_party_api",
            "found": bool(customer),
            "customer": customer,
            "checked_at": timezone.now().isoformat(),
        }
    except Exception as exc:
        return {"enabled": True, "provider": "decsi_party_api", "status": "error", "error": str(exc)}


def run_automated_document_checks(document) -> Dict[str, Any]:
    from loans.models import LoanRequestDocument

    rules = get_type_auth_rules(document)
    messages: List[str] = []
    file_field = document.file
    if not file_field:
        messages.append("No file attached.")
        document.auth_status = LoanRequestDocument.AUTH_NEEDS_REVIEW
        document.automated_checks = {"messages": messages, "passed": False}
        document.save(update_fields=["auth_status", "automated_checks"])
        return document.automated_checks

    name = document.original_filename or os.path.basename(file_field.name)
    ext = (os.path.splitext(name)[1] or "").lower().lstrip(".")
    allowed = rules['allowed_extensions']

    try:
        size = file_field.size
    except Exception:
        size = None

    max_mb = rules['max_file_size_mb']
    max_bytes = int(max_mb) * 1024 * 1024
    size_ok = size is not None and size <= max_bytes
    if not size_ok:
        messages.append(f'File exceeds maximum size for "{rules["document_type_name"]}" ({max_mb} MB).')

    ext_ok = ext in allowed
    if not ext_ok:
        messages.append(
            f'Extension ".{ext}" is not allowed for "{rules["document_type_name"]}" '
            f'(allowed: {", ".join(sorted(allowed))}).'
        )

    sha256, head = _read_file_head_and_hash(file_field)
    document.file_sha256 = sha256
    if size is not None:
        document.file_size = size

    magic_ok = _mime_magic_ok(ext, head) if ext_ok else False
    if ext_ok and not magic_ok:
        messages.append("File content does not match its extension (possible renamed/corrupt file).")

    duplicate_qs = LoanRequestDocument.objects.filter(file_sha256=sha256).exclude(pk=document.pk)
    duplicate_same_loan = duplicate_qs.filter(loan_request_id=document.loan_request_id).exists()
    duplicate_other = duplicate_qs.exclude(loan_request_id=document.loan_request_id).exists()
    if duplicate_same_loan:
        messages.append("Duplicate file: same fingerprint already uploaded for this loan.")
    if duplicate_other:
        messages.append("Warning: same file fingerprint used on another loan request.")

    content_failed = False
    if ext_ok and magic_ok and rules['content_validation']:
        content_ok, content_msgs, content_report = validate_upload_content(file_field, document.document_type, ext)
        report_content = content_report
    else:
        content_ok, content_msgs, report_content = True, [], {}

    if content_msgs:
        messages.extend(content_msgs)
    if not content_ok:
        content_failed = True

    doc_text = ''
    if ext_ok and magic_ok and _is_content_scannable(ext):
        if report_content.get('extract') and content_ok:
            raw = _read_upload_bytes(file_field)
            doc_text = (_extract_text_from_bytes(raw, ext).get('text') or '')
        elif not rules['content_validation']:
            extraction = _extract_text_best_effort(file_field, ext)
            doc_text = extraction.get('text') or ''
            report_content = report_content or {}
            report_content['extract'] = {
                'method': extraction.get('method'),
                'error': extraction.get('error'),
                'char_count': extraction.get('char_count'),
            }
        if doc_text:
            from loans.services.appraisal_prefill import (
                extract_fields_from_text,
                parse_extraction_mappings,
            )
            report_content = report_content or {}
            report_content['extracted_text_preview'] = doc_text[:12000]
            from loans.services.document_extraction_defaults import ensure_document_type_extraction_defaults
            ensure_document_type_extraction_defaults(document.document_type)
            document.document_type.refresh_from_db()
            mappings = parse_extraction_mappings(document.document_type.content_extraction_mappings)
            if mappings:
                report_content['extracted_fields'] = extract_fields_from_text(mappings, doc_text)

    passed = size_ok and ext_ok and magic_ok and not duplicate_same_loan and not content_failed
    extracted_text_preview = doc_text[:12000] if doc_text else ''
    report: Dict[str, Any] = {
        "passed": passed,
        "rules": {
            "max_file_size_mb": max_mb,
            "allowed_extensions": sorted(allowed),
            "require_officer_verification": rules['require_officer_verification'],
            "enable_ocr_match": rules['enable_ocr_match'],
            "enable_llm_check": rules['enable_llm_check'],
            "enable_external_id": rules['enable_external_id'],
            "content_validation": rules['content_validation'],
        },
        "sha256": sha256,
        "size_ok": size_ok,
        "ext_ok": ext_ok,
        "magic_ok": magic_ok,
        "duplicate_same_loan": duplicate_same_loan,
        "duplicate_other": duplicate_other,
        "content_validation": report_content,
        "extracted_text_preview": extracted_text_preview,
        "extracted_fields": (report_content or {}).get('extracted_fields') or {},
        "messages": messages,
        "checked_at": timezone.now().isoformat(),
    }

    ocr_failed_needs_review = False
    if passed and _is_pdf_or_image(ext) and (
        rules['enable_ocr_match'] or rules['enable_llm_check'] or rules['enable_external_id']
    ):
        extraction = _extract_text_best_effort(file_field, ext)
        report["ocr_extract"] = {
            "method": extraction.get("method"),
            "error": extraction.get("error"),
            "char_count": extraction.get("char_count"),
        }
        text = extraction.get("text") or ""

        if rules['enable_ocr_match']:
            identity_fields = document.document_type.get_identity_match_field_list()
            identity = _loan_identity_match(document.loan_request, text, identity_fields)
            report['identity_match'] = identity
            report['ocr_match_sheet1'] = identity
            if extraction.get('error'):
                report['messages'].append(f'OCR: {extraction["error"]}')
            if identity.get('passed') is False:
                failed = [
                    f'{k} ({v.get("detail", "no match")})'
                    for k, v in (identity.get('checks') or {}).items()
                    if v.get('matched') is False
                ]
                report['messages'].append(
                    'Identity match failed — document does not match loan data'
                    + (f': {"; ".join(failed)}' if failed else '.')
                    + ' — verify manually.'
                )
                ocr_failed_needs_review = True

        if rules['enable_llm_check']:
            preview = text[:3500]
            report["llm_bank_statement"] = _llm_bank_statement_plausibility(document, preview)
            llm = report["llm_bank_statement"]
            if llm.get("error"):
                report["messages"].append(f"LLM: {llm['error']}")
            elif llm.get("plausible") is False and float(llm.get("confidence") or 0) >= 0.6:
                report["messages"].append("LLM flagged document as implausible — officer review required.")
                ocr_failed_needs_review = True

        if rules['enable_external_id']:
            report["external_id"] = _external_id_verification(document)
            ext_res = report["external_id"]
            if ext_res.get("error"):
                report["messages"].append(f"External ID: {ext_res['error']}")
            elif ext_res.get("verified") is False or ext_res.get("found") is False:
                report["messages"].append("External ID verification did not confirm identity.")
                ocr_failed_needs_review = True

    if not document.original_filename:
        document.original_filename = name

    document.automated_checks = report
    if not passed:
        document.auth_status = LoanRequestDocument.AUTH_NEEDS_REVIEW
    elif rules['require_officer_verification']:
        document.auth_status = LoanRequestDocument.AUTH_NEEDS_REVIEW
        report["messages"].append("This document type requires manual officer verification.")
    elif ocr_failed_needs_review:
        document.auth_status = LoanRequestDocument.AUTH_NEEDS_REVIEW
    elif duplicate_other:
        document.auth_status = LoanRequestDocument.AUTH_NEEDS_REVIEW
        if not report["messages"]:
            report["messages"].append(
                "Automated checks passed but duplicate fingerprint on another loan — manual review required."
            )
    else:
        document.auth_status = LoanRequestDocument.AUTH_AUTO_PASSED

    document.save(update_fields=["file_sha256", "file_size", "original_filename", "auth_status", "automated_checks"])

    try:
        from loans.compliance.case_engine import maybe_open_document_case
        maybe_open_document_case(
            document,
            duplicate_other=duplicate_other,
            opened_by=getattr(document, 'uploaded_by', None),
        )
    except Exception:
        logger.exception('Compliance document case hook failed for doc %s', document.pk)

    return report


def document_is_accepted_for_collateral(document) -> bool:
    from loans.models import LoanRequestDocument

    if document.document_type.require_officer_verification:
        return document.auth_status == LoanRequestDocument.AUTH_VERIFIED
    return document.auth_status in (
        LoanRequestDocument.AUTH_VERIFIED,
        LoanRequestDocument.AUTH_AUTO_PASSED,
    )


def loan_documents_collateral_readiness(loan_request) -> Dict[str, Any]:
    from loans.models import LoanRequestDocument
    from loans.document_checklist import checklist_for_loan, required_items

    policy = get_document_auth_policy()
    require_auth = getattr(policy, 'require_verified_documents_for_collateral', True)
    checklist = checklist_for_loan(loan_request)
    required_types = required_items(checklist)
    docs = list(loan_request.application_documents.select_related("document_type").all())
    by_type: Dict[int, List[Any]] = {}
    for d in docs:
        by_type.setdefault(d.document_type_id, []).append(d)

    missing_required: List[str] = []
    not_authenticated: List[str] = []
    rejected: List[str] = []
    pending_review: List[str] = []

    for item in required_types:
        dt = item.document_type
        type_docs = by_type.get(dt.id, [])
        if not type_docs:
            missing_required.append(dt.name)
            continue
        if require_auth:
            if not any(document_is_accepted_for_collateral(d) for d in type_docs):
                label = dt.name
                if dt.require_officer_verification:
                    label += ' (officer verification required)'
                not_authenticated.append(label)
        for d in type_docs:
            if d.auth_status == LoanRequestDocument.AUTH_REJECTED:
                rejected.append(f"{dt.name} ({d.get_auth_status_display()})")

    required_type_ids = {item.id for item in required_types}
    for d in docs:
        if d.document_type_id not in required_type_ids:
            continue
        if d.auth_status in (LoanRequestDocument.AUTH_PENDING, LoanRequestDocument.AUTH_NEEDS_REVIEW):
            pending_review.append(d.document_type.name)

    ready = not missing_required and not not_authenticated and not rejected and not pending_review
    return {
        "ready": ready,
        "missing_required": missing_required,
        "not_authenticated": not_authenticated,
        "rejected": rejected,
        "pending_review": pending_review,
        "checklist_count": len(checklist),
    }
