"""Registration identity: owner/title, financed vs owned, dashboard eligibility."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from collateral.coverage import compute_coverage_adequacy
from collateral.engineering_qa import engineering_qa_approve_blockers, engineering_qa_checklist
from collateral.field_utils import get_building_readiness, get_land_readiness, get_other_item_readiness
from collateral.models import (
    Building, BuildingImage, BuildingValuation, LandValuation, LandValuationImage,
    MainWork, OtherCollateralItem, OtherCollateralItemImage, SubWork,
)
from collateral.registration import new_movable_item, resolved_owner_name
from collateral.views import _collateral_eligible_loans
from loans.collateral_kind import KIND_FINANCED, KIND_LAND
from loans.models import (
    Branch, CollateralType, District, LeaseAssetProfile, LoanCategory, LoanRequest,
    Region, Zone, City,
)
from loans.product_family import FAMILY_IDEA_EQUITY, FAMILY_LEASE, FAMILY_WHOLESALE


User = get_user_model()


class CollateralRegistrationTests(TestCase):
    def setUp(self):
        region = Region.objects.create(name='Addis R')
        zone = Zone.objects.create(name='Kirkos Z', region=region)
        self.city = City.objects.create(name='Woreda R', zone=zone)
        district = District.objects.create(name='Central R')
        self.branch = Branch.objects.create(name='Main R', district=district)
        self.building_type = CollateralType.objects.create(name='Building R')
        self.financed_type = CollateralType.objects.create(
            name='Financed plant', kind=KIND_FINANCED,
        )
        self.land_type = CollateralType.objects.create(name='Land plot R', kind=KIND_LAND)
        self.msme = LoanCategory.objects.create(name='MSME R')
        self.officer = User.objects.create_user(
            username='officer_reg', password='pass', phone_number='0911999001',
            role='loan_officer',
        )
        self.loan = LoanRequest.objects.create(
            loan_request_id='LR-REG-001',
            applicant_name='Borrower Name',
            phone_number='0911999000',
            amount_requested=Decimal('500000'),
            reason='Working capital',
            category=self.msme,
            branch=self.branch,
            collateral=self.building_type,
            queue_approved=True,
            operation_manager_approval=True,
            assigned_loan_officer=self.officer,
        )

    def test_borrower_owner_defaults_to_applicant(self):
        building = Building.objects.create(
            loan_request=self.loan, name='Shop R', city=self.city,
        )
        self.assertEqual(resolved_owner_name(building, self.loan), 'Borrower Name')
        checks = get_building_readiness(building)['checks']
        owner = next(c for c in checks if c['key'] == 'owner')
        self.assertTrue(owner['ok'])

    def test_third_party_needs_name_and_title(self):
        building = Building.objects.create(
            loan_request=self.loan, name='Guarantor house', city=self.city,
            owner_kind=Building.OWNER_THIRD_PARTY,
        )
        readiness = get_building_readiness(building)
        self.assertFalse(readiness['ready'])
        keys = {c['key']: c['ok'] for c in readiness['checks']}
        self.assertFalse(keys['owner'])
        self.assertFalse(keys['third_party_title'])
        building.owner_name = 'Auntie Owner'
        building.title_reference = 'DEED-99'
        building.save()
        keys = {c['key']: c['ok'] for c in get_building_readiness(building)['checks']}
        self.assertTrue(keys['owner'])
        self.assertTrue(keys['third_party_title'])

    def test_building_needs_front_photo(self):
        building = Building.objects.create(
            loan_request=self.loan, name='Facade test', city=self.city,
            site_gps_lat=Decimal('9.01'), site_gps_lon=Decimal('38.75'),
        )
        mw = MainWork.objects.create(name='R Structure', order=1)
        sw = SubWork.objects.create(name='R Foundation', main_work=mw, order=1)
        BuildingValuation.objects.create(
            building=building, sub_work=sw, quantity=Decimal('10'), unit_price=Decimal('1000'),
        )
        tiny = SimpleUploadedFile('p.jpg', b'fake-image-bytes', content_type='image/jpeg')
        for i in range(5):
            BuildingImage.objects.create(
                building=building, image=tiny,
                gps_lat=Decimal('9.01'), gps_lon=Decimal('38.75'),
            )
        self.assertFalse(get_building_readiness(building)['ready'])
        BuildingImage.objects.filter(building=building).first().delete()
        BuildingImage.objects.create(
            building=building, image=tiny, photo_type=BuildingImage.PHOTO_FRONT,
            gps_lat=Decimal('9.01'), gps_lon=Decimal('38.75'),
        )
        self.assertTrue(get_building_readiness(building)['ready'])

    def test_land_title_photo_or_reference(self):
        self.loan.collateral = self.land_type
        self.loan.save(update_fields=['collateral'])
        land = LandValuation.objects.create(
            loan_request=self.loan,
            land_size_sqm=Decimal('200'),
            unit_price_per_sqm=Decimal('500'),
            site_gps_lat=Decimal('9.01'),
            site_gps_lon=Decimal('38.75'),
        )
        tiny = SimpleUploadedFile('p.jpg', b'fake-image-bytes', content_type='image/jpeg')
        for i in range(3):
            LandValuationImage.objects.create(
                land_valuation=land, image=tiny, photo_type=LandValuationImage.PHOTO_PLOT,
                gps_lat=Decimal('9.01'), gps_lon=Decimal('38.75'),
            )
        self.assertFalse(get_land_readiness(land)['ready'])
        land.title_reference = 'PLOT-12'
        land.save(update_fields=['title_reference'])
        self.assertTrue(get_land_readiness(land)['ready'])

    def test_owned_movable_needs_plate_or_vin(self):
        item = OtherCollateralItem.objects.create(
            loan_request=self.loan, name='Truck', estimated_value=Decimal('200000'),
        )
        tiny = SimpleUploadedFile('p.jpg', b'fake-image-bytes', content_type='image/jpeg')
        for ptype in (
            OtherCollateralItemImage.PHOTO_PLATE,
            OtherCollateralItemImage.PHOTO_ASSET,
            OtherCollateralItemImage.PHOTO_SERIAL,
        ):
            OtherCollateralItemImage.objects.create(item=item, image=tiny, photo_type=ptype)
        self.assertFalse(get_other_item_readiness(item)['ready'])
        item.chassis_vin = 'VIN123456789'
        item.save(update_fields=['chassis_vin'])
        self.assertTrue(get_other_item_readiness(item)['ready'])

    def test_financed_item_ready_without_plate(self):
        lease_cat = LoanCategory.objects.create(
            name='Lease R', product_family=FAMILY_LEASE,
        )
        lease_loan = LoanRequest.objects.create(
            loan_request_id='LR-REG-LEASE',
            applicant_name='Lessee',
            phone_number='0911999002',
            amount_requested=Decimal('400000'),
            reason='Machine',
            category=lease_cat,
            branch=self.branch,
            collateral=self.financed_type,
            queue_approved=True,
            operation_manager_approval=True,
            assigned_loan_officer=self.officer,
        )
        LeaseAssetProfile.objects.create(
            loan_request=lease_loan,
            asset_description='CNC mill',
            make_model='Haas VF-2',
            asset_price=Decimal('380000'),
            supplier_invoice_ref='INV-44',
        )
        item = new_movable_item(lease_loan)
        self.assertEqual(item.acquisition_status, OtherCollateralItem.ACQ_TO_BUY)
        self.assertEqual(item.owner_kind, OtherCollateralItem.OWNER_BANK)
        self.assertEqual(item.name, 'CNC mill')
        self.assertEqual(item.estimated_value, Decimal('380000'))
        tiny = SimpleUploadedFile('p.jpg', b'fake-image-bytes', content_type='image/jpeg')
        for ptype in (
            OtherCollateralItemImage.PHOTO_OFFER,
            OtherCollateralItemImage.PHOTO_ASSET,
            OtherCollateralItemImage.PHOTO_OTHER,
        ):
            OtherCollateralItemImage.objects.create(item=item, image=tiny, photo_type=ptype)
        readiness = get_other_item_readiness(item)
        self.assertTrue(readiness['ready'], readiness['checks'])
        self.assertEqual(readiness['missing_photo_types'], [])

    def test_coverage_uses_committee_amount(self):
        Building.objects.create(
            loan_request=self.loan, name='Cover shop', city=self.city,
        )
        mw = MainWork.objects.create(name='Cover S', order=2)
        sw = SubWork.objects.create(name='Cover F', main_work=mw, order=1)
        building = Building.objects.filter(loan_request=self.loan, name='Cover shop').first()
        BuildingValuation.objects.create(
            building=building, sub_work=sw, quantity=Decimal('10'), unit_price=Decimal('1000'),
        )
        low = compute_coverage_adequacy(self.loan)
        self.assertFalse(low['adequate_for_submit'])
        self.loan.committee_final_amount = Decimal('8000')
        self.loan.save(update_fields=['committee_final_amount'])
        high = compute_coverage_adequacy(self.loan)
        self.assertTrue(high['uses_committee_amount'])
        self.assertTrue(high['adequate_for_submit'])
        self.assertEqual(high['coverage_amount'], Decimal('8000'))

    def test_dashboard_skips_wholesale_and_placeholder(self):
        wholesale = LoanCategory.objects.create(
            name='PFI R', product_family=FAMILY_WHOLESALE, requires_collateral=False,
        )
        idea = LoanCategory.objects.create(
            name='Idea R', product_family=FAMILY_IDEA_EQUITY, requires_collateral=False,
        )
        tbd = CollateralType.objects.create(name='To be determined')
        LoanRequest.objects.create(
            loan_request_id='LR-REG-W',
            applicant_name='PFI',
            phone_number='0911999010',
            amount_requested=Decimal('1'),
            reason='On-lending',
            category=wholesale,
            branch=self.branch,
            collateral=self.building_type,
            queue_approved=True,
            operation_manager_approval=True,
        )
        LoanRequest.objects.create(
            loan_request_id='LR-REG-I',
            applicant_name='Idea',
            phone_number='0911999011',
            amount_requested=Decimal('1'),
            reason='Equity',
            category=idea,
            branch=self.branch,
            collateral=self.building_type,
            queue_approved=True,
            operation_manager_approval=True,
        )
        LoanRequest.objects.create(
            loan_request_id='LR-REG-TBD',
            applicant_name='TBD',
            phone_number='0911999012',
            amount_requested=Decimal('1'),
            reason='Unknown',
            category=self.msme,
            branch=self.branch,
            collateral=tbd,
            queue_approved=True,
            operation_manager_approval=True,
        )
        ids = set(_collateral_eligible_loans().values_list('loan_request_id', flat=True))
        self.assertIn('LR-REG-001', ids)
        self.assertNotIn('LR-REG-W', ids)
        self.assertNotIn('LR-REG-I', ids)
        self.assertNotIn('LR-REG-TBD', ids)

    def test_engineering_approve_needs_ticks(self):
        checklist = engineering_qa_checklist(self.loan)
        self.assertFalse(checklist['all_ok'])
        blockers = engineering_qa_approve_blockers(self.loan, {})
        self.assertTrue(any('Tick' in b for b in blockers))
        ticked = {
            'qa_coverage': True,
            'qa_gps': True,
            'qa_evidence': True,
            'qa_valuation': True,
            'qa_ownership': True,
        }
        still = engineering_qa_approve_blockers(self.loan, ticked)
        self.assertTrue(still)
        self.assertFalse(any('Tick' in b for b in still))

    def test_manual_site_gps_requires_attestation(self):
        from collateral.governance import apply_site_gps_with_attestation

        building = Building.objects.create(
            loan_request=self.loan, name='Manual pin', city=self.city,
        )
        saved, err = apply_site_gps_with_attestation(building, {
            'site_gps_lat': '9.01',
            'site_gps_lon': '38.75',
            'site_gps_source': 'manual',
        })
        self.assertFalse(saved)
        self.assertIn('attestation', (err or '').lower())
        saved, err = apply_site_gps_with_attestation(building, {
            'site_gps_lat': '9.01',
            'site_gps_lon': '38.75',
            'site_gps_source': 'manual',
            'site_gps_weak_ack': '1',
            'site_gps_attestation_note': 'Phone GPS failed indoors; used survey pin on site.',
        })
        self.assertTrue(saved, err)
        building.refresh_from_db()
        self.assertEqual(building.site_gps_source, 'manual')
        self.assertTrue(building.site_gps_weak_acknowledged)
        self.assertIsNone(building.site_gps_accuracy_m)

    def test_vehicle_ready_without_site_or_photo_gps(self):
        from collateral.engineering_qa import engineering_qa_checklist

        movable = CollateralType.objects.create(name='Vehicle GPS Test')
        self.loan.collateral = movable
        self.loan.save(update_fields=['collateral'])
        item = OtherCollateralItem.objects.create(
            loan_request=self.loan,
            name='Isuzu truck',
            estimated_value=Decimal('300000'),
            plate_number='AA-55',
        )
        tiny = SimpleUploadedFile('p.jpg', b'fake-image-bytes', content_type='image/jpeg')
        for ptype in (
            OtherCollateralItemImage.PHOTO_PLATE,
            OtherCollateralItemImage.PHOTO_ASSET,
            OtherCollateralItemImage.PHOTO_SERIAL,
        ):
            OtherCollateralItemImage.objects.create(item=item, image=tiny, photo_type=ptype)
        readiness = get_other_item_readiness(item)
        self.assertTrue(readiness['ready'], readiness['checks'])
        checklist = engineering_qa_checklist(self.loan)
        gps_item = next(i for i in checklist['items'] if i['key'] == 'gps')
        self.assertTrue(gps_item['ok'], gps_item)