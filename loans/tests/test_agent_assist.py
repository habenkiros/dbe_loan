"""Agentic Assist MVP tests."""

import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from loans.agent import AgentRequest, run_bootstrap_pipeline, user_can_use_agent
from loans.agent_permissions import user_can_create_loan_via_agent
from loans.models import (
    AgentConversation,
    AgentRun,
    Branch,
    CollateralType,
    District,
    LoanApplicationDocumentType,
    LoanCategory,
    LoanRequest,
)


User = get_user_model()


class AgentAssistTests(TestCase):
    def setUp(self):
        district = District.objects.create(name='Agent Dist')
        self.branch = Branch.objects.create(name='Agent Branch', district=district)
        self.other_branch = Branch.objects.create(name='Other Branch', district=district)
        self.category = LoanCategory.objects.create(name='MSME Agent')
        self.corp_cat = LoanCategory.objects.create(name='Corporate CapEx Agent')
        self.collateral = CollateralType.objects.create(name='Machinery Agent')
        for name, order in [
            ('National ID / Kebele ID', 10),
            ('TIN Certificate', 20),
            ('Business License', 30),
            ('Bank Statement (6 months)', 40),
            ('Collateral Title / Ownership Doc', 50),
        ]:
            LoanApplicationDocumentType.objects.get_or_create(
                name=name,
                defaults={'order': order, 'is_required': True},
            )
        self.bm = User.objects.create_user(
            username='agent_bm', password='pass', phone_number='0911555001',
            role='branch_manager', branch=self.branch, district=district,
        )
        self.lo = User.objects.create_user(
            username='agent_lo', password='pass', phone_number='0911555002',
            role='loan_officer', branch=self.branch, district=district,
        )
        self.lo_other = User.objects.create_user(
            username='agent_lo2', password='pass', phone_number='0911555003',
            role='loan_officer', branch=self.other_branch, district=district,
        )
        self.ceo = User.objects.create_user(
            username='agent_ceo', password='pass', phone_number='0911555004',
            role='ceo',
        )

    def test_permissions(self):
        self.assertTrue(user_can_use_agent(self.bm))
        self.assertTrue(user_can_use_agent(self.lo))
        self.assertFalse(user_can_use_agent(self.ceo))
        self.assertTrue(user_can_create_loan_via_agent(self.bm))
        self.assertFalse(user_can_create_loan_via_agent(self.lo))
        self.admin = User.objects.create_user(
            username='agent_admin', password='pass', phone_number='0911555005',
            role='admin',
        )
        self.assertFalse(user_can_create_loan_via_agent(self.admin))

    def test_lo_cannot_create_loan_via_agent(self):
        req = AgentRequest(
            applicant_name='LO Cannot Create Co',
            amount=Decimal('100000'),
            complete_documents=False,
            draft_appraisal=False,
        )
        out = run_bootstrap_pipeline(self.lo, req)
        self.assertFalse(out['ok'])
        self.assertIn('branch manager', (out.get('error') or '').lower())

    def test_lo_document_and_appraisal_tools(self):
        # BM creates bare loan assigned to LO
        req = AgentRequest(
            applicant_name='LO Coach Case',
            amount=Decimal('750000'),
            assign_officer_id=self.lo.pk,
            complete_documents=True,  # ignored
            draft_appraisal=True,  # ignored
            queue_approved=True,  # ignored
            category_id=self.category.pk,
            collateral_type_id=self.collateral.pk,
        )
        out = run_bootstrap_pipeline(self.bm, req)
        self.assertTrue(out['ok'], out.get('error'))
        code = out['loan_request_code']
        loan = LoanRequest.objects.get(pk=out['loan_request_id'])
        self.assertFalse(loan.queue_approved)
        self.assertFalse(loan.application_documents.exists())
        client = Client()
        client.force_login(self.lo)
        with override_settings(AGENT_LLM_PROVIDER='stub', OPENAI_API_KEY=''):
            r1 = client.post(
                reverse('agent_chat_api'),
                data=json.dumps({'message': f'Document checklist for {code}'}),
                content_type='application/json',
            )
            self.assertEqual(r1.status_code, 200, r1.content)
            b1 = r1.json()
            self.assertTrue(b1.get('ok'), b1)
            self.assertTrue(any(t.get('tool') == 'document_checklist' for t in (b1.get('tools') or [])))
            r_reg = client.post(
                reverse('agent_chat_api'),
                data=json.dumps({
                    'conversation_id': b1['conversation_id'],
                    'message': f'Register building named Head Office for {code}',
                }),
                content_type='application/json',
            )
            b_reg = r_reg.json()
            self.assertTrue(b_reg.get('ok'), b_reg)
            self.assertTrue(any(t.get('tool') == 'register_collateral' for t in (b_reg.get('tools') or [])))
            from collateral.models import Building, BuildingValuation
            bldg = Building.objects.get(loan_request=loan)
            self.assertEqual(bldg.name, 'Head Office')
            self.assertEqual(BuildingValuation.objects.filter(building=bldg).count(), 0)
            r2 = client.post(
                reverse('agent_chat_api'),
                data=json.dumps({
                    'conversation_id': b1['conversation_id'],
                    'message': f'Read appraisal for {code}',
                }),
                content_type='application/json',
            )
            b2 = r2.json()
            self.assertTrue(b2.get('ok'), b2)
            self.assertTrue(any(t.get('tool') == 'read_appraisal' for t in (b2.get('tools') or [])))
            # LO cannot create
            r3 = client.post(
                reverse('agent_chat_api'),
                data=json.dumps({'message': 'Create a loan for Not Allowed PLC for 1,000,000 ETB'}),
                content_type='application/json',
            )
            b3 = r3.json()
            self.assertIn('branch manager', (b3.get('reply') or '').lower())
            self.assertFalse(LoanRequest.objects.filter(applicant_name='Not Allowed PLC').exists())

    def test_bm_pipeline_creates_loan_docs_appraisal(self):
        req = AgentRequest(
            applicant_name='Agent Test PLC',
            phone_number='0911222333',
            amount=Decimal('1500000'),
            reason='WC agent test',
            category_id=self.corp_cat.pk,
            collateral_type_id=self.collateral.pk,
            assign_officer_id=self.lo.pk,
            corporate=True,
            complete_documents=True,
            draft_appraisal=True,
            queue_approved=True,
        )
        out = run_bootstrap_pipeline(self.bm, req)
        self.assertTrue(out['ok'], out.get('error'))
        loan = LoanRequest.objects.get(pk=out['loan_request_id'])
        self.assertEqual(loan.branch_id, self.branch.pk)
        self.assertEqual(loan.assigned_loan_officer_id, self.lo.pk)
        # Bare application only
        self.assertFalse(loan.queue_approved)
        self.assertFalse(loan.operation_manager_approval)
        self.assertFalse(loan.application_documents.exists())
        self.assertFalse(
            hasattr(loan, 'appraisal') and loan.appraisal and loan.appraisal_completed_at
        )
        self.assertIsNone(loan.appraisal_completed_at)
        self.assertIn(loan.committee_status, ('', None))
        self.assertIsNone(loan.submitted_to_committee_at)
        from collateral.models import Building, LandValuation, OtherCollateralItem
        self.assertEqual(Building.objects.filter(loan_request=loan).count(), 0)
        self.assertEqual(LandValuation.objects.filter(loan_request=loan).count(), 0)
        self.assertEqual(OtherCollateralItem.objects.filter(loan_request=loan).count(), 0)
        run = AgentRun.objects.get(pk=out['run_id'])
        self.assertEqual(run.status, AgentRun.STATUS_OK)
        self.assertEqual(len(run.steps), 1)
        self.assertEqual(run.steps[0]['tool'], 'create_loan')

    def test_bm_cannot_create_other_branch(self):
        req = AgentRequest(
            applicant_name='Bad branch',
            amount=Decimal('100000'),
            branch_id=self.other_branch.pk,
            assign_officer_id=self.lo_other.pk,
            complete_documents=False,
            draft_appraisal=False,
        )
        out = run_bootstrap_pipeline(self.bm, req)
        self.assertFalse(out['ok'])
        self.assertIn('branch', (out.get('error') or '').lower())

    def test_console_get_and_post(self):
        client = Client()
        client.force_login(self.bm)
        get = client.get(reverse('agent_assist'))
        self.assertEqual(get.status_code, 200)
        self.assertContains(get, 'DECSI Assist')
        # Floating chatbot widget on every allowed page
        self.assertContains(get, 'decsi-agent-widget')
        self.assertContains(get, 'decsi-agent-launcher')
        # Also present on ordinary home for BM
        home = client.get(reverse('home'))
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, 'decsi-agent-widget')
        # CEO: no widget, agent page blocked
        client.force_login(self.ceo)
        banned = client.get(reverse('agent_assist'))
        self.assertIn(banned.status_code, (302, 403))
        ceo_home = client.get(reverse('home'))
        if ceo_home.status_code == 200:
            self.assertNotContains(ceo_home, 'decsi-agent-widget')

    @override_settings(AGENT_LLM_PROVIDER='stub', OPENAI_API_KEY='')
    def test_chat_bootstrap_stub(self):
        client = Client()
        client.force_login(self.bm)
        res = client.post(
            reverse('agent_chat_api'),
            data='{"message": "Create a corporate loan for Chatbot PLC for 1,500,000 ETB working capital"}',
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertTrue(body.get('ok'), body)
        self.assertTrue(body.get('loan_request_code') or 'Created' in (body.get('reply') or ''))
        self.assertTrue(
            LoanRequest.objects.filter(applicant_name='Chatbot PLC').exists()
            or LoanRequest.objects.filter(applicant_name__icontains='Chatbot').exists(),
            body,
        )
        self.assertTrue(AgentConversation.objects.filter(user=self.bm).exists())
        story = body.get('story') or {}
        self.assertTrue(story.get('committed_loan_code') or body.get('loan_request_code'))

    def test_extract_amount_plain_and_labeled(self):
        from loans.agent_chat import _extract_amount, _extract_name, _correction_patch

        self.assertEqual(_extract_amount('create loan for zemeo 900000'), Decimal('900000'))
        self.assertEqual(
            _extract_amount('create a loan request for zemeo, 900000 birr amount'),
            Decimal('900000'),
        )
        self.assertEqual(_extract_amount('amount: 900000\nphone: 0906112233'), Decimal('900000'))
        self.assertEqual(_extract_amount('i said amount of 900000 birr'), Decimal('900000'))
        self.assertEqual(
            _extract_name(
                'create loan request,\napplicant name: zemeo\namount: 900000\nphone: 0906112233'
            ),
            'zemeo',
        )
        self.assertEqual(_extract_name('create a loan request for zemeo, 900000 birr'), 'zemeo')
        patch = _correction_patch(
            'i said amount of 900000 birr',
            'i said amount of 900000 birr',
        )
        self.assertEqual(patch.get('amount'), 900000.0)

    @override_settings(AGENT_LLM_PROVIDER='stub', OPENAI_API_KEY='')
    def test_chat_create_plain_amount_no_commas(self):
        """BM phrasing with unformatted ETB amounts must create a loan."""
        client = Client()
        client.force_login(self.bm)
        res = client.post(
            reverse('agent_chat_api'),
            data=json.dumps({
                'message': (
                    'create loan request,\n'
                    'applicant name: zemeo\n'
                    'amount: 900000\n'
                    'Category: MSME\n'
                    'phone: 0906112233'
                ),
            }),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertTrue(body.get('ok'), body)
        loan = LoanRequest.objects.filter(applicant_name__iexact='zemeo').order_by('-id').first()
        self.assertIsNotNone(loan, body)
        self.assertEqual(loan.amount_requested, Decimal('900000'))

    @override_settings(AGENT_LLM_PROVIDER='stub', OPENAI_API_KEY='')
    def test_story_edit_then_confirm(self):
        client = Client()
        client.force_login(self.bm)
        r1 = client.post(
            reverse('agent_chat_api'),
            data=json.dumps({
                'message': (
                    'Draft for Story Edit Co, amount 800000 ETB working capital — '
                    'hold story only, do not create yet'
                ),
            }),
            content_type='application/json',
        )
        self.assertEqual(r1.status_code, 200, r1.content)
        b1 = r1.json()
        self.assertTrue(b1.get('ok'), b1)
        cid = b1['conversation_id']
        self.assertFalse(
            LoanRequest.objects.filter(applicant_name='Story Edit Co').exists(),
            'Must not create before confirm when hold-only',
        )
        story = b1.get('story') or {}
        self.assertEqual(story.get('applicant_name'), 'Story Edit Co')
        # Correct amount
        r2 = client.post(
            reverse('agent_chat_api'),
            data=json.dumps({
                'conversation_id': cid,
                'message': 'change amount to 1200000',
            }),
            content_type='application/json',
        )
        b2 = r2.json()
        self.assertEqual(b2.get('story', {}).get('amount'), 1200000.0, b2)
        r3 = client.post(
            reverse('agent_chat_api'),
            data=json.dumps({'conversation_id': cid, 'message': 'confirm'}),
            content_type='application/json',
        )
        b3 = r3.json()
        self.assertTrue(b3.get('ok'), b3)
        self.assertTrue(LoanRequest.objects.filter(applicant_name='Story Edit Co').exists(), b3)
        loan = LoanRequest.objects.get(applicant_name='Story Edit Co')
        self.assertEqual(loan.amount_requested, Decimal('1200000'))

    @override_settings(AGENT_LLM_PROVIDER='stub', OPENAI_API_KEY='')
    def test_pipeline_report_in_chat(self):
        LoanRequest.objects.create(
            loan_request_id='AG-REP-001',
            applicant_name='Report Sample Co',
            phone_number='0911000001',
            amount_requested=Decimal('500000'),
            reason='WC',
            category=self.category,
            collateral=self.collateral,
            branch=self.branch,
            district=self.branch.district,
            status='Pending',
        )
        client = Client()
        client.force_login(self.bm)
        res = client.post(
            reverse('agent_chat_api'),
            data=json.dumps({'message': 'Pipeline report with Excel export'}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertTrue(body.get('ok'), body)
        tools = body.get('tools') or []
        self.assertTrue(any(t.get('tool') == 'pipeline_report' for t in tools), body)
        self.assertIn('excel', (body.get('reply') or '').lower() + str(tools).lower())

    @override_settings(AGENT_LLM_PROVIDER='openai', OPENAI_API_KEY='test-key')
    @patch('loans.agent_chat._openai_chat')
    def test_chat_openai_tool_loop(self, mock_chat):
        """LLM returns tool_call then final summary; server executes bootstrap."""
        def side_effect(messages, tools):
            has_tool_result = any(m.get('role') == 'tool' for m in messages)
            if not has_tool_result:
                return {
                    'choices': [{
                        'message': {
                            'role': 'assistant',
                            'content': None,
                            'tool_calls': [{
                                'id': 'call_1',
                                'type': 'function',
                                'function': {
                                    'name': 'bootstrap_loan',
                                    'arguments': (
                                        '{"applicant_name":"OpenAI Tool Co",'
                                        '"amount":900000,"corporate":false,'
                                        '"complete_documents":true,"draft_appraisal":true}'
                                    ),
                                },
                            }],
                        },
                    }],
                }
            return {
                'choices': [{
                    'message': {
                        'role': 'assistant',
                        'content': 'Loan file ready. Review appraisal next.',
                    },
                }],
            }

        mock_chat.side_effect = side_effect
        client = Client()
        client.force_login(self.bm)
        res = client.post(
            reverse('agent_chat_api'),
            data='{"message": "Please bootstrap OpenAI Tool Co"}',
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertTrue(body.get('ok'), body)
        self.assertIn('ready', (body.get('reply') or '').lower())
        self.assertTrue(LoanRequest.objects.filter(applicant_name='OpenAI Tool Co').exists())
        tools = body.get('tools') or []
        self.assertTrue(any(t.get('tool') == 'bootstrap_loan' for t in tools))
