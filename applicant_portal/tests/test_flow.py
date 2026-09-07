"""End-to-end digital apply + auth/security coverage."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from applicant_portal.models import (
    ApplicantAccount,
    ApplicantAuthEvent,
    ApplicantPortalSettings,
    OnlineApplication,
    OnlineApplicationDocument,
)
from applicant_portal.security import normalize_phone, validate_applicant_password, validate_phone_format
from loans.models import (
    Branch,
    CollateralType,
    District,
    LoanApplicationDocumentType,
    LoanCategory,
    LoanCategoryDocumentRequirement,
    LoanRequest,
)


User = get_user_model()


class ApplicantPortalFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        ApplicantPortalSettings.objects.update_or_create(
            pk=1,
            defaults={
                'enabled': True,
                'processing_fee_etb': Decimal('25.00'),
                'min_password_length': 10,
                'require_uppercase': True,
                'require_lowercase': True,
                'require_digit': True,
                'require_special': True,
                'max_failed_logins': 5,
                'lockout_minutes': 15,
                'register_rate_limit_per_hour': 20,
                'session_idle_minutes': 30,
            },
        )
        self.district = District.objects.create(name='AP District')
        self.district_other = District.objects.create(name='Other District')
        self.branch = Branch.objects.create(name='AP Branch', district=self.district)
        self.branch_other = Branch.objects.create(name='Other Branch', district=self.district_other)
        self.category = LoanCategory.objects.create(
            name='AP MSME Product', appraisal_mode=LoanCategory.MODE_MSME,
        )
        self.collateral = CollateralType.objects.create(name='AP Collateral')
        self.dt_id = LoanApplicationDocumentType.objects.create(
            name='AP National ID', order=1, is_required=True,
            allowed_extensions='pdf,jpg,jpeg,png',
        )
        self.dt_opt = LoanApplicationDocumentType.objects.create(
            name='AP Optional Letter', order=2, is_required=False,
            allowed_extensions='pdf,jpg,jpeg,png',
        )
        LoanCategoryDocumentRequirement.objects.create(
            category=self.category, document_type=self.dt_id, is_required=True, order=1,
        )
        LoanCategoryDocumentRequirement.objects.create(
            category=self.category, document_type=self.dt_opt, is_required=False, order=2,
        )
        self.png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00'
            b'\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        try:
            from PIL import Image
            import io
            img = Image.new('RGB', (640, 480))
            img.putdata([
                ((i * 17) % 256, (i * 31) % 256, (i * 7) % 256)
                for i in range(640 * 480)
            ])
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            self.png_bytes = buf.getvalue()
        except Exception:
            pass
        self.strong_password = 'SecurePass1!'

    def _register(self, phone='0911222333', customer_number='1001001'):
        resp = self.client.post(reverse('applicant_portal:register'), {
            'full_name': 'Amanuel Applicant',
            'phone_number': phone,
            'customer_number': customer_number,
            'password': self.strong_password,
            'password_confirm': self.strong_password,
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 302, getattr(resp, 'content', b'')[:500])
        expected = normalize_phone(phone)
        self.assertTrue(ApplicantAccount.objects.filter(phone_number=expected).exists())

    def test_root_is_applicant_landing(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Digital Apply')

    def test_staff_hub_login_path(self):
        resp = self.client.get('/hub/login/')
        self.assertEqual(resp.status_code, 200)

    def test_hub_settings_page_for_superuser(self):
        admin = User.objects.create_superuser(
            username='apadmin', password='AdminPass1!', phone_number='0911000999',
        )
        self.client.login(username='apadmin', password='AdminPass1!')
        resp = self.client.get('/hub/manage_applicant_portal/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Digital apply settings')
        self.assertContains(resp, 'Chapa')
        intake = self.client.get('/hub/online_loan_intake/')
        self.assertEqual(intake.status_code, 200)
        post = self.client.post('/hub/manage_applicant_portal/', {
            'enabled': 'on',
            'processing_fee_etb': '75.00',
            'min_password_length': '10',
            'require_uppercase': 'on',
            'require_lowercase': 'on',
            'require_digit': 'on',
            'require_special': 'on',
            'max_failed_logins': '5',
            'lockout_minutes': '15',
            'register_rate_limit_per_hour': '8',
            'session_idle_minutes': '30',
            'require_terms_acceptance': 'on',
        })
        self.assertEqual(post.status_code, 302)
        policy = ApplicantPortalSettings.objects.get(pk=1)
        self.assertEqual(policy.processing_fee_etb, Decimal('75.00'))

    def test_phone_normalize_safaricom_and_intl(self):
        cases = [
            ('0911222333', '0911222333'),
            ('911222333', '0911222333'),
            ('+251911222333', '0911222333'),
            ('251911222333', '0911222333'),
            ('0711222333', '0711222333'),
            ('711222333', '0711222333'),
            ('+251711222333', '0711222333'),
            ('251711222333', '0711222333'),
        ]
        for raw, expected in cases:
            normalized = normalize_phone(raw)
            self.assertEqual(normalized, expected, msg=raw)
            validate_phone_format(normalized)

    @override_settings(CHAPA_SECRET_KEY='', CHAPA_PUBLIC_KEY='', CHAPA_FORCE_MOCK=True)
    def test_full_submit_creates_loan_and_queue_id(self):
        self._register()
        start = self.client.post(reverse('applicant_portal:apply_start'))
        self.assertEqual(start.status_code, 302)
        app = OnlineApplication.objects.get()
        self.assertEqual(app.processing_fee_amount, Decimal('25.00'))
        self.assertEqual(app.customer_number, '1001001')

        details = self.client.post(
            reverse('applicant_portal:apply_details', args=[app.public_id]),
            {
                'applicant_name': 'Amanuel Applicant',
                'phone_number': '0911222333',
                'customer_number': '1001001',
                'customer_history': 'new',
                'category': self.category.id,
                'collateral': self.collateral.id,
                'district': self.district.id,
                'branch': self.branch.id,
                'amount_requested': '15000.00',
                'reason': 'Working capital for kiosk',
            },
        )
        self.assertEqual(details.status_code, 302, details.content[:400] if details.status_code != 302 else b'')
        app.refresh_from_db()
        self.assertEqual(app.status, OnlineApplication.STATUS_DOCUMENTS)
        self.assertEqual(app.branch_id, self.branch.id)

        # Reject branch from wrong district
        bad = self.client.post(
            reverse('applicant_portal:apply_details', args=[app.public_id]),
            {
                'applicant_name': 'Amanuel Applicant',
                'phone_number': '0911222333',
                'customer_number': '1001001',
                'customer_history': 'new',
                'category': self.category.id,
                'collateral': self.collateral.id,
                'district': self.district.id,
                'branch': self.branch_other.id,
                'amount_requested': '15000.00',
                'reason': 'Working capital for kiosk',
            },
        )
        self.assertEqual(bad.status_code, 200)
        # Wrong-district branch is not in the dropdown queryset → invalid choice
        self.assertTrue(
            b'valid choice' in bad.content.lower()
            or b'belongs to the chosen district' in bad.content.lower()
        )
        app.refresh_from_db()
        self.assertEqual(app.branch_id, self.branch.id)

        upload = self.client.post(
            reverse('applicant_portal:apply_documents', args=[app.public_id]),
            {
                'action': 'upload',
                f'doc_type_{self.dt_id.id}': SimpleUploadedFile(
                    'id.png', self.png_bytes, content_type='image/png',
                ),
            },
        )
        self.assertEqual(upload.status_code, 302)
        self.assertTrue(
            OnlineApplicationDocument.objects.filter(
                application=app, document_type=self.dt_id,
            ).exists()
        )

        cont = self.client.post(
            reverse('applicant_portal:apply_documents', args=[app.public_id]),
            {'action': 'continue'},
        )
        self.assertEqual(cont.status_code, 302)

        pay = self.client.post(
            reverse('applicant_portal:apply_payment', args=[app.public_id]),
            {'action': 'pay'},
        )
        # Mock Chapa redirects to return_url then verify
        self.assertEqual(pay.status_code, 302)
        # follow mock checkout (return_url)
        ret = self.client.get(pay.url)
        self.assertEqual(ret.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.payment_status, OnlineApplication.PAY_PAID)
        self.assertTrue(app.chapa_tx_ref)

        submit = self.client.post(
            reverse('applicant_portal:apply_submit', args=[app.public_id]),
        )
        self.assertEqual(submit.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, OnlineApplication.STATUS_SUBMITTED)
        loan = LoanRequest.objects.get(pk=app.loan_request_id)
        self.assertEqual(loan.branch_id, self.branch.id)
        self.assertEqual(loan.district_id, self.district.id)

    def test_login_required_for_home(self):
        resp = self.client.get(reverse('applicant_portal:home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp.url)

    def test_weak_password_rejected(self):
        resp = self.client.post(reverse('applicant_portal:register'), {
            'full_name': 'Weak User',
            'phone_number': '0911000001',
            'customer_number': 'CUST-weak',
            'password': 'secret12',
            'password_confirm': 'secret12',
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ApplicantAccount.objects.filter(phone_number='0911000001').exists())

    def test_password_policy_helper(self):
        with self.assertRaises(ValidationError):
            validate_applicant_password('short', phone='0911222333')
        validate_applicant_password('SecurePass1!', phone='0911222333', full_name='Sara')

    def test_login_lockout(self):
        self._register(phone='0911888777', customer_number='1001888')
        self.client = Client()
        ApplicantPortalSettings.objects.filter(pk=1).update(max_failed_logins=3, lockout_minutes=30)
        for _ in range(3):
            self.client.post(reverse('applicant_portal:login'), {
                'login_id': '0911888777',
                'password': 'WrongPass1!',
            })
        account = ApplicantAccount.objects.get(phone_number='0911888777')
        self.assertTrue(account.is_login_locked())
        self.assertTrue(
            ApplicantAuthEvent.objects.filter(event_type=ApplicantAuthEvent.EVT_LOGIN_LOCKED).exists()
        )

    def test_register_requires_customer_number(self):
        resp = self.client.post(reverse('applicant_portal:register'), {
            'full_name': 'No Cust',
            'phone_number': '0911000111',
            'customer_number': '',
            'password': self.strong_password,
            'password_confirm': self.strong_password,
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ApplicantAccount.objects.filter(phone_number='0911000111').exists())

    def test_reject_letters_in_numeric_fields(self):
        # Phone with letters
        r1 = self.client.post(reverse('applicant_portal:register'), {
            'full_name': 'Bad Phone',
            'phone_number': '0911abc333',
            'customer_number': '12345',
            'password': self.strong_password,
            'password_confirm': self.strong_password,
            'accept_terms': 'on',
        })
        self.assertEqual(r1.status_code, 200)
        self.assertContains(r1, 'letters', status_code=200)
        # Customer number with letters
        r2 = self.client.post(reverse('applicant_portal:register'), {
            'full_name': 'Bad Cust',
            'phone_number': '0911222444',
            'customer_number': 'CUST-ABC',
            'password': self.strong_password,
            'password_confirm': self.strong_password,
            'accept_terms': 'on',
        })
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(ApplicantAccount.objects.filter(phone_number='0911222444').exists())

    def test_applicant_views_loan_status_timeline(self):
        self._register()
        from applicant_portal.status import build_applicant_status
        app = OnlineApplication.objects.create(
            applicant=ApplicantAccount.objects.get(phone_number='0911222333'),
            applicant_name='Amanuel Applicant',
            phone_number='0911222333',
            customer_number='1001001',
            category=self.category,
            branch=self.branch,
            amount_requested=Decimal('10000'),
            reason='test',
            status=OnlineApplication.STATUS_SUBMITTED,
            queue_id='HK-STATUS01',
            processing_fee_amount=Decimal('25'),
            payment_status=OnlineApplication.PAY_PAID,
        )
        loan = LoanRequest.objects.create(
            loan_request_id='HK-STATUS01',
            applicant_name='Amanuel Applicant',
            phone_number='0911222333',
            category=self.category,
            collateral=self.collateral,
            amount_requested=Decimal('10000'),
            reason='test',
            branch=self.branch,
            district=self.district,
            status='Pending',
            queue_approved=False,
            source_channel=LoanRequest.SOURCE_ONLINE,
        )
        app.loan_request = loan
        app.save(update_fields=['loan_request', 'updated_at'])
        status = build_applicant_status(app)
        self.assertTrue(status.is_submitted)
        self.assertEqual(status.queue_id, 'HK-STATUS01')
        self.assertTrue(any(s.state == 'current' for s in status.stages))
        resp = self.client.get(reverse('applicant_portal:apply_status', args=[app.public_id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'HK-STATUS01')
        self.assertContains(resp, 'Progress')
        self.assertContains(resp, 'Branch intake')
        self.assertContains(resp, 'Loan requested')
        self.assertContains(resp, '10,000.00 ETB')

    def test_applicant_sees_loan_approved_and_schedule(self):
        self._register()
        from applicant_portal.status import build_applicant_status
        from loans.models import AppraisalAmortizationEntry, LoanAppraisal
        import datetime as dt

        account = ApplicantAccount.objects.get(phone_number='0911222333')
        app = OnlineApplication.objects.create(
            applicant=account,
            applicant_name='Amanuel Applicant',
            phone_number='0911222333',
            customer_number='1001001',
            category=self.category,
            branch=self.branch,
            amount_requested=Decimal('10000'),
            reason='test',
            status=OnlineApplication.STATUS_SUBMITTED,
            queue_id='HK-APPR01',
            processing_fee_amount=Decimal('25'),
            payment_status=OnlineApplication.PAY_PAID,
        )
        loan = LoanRequest.objects.create(
            loan_request_id='HK-APPR01',
            applicant_name='Amanuel Applicant',
            phone_number='0911222333',
            category=self.category,
            collateral=self.collateral,
            amount_requested=Decimal('10000'),
            reason='test',
            branch=self.branch,
            district=self.district,
            status='Approved',
            queue_approved=True,
            source_channel=LoanRequest.SOURCE_ONLINE,
            committee_status=LoanRequest.COMMITTEE_APPROVED,
            committee_final_amount=Decimal('9000'),
            operation_manager_approval=True,
        )
        app.loan_request = loan
        app.save(update_fields=['loan_request', 'updated_at'])

        status = build_applicant_status(app)
        self.assertTrue(status.is_loan_requested)
        self.assertTrue(status.is_loan_approved)
        self.assertEqual(status.pipeline_label, 'Loan approved')
        self.assertIn('9,000', status.amount_approved)

        resp = self.client.get(reverse('applicant_portal:apply_status', args=[app.public_id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Loan approved')
        self.assertContains(resp, '9,000.00 ETB')
        self.assertContains(resp, 'Repayment schedule')

        # Empty schedule until staff generates rows
        s1 = self.client.get(reverse('applicant_portal:apply_schedule', args=[app.public_id]))
        self.assertEqual(s1.status_code, 200)
        self.assertContains(s1, 'not ready')

        appraisal = LoanAppraisal.objects.create(loan_request=loan, amount_approved=Decimal('9000'))
        AppraisalAmortizationEntry.objects.create(
            appraisal=appraisal,
            period_number=1,
            payment_date=dt.date(2026, 9, 1),
            payment_amount=Decimal('800'),
            principal=Decimal('700'),
            interest=Decimal('100'),
            balance_after=Decimal('8300'),
        )
        AppraisalAmortizationEntry.objects.create(
            appraisal=appraisal,
            period_number=2,
            payment_date=dt.date(2026, 10, 1),
            payment_amount=Decimal('800'),
            principal=Decimal('710'),
            interest=Decimal('90'),
            balance_after=Decimal('7590'),
        )
        s2 = self.client.get(reverse('applicant_portal:apply_schedule', args=[app.public_id]))
        self.assertEqual(s2.status_code, 200)
        self.assertContains(s2, 'Installments')
        self.assertContains(s2, '800.00 ETB')
        self.assertContains(s2, '01 Sep 2026')

    def test_portal_disabled(self):
        ApplicantPortalSettings.objects.filter(pk=1).update(enabled=False)
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 503)

    def test_ajax_branches_filtered_by_district(self):
        self._register(phone='0711222333', customer_number='1001999')
        resp = self.client.get(
            reverse('applicant_portal:ajax_branches'),
            {'district_id': self.district.id},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        ids = {b['id'] for b in data['branches']}
        self.assertIn(self.branch.id, ids)
        self.assertNotIn(self.branch_other.id, ids)

    def test_login_with_customer_number(self):
        self._register(phone='0911555666', customer_number='8887776')
        self.client = Client()
        resp = self.client.post(reverse('applicant_portal:login'), {
            'login_id': '8887776',
            'password': self.strong_password,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self.client.session.get('applicant_portal_account_id'))

    def test_password_reset_flow(self):
        self._register(phone='0911333444', customer_number='1001334')
        self.client = Client()
        from applicant_portal.password_reset import issue_password_reset
        account = ApplicantAccount.objects.get(phone_number='0911333444')
        code = issue_password_reset(account)
        resp = self.client.post(reverse('applicant_portal:password_reset_confirm'), {
            'login_id': '0911333444',
            'code': code,
            'new_password': 'NewerPass2!',
            'new_password_confirm': 'NewerPass2!',
        })
        self.assertEqual(resp.status_code, 302)
        account.refresh_from_db()
        self.assertTrue(account.check_password('NewerPass2!'))

    def test_withdraw_draft(self):
        self._register(phone='0911444555', customer_number='1001445')
        self.client.post(reverse('applicant_portal:apply_start'))
        app = OnlineApplication.objects.get()
        resp = self.client.post(
            reverse('applicant_portal:apply_withdraw', args=[app.public_id]),
            {'reason': 'Changed mind'},
        )
        self.assertEqual(resp.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, OnlineApplication.STATUS_CANCELLED)

    def test_chapa_payload_meets_gateway_rules(self):
        from applicant_portal.chapa import build_initialize_payload

        self._register(phone='0911555666', customer_number='1001556')
        account = ApplicantAccount.objects.get(phone_number='0911555666')
        account.email = 'not-an-email'
        account.save(update_fields=['email'])
        app = OnlineApplication.objects.create(
            applicant=account,
            applicant_name='Sara Applicant',
            phone_number='0911555666',
            customer_number='1001556',
            category=self.category,
            branch=self.branch,
            amount_requested=Decimal('10000'),
            reason='test',
            email='',
            processing_fee_amount=Decimal('25'),
        )
        payload = build_initialize_payload(
            app,
            tx_ref='DA-ABC123-DEF45678',
            return_url='http://localhost/return',
            callback_url='http://localhost/webhook',
        )
        self.assertTrue(payload['email'].endswith('@decsi.com'))
        self.assertLessEqual(len(payload['customization']['title']), 16)
        desc = payload['customization']['description']
        self.assertRegex(desc, r'^[A-Za-z0-9 _.\-]+$')
        self.assertNotIn('·', desc)
        self.assertTrue(payload['meta'].get('hide_receipt'))
        self.assertIn('localhost', payload['return_url'])

    def test_checkout_base_url_uses_browser_host_not_site_url_ip(self):
        from django.test import RequestFactory, override_settings
        from applicant_portal.chapa import checkout_base_url

        factory = RequestFactory()
        req = factory.get('/pay/')
        req.META['HTTP_HOST'] = 'localhost:8000'
        with override_settings(SITE_URL='https://10.234.118.168:8443'):
            self.assertEqual(checkout_base_url(req), 'http://localhost:8000')
            self.assertEqual(checkout_base_url(None), 'https://10.234.118.168:8443')
