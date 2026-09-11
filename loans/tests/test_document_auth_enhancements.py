"""Document authentication enhancements: score gate, providers, committee gate."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from loans.models import (
    Branch,
    CollateralType,
    District,
    DocumentAuthenticationPolicy,
    LoanApplicationDocumentType,
    LoanCategory,
    LoanCategoryDocumentRequirement,
    LoanRequest,
    LoanRequestBasicInfo,
)
from loans.product_family import FAMILY_GENERAL, FAMILY_PROJECT
from loans.services.document_auth import (
    document_committee_blockers,
    extract_structured_id_cues,
    get_document_intel_providers,
    _loan_identity_match,
)


User = get_user_model()


class DocumentAuthEnhancementTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Auth Dist')
        self.branch = Branch.objects.create(name='Auth Branch', district=district)
        self.collateral = CollateralType.objects.create(name='Auth Coll')
        self.officer = User.objects.create_user(
            username='auth_clo', password='pass', phone_number='0911888001',
            role='credit_loan_officer',
        )
        self.project_cat = LoanCategory.objects.create(
            name='Auth Project', product_family=FAMILY_PROJECT, appraisal_mode=FAMILY_PROJECT,
        )
        self.general_cat = LoanCategory.objects.create(
            name='Auth MSME', product_family=FAMILY_GENERAL, appraisal_mode='msme',
        )

    def _loan(self, category, lid, *, name='Abebe Kebede', phone='0911000111', tin='9988776655'):
        loan = LoanRequest.objects.create(
            loan_request_id=lid,
            applicant_name=name,
            phone_number=phone,
            amount_requested=Decimal('500000'),
            reason='auth test',
            category=category,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
        )
        LoanRequestBasicInfo.objects.create(loan_request=loan, tin_number=tin)
        return loan

    @override_settings(DOCUMENT_OCR_MATCH_MIN_SCORE=60)
    def test_soft_score_pass_with_name_and_tin(self):
        loan = self._loan(self.general_cat, 'LR-AUTH-1')
        text = 'Name: Abebe Kebede\nTIN: 9988776655\nSome bank statement body'
        result = _loan_identity_match(
            loan, text, ['applicant_name', 'phone_number', 'tin_number'],
            require_all_fields=False,
        )
        self.assertTrue(result['passed'])
        self.assertGreaterEqual(result['match_score'], 60)
        self.assertTrue(result['checks']['applicant_name']['matched'])
        self.assertTrue(result['checks']['tin_number']['matched'])

    @override_settings(DOCUMENT_OCR_MATCH_MIN_SCORE=60)
    def test_soft_score_fails_without_anchor(self):
        loan = self._loan(self.general_cat, 'LR-AUTH-2')
        text = 'Phone contact 0911000111 only — no name or TIN printed'
        result = _loan_identity_match(
            loan, text, ['applicant_name', 'phone_number', 'tin_number'],
            require_all_fields=False,
        )
        self.assertFalse(result['passed'])
        self.assertLess(result['match_score'], 60)

    @override_settings(DOCUMENT_OCR_MATCH_MIN_SCORE=60)
    def test_strict_requires_all_fields(self):
        loan = self._loan(self.general_cat, 'LR-AUTH-3')
        text = 'Name: Abebe Kebede\nTIN: 9988776655'
        soft = _loan_identity_match(
            loan, text, ['applicant_name', 'phone_number', 'tin_number'],
            require_all_fields=False,
        )
        strict = _loan_identity_match(
            loan, text, ['applicant_name', 'phone_number', 'tin_number'],
            require_all_fields=True,
        )
        self.assertTrue(soft['passed'])
        self.assertFalse(strict['passed'])
        self.assertFalse(strict['checks']['phone_number']['matched'])

    def test_structured_tin_cue(self):
        cues = extract_structured_id_cues('Taxpayer TIN: 1122334455 appears on form')
        self.assertIn('1122334455', cues['tins'])
        self.assertEqual(cues['labeled'].get('tin'), '1122334455')

    @override_settings(OPENAI_API_KEY='', GEMINI_API_KEY='', EXTERNAL_ID_VERIFY_URL='')
    def test_provider_badges_unconfigured(self):
        providers = get_document_intel_providers()
        self.assertEqual(providers['ocr']['data_source'], 'local')
        self.assertEqual(providers['llm']['data_source'], 'unconfigured')
        self.assertIn(providers['external_id']['data_source'], ('mock_or_cbs', 'unconfigured'))

    def test_committee_gate_applies_to_msme_with_pack(self):
        dt = LoanApplicationDocumentType.objects.create(
            name='Trade License Auth', order=20, is_required=True, for_appraisal_mode='msme',
        )
        LoanCategoryDocumentRequirement.objects.create(
            category=self.general_cat, document_type=dt, is_required=True, order=1,
        )
        loan = self._loan(self.general_cat, 'LR-AUTH-MSME')
        blockers = document_committee_blockers(loan)
        self.assertTrue(blockers)
        self.assertTrue(any('Trade License Auth' in b for b in blockers))

    def test_committee_gate_can_be_disabled(self):
        policy, _ = DocumentAuthenticationPolicy.objects.get_or_create(pk=1)
        policy.require_verified_documents_for_committee = False
        policy.save(update_fields=['require_verified_documents_for_committee'])
        dt = LoanApplicationDocumentType.objects.create(
            name='Site Pack Auth', order=91, is_required=True, for_appraisal_mode=FAMILY_PROJECT,
        )
        LoanCategoryDocumentRequirement.objects.create(
            category=self.project_cat, document_type=dt, is_required=True, order=1,
        )
        loan = self._loan(self.project_cat, 'LR-AUTH-OFF')
        self.assertEqual(document_committee_blockers(loan), [])
