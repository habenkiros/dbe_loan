"""Phase A: product-engine registry. Unbuilt families are no-ops like DECSI general."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from loans.engines import (
    ConsumerEngine, GeneralEngine, IdeaEngine, IjarahEngine, LeaseEngine,
    MurabahaEngine, ProjectEngine, WholesaleEngine, get_engine,
)
from loans.models import Branch, CollateralType, District, LoanCategory, LoanRequest
from loans.product_family import (
    FAMILY_CONSUMER,
    FAMILY_GENERAL,
    FAMILY_IDEA_EQUITY,
    FAMILY_IFB_IJARAH,
    FAMILY_IFB_MURABAHA,
    FAMILY_LEASE,
    FAMILY_PROJECT,
    FAMILY_WHOLESALE,
)


User = get_user_model()


class EngineRegistryTests(TestCase):
    def setUp(self):
        self.district = District.objects.create(name='Eng Dist')
        self.branch = Branch.objects.create(name='Eng Branch', district=self.district)
        self.collateral = CollateralType.objects.create(name='Eng Coll')
        self.officer = User.objects.create_user(
            username='eng_lo', password='pass', phone_number='0911222666', role='loan_officer',
        )

    def _loan(self, family, name='Eng Cat', lid='LR-ENG-1'):
        cat = LoanCategory.objects.create(
            name=name, appraisal_mode='msme', product_family=family,
        )
        return LoanRequest.objects.create(
            loan_request_id=lid,
            applicant_name='Eng Co',
            phone_number='0911000666',
            amount_requested=Decimal('10000'),
            reason='x',
            category=cat,
            branch=self.branch,
            collateral=self.collateral,
            assigned_loan_officer=self.officer,
        )

    def test_general_is_noop(self):
        loan = self._loan(FAMILY_GENERAL)
        engine = get_engine(loan)
        self.assertIsInstance(engine, GeneralEngine)
        self.assertEqual(engine.family, FAMILY_GENERAL)
        self.assertTrue(engine.uses_conventional_schedule)
        self.assertEqual(engine.disbursement_blockers(), [])
        self.assertIsNone(engine.file_summary())
        self.assertIsNone(engine.assist_brief())
        engine.consume_draw(None)

    def test_project_uses_project_engine(self):
        loan = self._loan(FAMILY_PROJECT, name='Eng Project', lid='LR-ENG-P')
        engine = get_engine(loan)
        self.assertIsInstance(engine, ProjectEngine)
        self.assertEqual(engine.family, FAMILY_PROJECT)
        blockers = engine.disbursement_blockers()
        self.assertTrue(any('project' in b.lower() or 'equity' in b.lower() for b in blockers))
        summary = engine.file_summary()
        self.assertIsNotNone(summary)
        self.assertTrue(summary.get('is_project'))
        self.assertFalse(engine.requires_appraisal_sheets())

    def test_lease_uses_lease_engine(self):
        loan = self._loan(FAMILY_LEASE, name='Eng Lease', lid='LR-ENG-L')
        engine = get_engine(loan)
        self.assertIsInstance(engine, LeaseEngine)
        self.assertEqual(engine.family, FAMILY_LEASE)
        self.assertTrue(engine.uses_conventional_schedule)
        blockers = engine.disbursement_blockers()
        self.assertTrue(any('asset' in b.lower() or 'lease' in b.lower() for b in blockers))
        summary = engine.file_summary()
        self.assertTrue(summary.get('is_lease'))
        self.assertFalse(summary.get('is_ijarah'))
        self.assertFalse(engine.requires_appraisal_sheets())

    def test_ijarah_uses_ijarah_engine(self):
        loan = self._loan(FAMILY_IFB_IJARAH, name='Eng Ijarah', lid='LR-ENG-I')
        engine = get_engine(loan)
        self.assertIsInstance(engine, IjarahEngine)
        self.assertFalse(engine.uses_conventional_schedule)
        self.assertTrue(engine.file_summary().get('is_ijarah'))
        self.assertFalse(engine.requires_appraisal_sheets())

    def test_murabaha_uses_murabaha_engine(self):
        loan = self._loan(FAMILY_IFB_MURABAHA, name='Eng Murabaha', lid='LR-ENG-M')
        engine = get_engine(loan)
        self.assertIsInstance(engine, MurabahaEngine)
        self.assertFalse(engine.uses_conventional_schedule)
        self.assertTrue(engine.file_summary().get('is_murabaha'))
        self.assertFalse(engine.requires_appraisal_sheets())

    def test_idea_uses_idea_engine(self):
        loan = self._loan(FAMILY_IDEA_EQUITY, name='Eng Idea', lid='LR-ENG-ID')
        engine = get_engine(loan)
        self.assertIsInstance(engine, IdeaEngine)
        self.assertFalse(engine.uses_conventional_schedule)
        self.assertTrue(engine.file_summary().get('is_idea'))
        self.assertFalse(engine.requires_appraisal_sheets())

    def test_consumer_uses_consumer_engine(self):
        loan = self._loan(FAMILY_CONSUMER, name='Eng Consumer', lid='LR-ENG-C')
        engine = get_engine(loan)
        self.assertIsInstance(engine, ConsumerEngine)
        self.assertEqual(engine.family, FAMILY_CONSUMER)
        self.assertFalse(engine.requires_appraisal_sheets())
        self.assertTrue(engine.file_summary().get('is_consumer'))
        self.assertTrue(any('consumer' in b.lower() or 'employer' in b.lower() or 'salary' in b.lower() for b in engine.committee_blockers()))

    def test_wholesale_uses_wholesale_engine(self):
        loan = self._loan(FAMILY_WHOLESALE, name='Eng PFI', lid='LR-ENG-W')
        engine = get_engine(loan)
        self.assertIsInstance(engine, WholesaleEngine)
        self.assertEqual(engine.family, FAMILY_WHOLESALE)
        self.assertFalse(engine.requires_appraisal_sheets())
        blockers = engine.disbursement_blockers()
        self.assertTrue(any('PFI' in b or 'institution' in b.lower() for b in blockers))
        summary = engine.file_summary()
        self.assertIsNotNone(summary)
        self.assertTrue(summary.get('is_wholesale'))
