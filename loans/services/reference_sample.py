"""Official reference sample (PDF/image) per document type — analyze once, compare uploads."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

from django.utils import timezone

from loans.services.document_auth import (
    _extract_text_from_bytes,
    _match_content_phrases,
    _normalize,
)


# Label text on documents → appraisal field names (Sheet 1 / 2).
_LABEL_FIELD_HINTS = [
    (r'\btin\b|tax\s*identification|tax\s*id', 'tin_number'),
    (r'father\s*name|father\'?s\s*name', 'father_name'),
    (r'grand\s*father|grandfather', 'grandfather_name'),
    (r'mother\s*name', 'mother_name'),
    (r'\bsex\b|\bgender\b', 'gender'),
    (r'\baddress\b|residence|woreda|kebele', 'home_address'),
    (r'business\s*name|trade\s*name|company\s*name', 'business_name'),
    (r'business\s*address|office\s*address', 'business_address'),
    (r'ownership|form\s*of\s*ownership', 'form_of_ownership'),
    (r'date\s*of\s*registration|business\s*started|established', 'date_business_started'),
    (r'economic\s*sector|sector', 'economic_sector'),
    (r'credit\s*score|bureau\s*score', 'bureau_score'),
    (r'report\s*date', 'bureau_report_date'),
    (r'nbe|national\s*bank', 'nbe_credit_report_obtained'),
    (r'\bphone\b|mobile|telephone', 'phone_number'),
    (r'\bname\b|full\s*name|applicant', 'applicant_name'),
]


def _guess_field_from_label(label: str) -> Optional[str]:
    low = (label or '').lower()
    for pattern, field in _LABEL_FIELD_HINTS:
        if re.search(pattern, low):
            return field
    return None


def extract_validation_phrases_from_text(text: str, max_phrases: int = 12) -> List[str]:
    """Pick distinctive lines from reference OCR/text for upload matching."""
    if not text:
        return []
    candidates: List[Tuple[int, str]] = []
    keywords = (
        'REPUBLIC', 'ETHIOPIA', 'IDENTITY', 'LICENSE', 'CERTIFICATE', 'BANK',
        'STATEMENT', 'TRADE', 'BUSINESS', 'TIN', 'NATIONAL', 'FEDERAL', 'KEBELE',
    )
    for line in text.splitlines():
        line = line.strip()
        if len(line) < 5 or len(line) > 120:
            continue
        if re.fullmatch(r'[\d\s\.\-/]+', line):
            continue
        alpha = re.sub(r'[^A-Za-z]', '', line)
        if len(alpha) < 4:
            continue
        score = 0
        upper_ratio = sum(1 for c in line if c.isupper()) / max(len(line), 1)
        if upper_ratio > 0.5:
            score += 3
        if any(k in line.upper() for k in keywords):
            score += 4
        if 2 <= len(line.split()) <= 8:
            score += 2
        if line.endswith(':'):
            score += 1
        candidates.append((score, line.rstrip(':')))
    candidates.sort(key=lambda x: (-x[0], -len(x[1])))
    seen = set()
    phrases: List[str] = []
    for _, line in candidates:
        norm = _normalize(line)
        if norm in seen or len(norm) < 4:
            continue
        seen.add(norm)
        phrases.append(line)
        if len(phrases) >= max_phrases:
            break
    return phrases


def suggest_extraction_mappings(text: str, max_mappings: int = 15) -> List[str]:
    """Suggest field=Label lines from colon-separated labels in reference text."""
    if not text:
        return []
    mappings: List[str] = []
    seen = set()
    for match in re.finditer(
        r'(?m)^([A-Za-z][A-Za-z0-9\s\'/\-]{2,40})\s*[:：]\s*',
        text,
    ):
        label = match.group(1).strip()
        field = _guess_field_from_label(label)
        if not field:
            continue
        line = f'{field}={label}'
        if line in seen:
            continue
        seen.add(line)
        mappings.append(line)
        if len(mappings) >= max_mappings:
            break
    return mappings


def _reference_file_bytes(doc_type) -> Tuple[bytes, str]:
    if not doc_type.reference_sample:
        return b'', ''
    name = doc_type.reference_sample.name.split('/')[-1]
    ext = (name.rsplit('.', 1)[-1] if '.' in name else '').lower()
    with doc_type.reference_sample.open('rb') as fh:
        return fh.read(), ext


def analyze_reference_sample_file(doc_type) -> Dict[str, Any]:
    """OCR/extract text from the stored reference sample file."""
    raw, ext = _reference_file_bytes(doc_type)
    if not raw:
        return {'error': 'No reference sample file uploaded.'}
    extraction = _extract_text_from_bytes(raw, ext)
    text = extraction.get('text') or ''
    sha256 = hashlib.sha256(raw).hexdigest()
    phrases = extract_validation_phrases_from_text(text)
    mappings = suggest_extraction_mappings(text)
    return {
        'analyzed_at': timezone.now().isoformat(),
        'filename': doc_type.reference_sample.name.split('/')[-1],
        'extension': ext,
        'sha256': sha256,
        'extract': {
            'method': extraction.get('method'),
            'error': extraction.get('error'),
            'char_count': extraction.get('char_count'),
        },
        'extracted_text_preview': text[:15000],
        'validation_phrases': phrases,
        'suggested_mappings': mappings,
        'suggested_min_matches': max(1, min(3, len(phrases) // 2)) if phrases else 1,
    }


def process_reference_sample(
    doc_type,
    *,
    seed_empty_fields: bool = True,
    force_reseed_phrases: bool = False,
) -> Dict[str, Any]:
    """Analyze reference file and optionally seed validation / mapping fields."""
    profile = analyze_reference_sample_file(doc_type)
    if profile.get('error'):
        return profile

    doc_type.reference_sample_profile = profile
    doc_type.reference_sample_analyzed_at = timezone.now()

    if seed_empty_fields or force_reseed_phrases:
        phrases = profile.get('validation_phrases') or []
        if phrases and (force_reseed_phrases or not (doc_type.content_validation_sample or '').strip()):
            doc_type.content_validation_sample = '\n'.join(phrases)
            doc_type.content_validation_min_matches = profile.get('suggested_min_matches', 2)
            doc_type.use_reference_sample_validation = True

    if seed_empty_fields and not (doc_type.content_extraction_mappings or '').strip():
        suggested = profile.get('suggested_mappings') or []
        if suggested:
            doc_type.content_extraction_mappings = '\n'.join(suggested)

    update_fields = [
        'reference_sample_profile', 'reference_sample_analyzed_at',
        'content_validation_sample', 'content_validation_min_matches',
        'use_reference_sample_validation', 'content_extraction_mappings',
    ]
    doc_type.save(update_fields=update_fields)
    profile['seeded'] = {
        'validation_phrases': bool(profile.get('validation_phrases')),
        'suggested_mappings': bool(profile.get('suggested_mappings')),
    }
    return profile


def compare_text_to_reference(upload_text: str, doc_type) -> Dict[str, Any]:
    """Compare upload OCR text to the analyzed reference sample."""
    profile = doc_type.reference_sample_profile or {}
    if not profile.get('validation_phrases') and not profile.get('extracted_text_preview'):
        return {'enabled': False, 'passed': True}

    ref_phrases = profile.get('validation_phrases') or []
    min_matches = doc_type.content_validation_min_matches or profile.get('suggested_min_matches', 2)
    phrase_match = _match_content_phrases(upload_text or '', ref_phrases, min_matches)

    ref_norm = _normalize(profile.get('extracted_text_preview') or '')
    up_norm = _normalize(upload_text or '')
    ref_tokens = set(ref_norm.split()) - {'', 'the', 'and', 'of', 'to', 'a', 'in'}
    up_tokens = set(up_norm.split()) - {'', 'the', 'and', 'of', 'to', 'a', 'in'}
    overlap = len(ref_tokens & up_tokens)
    union = len(ref_tokens | up_tokens) or 1
    jaccard = round(overlap / union, 3)
    min_jaccard = float(doc_type.reference_min_similarity or 0.08)

    passed = phrase_match['passed'] and jaccard >= min_jaccard
    return {
        'enabled': True,
        'passed': passed,
        'phrase_match': phrase_match,
        'text_similarity': jaccard,
        'min_similarity': min_jaccard,
        'reference_filename': profile.get('filename'),
        'reference_analyzed_at': profile.get('analyzed_at'),
    }
