"""Shared KYC identity case, Fayda mock, forensics, and committee band."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from applicant_portal.models import ApplicantAccount, OnlineApplication, OnlineApplicationDocument
from applicant_portal.services import _copy_online_documents, can_proceed_to_payment
from loans.kyc_desk import (
    KycClearBlocked,
    complete_checklist_payload,
    ensure_intake_screenings,
    kyc_applies,
    kyc_committee_blockers,
    kyc_is_complete,
    set_screening_status,
)
from loans.kyc_identity import (
    ensure_identity_case,
    identity_committee_blockers,
    identity_fee_blockers,
    recompute_identity_case,
    save_applicant_identity,
)
from loans.models import (
    Branch,
    CollateralType,
    CreditDeskScreening,
    District,
    KycIdentityCase,
    KycParty,
    LoanApplicationDocumentType,
    LoanCategory,
    LoanRequest,
    LoanRequestDocument,
)
from loans.product_family import FAMILY_GENERAL, FAMILY_PROJECT
from loans.services.document_auth import document_committee_blockers
from loans.services.document_forensics import applicant_facing, quality_report
from loans.services.identity_verify import verify_party


User = get_user_model()


def _pattern_png(width=640, height=480) -> bytes:
    from PIL import Image
    img = Image.new('RGB', (width, height))
    img.putdata([
        ((i * 17) % 256, (i * 31) % 256, (i * 7) % 256)
        for i in range(width * height)
    ])
    buf = __import__('io').BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


class KycIdentityCaseTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='Id Dist')
        self.branch = Branch.objects.create(name='Id Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='Id Coll')
        self.officer = User.objects.create_user(
            username='id_clo', password='pass', phone_number='0911888001',
            role='credit_loan_officer',
        )
        self.project_cat = LoanCategory.objects.create(
            name='Id Project', product_family=FAMILY_PROJECT,
        )
        self.general_cat = LoanCategory.objects.create(
            name='Id MSME', product_family=FAMILY_GENERAL, appraisal_mode='msme',
        )
        self.dt_id = LoanApplicationDocumentType.objects.create(
            name='National ID', order=1, is_required=True,
            allowed_extensions='pdf,jpg,jpeg,png',
        )

    def _loan(self, category, rid, **kwargs):
        defaults = dict(
            loan_request_id=rid,
            applicant_name='Id Co',
            phone_number='0911000333',
            amount_requested=Decimal('500000'),
            reason='kyc',
            category=category,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
        )
        defaults.update(kwargs)
        return LoanRequest.objects.create(**defaults)

    def test_decsi_general_still_skips_desk_packs(self):
        loan = self._loan(self.general_cat, 'LR-ID-G')
        self.assertFalse(kyc_applies(loan))
        self.assertEqual(ensure_intake_screenings(loan), [])
        self.assertTrue(kyc_is_complete(loan))
        self.assertEqual(kyc_committee_blockers(loan), [])

    def test_mock_fayda_confirms_and_denies(self):
        loan = self._loan(self.project_cat, 'LR-ID-F')
        party = save_applicant_identity(
            loan_request=loan,
            identity_kind=KycParty.KIND_FAYDA,
            legal_name_en='Id Co',
            fan='123456789',
            tin='99887766',
            verify=True,
        )
        self.assertEqual(party.verify_status, KycParty.VERIFY_CONFIRMED)
        denied = save_applicant_identity(
            loan_request=loan,
            identity_kind=KycParty.KIND_FAYDA,
            legal_name_en='Id Co',
            fan='000111222',
            verify=True,
        )
        self.assertEqual(denied.verify_status, KycParty.VERIFY_NOT_FOUND)
        case = loan.kyc_identity_case
        recompute_identity_case(case)
        self.assertEqual(case.band, KycIdentityCase.BAND_BLOCKED)
        self.assertTrue(identity_committee_blockers(loan))
        self.assertTrue(any('Fayda' in m or 'TIN' in m or 'Identity' in m for m in kyc_committee_blockers(loan)))

    @override_settings(IDENTITY_VERIFY_PROVIDER='off')
    def test_provider_off_skips_without_blocking(self):
        loan = self._loan(self.project_cat, 'LR-ID-OFF')
        party = save_applicant_identity(
            loan_request=loan, fan='123456789', verify=True,
        )
        self.assertEqual(party.verify_status, KycParty.VERIFY_SKIPPED)
        self.assertEqual(identity_committee_blockers(loan), [])

    def test_scan_admin_blocked_needs_override_note(self):
        loan = self._loan(
            self.project_cat, 'LR-ID-SCAN',
            source_channel=LoanRequest.SOURCE_ONLINE,
        )
        ensure_intake_screenings(loan)
        case = ensure_identity_case(loan_request=loan)
        case.band = KycIdentityCase.BAND_BLOCKED
        case.blockers = ['Identity mismatch on National ID.']
        case.save()
        with self.assertRaises(KycClearBlocked):
            set_screening_status(
                loan, CreditDeskScreening.DESK_SCAN,
                CreditDeskScreening.STATUS_CLEARED, self.officer, 'short',
                checklist=complete_checklist_payload(CreditDeskScreening.DESK_SCAN, loan),
            )
        row = set_screening_status(
            loan, CreditDeskScreening.DESK_SCAN,
            CreditDeskScreening.STATUS_CLEARED, self.officer,
            'Applicant confirmed in person at the branch desk.',
            checklist=complete_checklist_payload(CreditDeskScreening.DESK_SCAN, loan),
        )
        self.assertEqual(row.status, CreditDeskScreening.STATUS_CLEARED)
        case.refresh_from_db()
        self.assertTrue((case.findings or {}).get('scan_override'))

    def test_copy_online_documents_does_not_reocr_when_checks_present(self):
        acct = ApplicantAccount.objects.create(
            full_name='Portal Person',
            phone_number='0911000444',
            customer_number='1003003',
            password_hash='x',
        )
        app = OnlineApplication.objects.create(
            applicant=acct,
            applicant_name='Portal Person',
            phone_number='0911000444',
            category=self.project_cat,
            branch=self.branch,
            collateral=self.collateral,
            amount_requested=Decimal('200000'),
            reason='docs',
        )
        raw = _pattern_png()
        online = OnlineApplicationDocument(
            application=app,
            document_type=self.dt_id,
            original_filename='id.png',
            file_size=len(raw),
            file_sha256='a' * 64,
            auth_status='auto_passed',
            automated_checks={
                'passed': True,
                'sha256': 'a' * 64,
                'auth_status': 'auto_passed',
                'forensics': {'authenticity_score': 88, 'quality': {'score': 90}},
            },
            quality_score=90,
            authenticity_score=88,
        )
        online.file.save('id.png', ContentFile(raw), save=False)
        online.save()
        loan = self._loan(self.project_cat, 'LR-ID-COPY')
        app.loan_request = loan
        app.save(update_fields=['loan_request'])
        with patch('loans.services.document_auth.run_automated_document_checks') as mocked:
            _copy_online_documents(app, loan)
            mocked.assert_not_called()
        copied = loan.application_documents.get(document_type=self.dt_id)
        self.assertEqual(copied.file_sha256, 'a' * 64)
        self.assertEqual(copied.auth_status, 'auto_passed')
        self.assertEqual(copied.authenticity_score, 88)

    def test_tiny_id_scan_blocks_fee_and_unreadable_message(self):
        acct = ApplicantAccount.objects.create(
            full_name='Tiny Scan',
            phone_number='0911000555',
            customer_number='1003004',
            password_hash='x',
        )
        app = OnlineApplication.objects.create(
            applicant=acct,
            applicant_name='Tiny Scan',
            phone_number='0911000555',
            category=self.general_cat,
            branch=self.branch,
            collateral=self.collateral,
            amount_requested=Decimal('20000'),
            reason='kiosk',
        )
        from PIL import Image
        import io
        img = Image.new('RGB', (24, 24), (0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        tiny = buf.getvalue()
        q = quality_report(tiny, 'png', '')
        self.assertLess(q['score'], 40)
        facing = applicant_facing({
            'auth_status': 'needs_review',
            'forensics': {'quality': q, 'reasons': q['reasons'], 'authenticity_score': 20},
        })
        self.assertTrue(facing['retake'])
        online = OnlineApplicationDocument(
            application=app,
            document_type=self.dt_id,
            original_filename='tiny.png',
            file_size=len(tiny),
            auth_status='needs_review',
            automated_checks={
                'auth_status': 'needs_review',
                'forensics': {'quality': q, 'reasons': q['reasons'], 'authenticity_score': 20},
            },
        )
        online.file.save('tiny.png', ContentFile(tiny), save=False)
        online.save()
        blockers = identity_fee_blockers(app)
        self.assertTrue(blockers)
        ok, reason = can_proceed_to_payment(app)
        self.assertFalse(ok)
        self.assertIn('Retake', reason)

    def test_loan_detail_shows_identity_case_panel(self):
        loan = self._loan(self.project_cat, 'LR-ID-UI')
        save_applicant_identity(
            loan_request=loan, legal_name_en='Id Co', fan='123456789', verify=True,
        )
        from django.test import Client
        from django.urls import reverse
        client = Client()
        client.force_login(self.officer)
        resp = client.get(reverse('loan_request_detail', args=[loan.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Identity case')
        self.assertContains(resp, 'FAN')
        self.assertContains(resp, 'Face match')
        self.assertContains(resp, 'Add director')

    def test_mock_biometric_matches_id_portrait(self):
        loan = self._loan(self.project_cat, 'LR-ID-BIO')
        raw = _pattern_png()
        doc = LoanRequestDocument(
            loan_request=loan,
            document_type=self.dt_id,
            original_filename='id.png',
            file_size=len(raw),
        )
        doc.file.save('id.png', ContentFile(raw), save=False)
        doc.save()
        from django.core.files.uploadedfile import SimpleUploadedFile
        from loans.kyc_identity import save_applicant_selfie
        party = save_applicant_selfie(
            loan_request=loan,
            uploaded_file=SimpleUploadedFile('selfie.png', raw, content_type='image/png'),
        )
        self.assertEqual(party.biometric_status, KycParty.BIOMETRIC_MATCHED)
        self.assertTrue(party.liveness_ref)
        self.assertGreaterEqual(float(party.face_match_score), 70)
        loan.kyc_identity_case.refresh_from_db()
        self.assertNotEqual(loan.kyc_identity_case.band, KycIdentityCase.BAND_BLOCKED)

    @override_settings(BIOMETRIC_PROVIDER='mock')
    def test_mock_biometric_fail_token_blocks_case(self):
        loan = self._loan(self.project_cat, 'LR-ID-BIOF')
        raw = _pattern_png()
        from django.core.files.uploadedfile import SimpleUploadedFile
        from loans.kyc_identity import save_applicant_selfie
        party = save_applicant_selfie(
            loan_request=loan,
            uploaded_file=SimpleUploadedFile('fail-selfie.png', raw, content_type='image/png'),
        )
        self.assertEqual(party.biometric_status, KycParty.BIOMETRIC_FAILED)
        case = loan.kyc_identity_case
        case.refresh_from_db()
        self.assertEqual(case.band, KycIdentityCase.BAND_BLOCKED)
        self.assertTrue(identity_committee_blockers(loan))

    def test_ubo_party_drives_legal_hints_and_review_band(self):
        from loans.kyc_desk import checklist_spec
        from loans.dbe_desks import DESK_CRM, DESK_LEGAL
        from loans.kyc_identity import save_related_party, suggested_kyc_hints
        from loans.product_family import FAMILY_CONSUMER

        consumer_keys = [k for k, _, _ in checklist_spec(DESK_CRM, FAMILY_CONSUMER)]
        self.assertNotIn('ubo', consumer_keys)
        project_crm = [k for k, _, _ in checklist_spec(DESK_CRM, FAMILY_PROJECT)]
        self.assertIn('ubo', project_crm)
        project_legal = [k for k, _, _ in checklist_spec(DESK_LEGAL, FAMILY_PROJECT)]
        self.assertIn('ubo_recorded', project_legal)

        loan = self._loan(self.project_cat, 'LR-ID-UBO')
        save_applicant_identity(
            loan_request=loan, legal_name_en='Id Co', fan='123456789', verify=True,
        )
        case = loan.kyc_identity_case
        case.refresh_from_db()
        self.assertEqual(case.band, KycIdentityCase.BAND_REVIEW)
        self.assertIn('ubo_incomplete', (case.findings or {}).get('reasons') or [])
        hints = suggested_kyc_hints(loan)
        self.assertIn('no director or UBO', hints.get('ubo', ''))
        save_related_party(
            loan_request=loan,
            role=KycParty.ROLE_UBO,
            legal_name_en='Owner One',
            id_number='ID-UBO-1',
            share_percent='40',
            capacity='Shareholder',
            verify=False,
        )
        save_related_party(
            loan_request=loan,
            role=KycParty.ROLE_DIRECTOR,
            legal_name_en='Chair Person',
            capacity='Chair',
            verify=False,
        )
        case.refresh_from_db()
        self.assertTrue((case.findings or {}).get('ubo', {}).get('complete'))
        hints = suggested_kyc_hints(loan)
        self.assertIn('UBO', hints.get('ubo_recorded', ''))
        self.assertIn('director', hints.get('title_or_authority', '').lower())

    @override_settings(SANCTIONS_PROVIDER='mock')
    def test_pep_screen_covers_related_parties(self):
        from loans.compliance.sanctions_screen import screen_loan_request
        from loans.kyc_identity import save_related_party

        loan = self._loan(self.project_cat, 'LR-ID-PEP')
        save_applicant_identity(
            loan_request=loan, legal_name_en='Clean Applicant', fan='123456789', verify=True,
        )
        save_related_party(
            loan_request=loan,
            role=KycParty.ROLE_DIRECTOR,
            legal_name_en='PEP Demo Official',
            verify=False,
        )
        result = screen_loan_request(loan)
        self.assertTrue(result.get('hit'))
        self.assertGreaterEqual(int(result.get('subjects_screened') or 0), 2)


class KycIdentityVerifyHttpTests(TestCase):
    def test_verify_party_http_error_is_not_a_hard_block(self):
        from loans.models import KycIdentityCase as Case
        district = District.objects.create(name='Http Dist')
        branch = Branch.objects.create(name='Http Branch', district=district)
        coll = CollateralType.objects.create(name='Http Coll')
        cat = LoanCategory.objects.create(name='Http Cat', product_family=FAMILY_GENERAL)
        loan = LoanRequest.objects.create(
            loan_request_id='LR-ID-HTTP',
            applicant_name='Http Person',
            phone_number='0911000666',
            amount_requested=Decimal('1'),
            reason='x',
            category=cat,
            branch=branch,
            collateral=coll,
        )
        case = Case.objects.create(loan_request=loan)
        party = KycParty.objects.create(
            identity_case=case, role=KycParty.ROLE_APPLICANT,
            legal_name_en='Http Person', fan='555',
        )
        with override_settings(
            IDENTITY_VERIFY_PROVIDER='http',
            FAYDA_VERIFY_URL='http://127.0.0.1:9/fayda',
            IDENTITY_VERIFY_FORCE_MOCK=False,
            IDENTITY_VERIFY_TIMEOUT=1,
        ):
            payload = verify_party(party)
        self.assertEqual(payload.get('status'), 'provider_error')
        party.refresh_from_db()
        self.assertEqual(party.verify_status, KycParty.VERIFY_ERROR)
        recompute_identity_case(case)
        case.refresh_from_db()
        self.assertEqual(case.band, KycIdentityCase.BAND_REVIEW)
        self.assertEqual(document_committee_blockers(loan), [])
