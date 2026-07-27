"""
Populate demo master data, users, loans, appraisals, and collateral samples.

Usage:
  python manage.py seed_sample_data
  python manage.py seed_sample_data --flush-loans   # delete sample loans first
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from collateral.models import (
    Building,
    BuildingValuation,
    LandValuation,
    MainWork,
    OtherCollateralItem,
    SubSubWork,
    SubWork,
    SubWorkUnitPrice,
)
from loans.models import (
    ApprovalCommitteeLevel,
    ApprovalCommitteeMemberRule,
    AppraisalPurposeLine,
    Branch,
    City,
    CollateralEstimationConfig,
    CollateralType,
    CommitteeApprovalPolicy,
    CustomUser,
    District,
    DocumentAuthenticationPolicy,
    LatestLoanRequestID,
    LoanAnalysisPolicyConfig,
    LoanApplicationDocumentType,
    LoanAppraisal,
    LoanCategory,
    LoanNotification,
    LoanRequest,
    LoanRequestBasicInfo,
    Region,
    Zone,
)


DEFAULT_PASSWORD = 'Demo@12345'


class Command(BaseCommand):
    help = 'Seed sample geography, users, categories, loans, appraisals, and collateral data.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--flush-loans',
            action='store_true',
            help='Delete existing LoanRequest rows before seeding loans (keeps users/master data).',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('Seeding sample data…'))

        geo = self._seed_geography()
        categories = self._seed_categories()
        collateral_types = self._seed_collateral_types()
        self._seed_document_types()
        self._seed_configs()
        catalog = self._seed_collateral_catalog(geo['cities'])
        users = self._seed_users(geo)
        self._seed_committee(users)

        if options['flush_loans']:
            deleted, _ = LoanRequest.objects.all().delete()
            self.stdout.write(f'  Flushed {deleted} loan-related rows')

        loans = self._seed_loans(geo, categories, collateral_types, users, catalog)
        self._seed_notifications(users, loans)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Sample data ready.'))
        self.stdout.write(f'  Login password for demo users: {DEFAULT_PASSWORD}')
        self.stdout.write('  Examples: bm.mekele / lo.mekele1 / eng.head / op.manager / ceo')
        self.stdout.write(f'  Loans created/updated: {len(loans)}')

    # ------------------------------------------------------------------ geography
    def _seed_geography(self):
        region, _ = Region.objects.get_or_create(name='Tigray')
        zone_me, _ = Zone.objects.get_or_create(region=region, name='Mekelle Zone')
        zone_ad, _ = Zone.objects.get_or_create(region=region, name='Adigrat Zone')
        city_me, _ = City.objects.get_or_create(zone=zone_me, name='Mekelle')
        city_ad, _ = City.objects.get_or_create(zone=zone_ad, name='Adigrat')
        city_ax, _ = City.objects.get_or_create(zone=zone_me, name='Axum')

        d_mekele, _ = District.objects.get_or_create(name='Mekelle District')
        d_eastern, _ = District.objects.get_or_create(name='Eastern District')
        d_central, _ = District.objects.get_or_create(name='Central District')

        branches = {}
        for district, name in [
            (d_mekele, 'Mekelle Main Branch'),
            (d_mekele, 'Mekelle Industrial Branch'),
            (d_eastern, 'Adigrat Branch'),
            (d_eastern, 'Wukro Branch'),
            (d_central, 'Axum Branch'),
            (d_central, 'Shire Branch'),
        ]:
            b, _ = Branch.objects.get_or_create(name=name, defaults={'district': district})
            if b.district_id != district.id:
                b.district = district
                b.save(update_fields=['district'])
            branches[name] = b

        self.stdout.write(self.style.SUCCESS(
            f'  Geography: {Region.objects.count()} regions, {Branch.objects.count()} branches'
        ))
        return {
            'region': region,
            'cities': {'Mekelle': city_me, 'Adigrat': city_ad, 'Axum': city_ax},
            'districts': {
                'Mekelle District': d_mekele,
                'Eastern District': d_eastern,
                'Central District': d_central,
            },
            'branches': branches,
        }

    # ------------------------------------------------------------------ master
    def _seed_categories(self):
        specs = [
            ('MSME Trade', 'msme'),
            ('MSME Agriculture', 'msme'),
            ('MSME Manufacturing', 'msme'),
            ('MSME Services', 'msme'),
            ('Corporate Working Capital', 'corporate'),
            ('Corporate CapEx', 'corporate'),
        ]
        out = {}
        for name, mode in specs:
            cat, created = LoanCategory.objects.get_or_create(
                name=name, defaults={'appraisal_mode': mode}
            )
            if not created and cat.appraisal_mode != mode:
                cat.appraisal_mode = mode
                cat.save(update_fields=['appraisal_mode'])
            out[name] = cat
        self.stdout.write(self.style.SUCCESS(f'  Loan categories: {len(out)}'))
        return out

    def _seed_collateral_types(self):
        names = [
            'Building / House',
            'Land',
            'Vehicle',
            'Machinery / Equipment',
            'Other Movable',
        ]
        out = {}
        for name in names:
            ct, _ = CollateralType.objects.get_or_create(name=name)
            out[name] = ct
        self.stdout.write(self.style.SUCCESS(f'  Collateral types: {len(out)}'))
        return out

    def _seed_document_types(self):
        docs = [
            ('National ID / Kebele ID', 10, True, True),
            ('TIN Certificate', 20, True, True),
            ('Business License', 30, True, False),
            ('Bank Statement (6 months)', 40, True, False),
            ('Proof of Income', 50, False, False),
            ('Collateral Title / Ownership Doc', 60, True, True),
            ('Audited Financial Statements', 70, False, False),
            ('Marriage Certificate (if applicable)', 80, False, False),
        ]
        for name, order, required, ocr in docs:
            LoanApplicationDocumentType.objects.get_or_create(
                name=name,
                defaults={
                    'order': order,
                    'is_required': required,
                    'enable_ocr_match': ocr,
                    'allowed_extensions': 'pdf,jpg,jpeg,png',
                    'max_file_size_mb': 10,
                },
            )
        self.stdout.write(self.style.SUCCESS(
            f'  Document types: {LoanApplicationDocumentType.objects.count()}'
        ))

    def _seed_configs(self):
        CollateralEstimationConfig.objects.get_or_create(
            pk=1, defaults={'mode': CollateralEstimationConfig.MODE_BOTH}
        )
        cfg = CollateralEstimationConfig.objects.first()
        if cfg and cfg.mode != CollateralEstimationConfig.MODE_BOTH:
            cfg.mode = CollateralEstimationConfig.MODE_BOTH
            cfg.save(update_fields=['mode'])

        LoanAnalysisPolicyConfig.objects.get_or_create(pk=1)
        DocumentAuthenticationPolicy.objects.get_or_create(pk=1)
        CommitteeApprovalPolicy.objects.get_or_create(pk=1)
        LatestLoanRequestID.objects.get_or_create(pk=1, defaults={'latest_id': 1000})
        self.stdout.write(self.style.SUCCESS('  Bank configs ensured'))

    def _seed_collateral_catalog(self, cities):
        catalog = [
            ('Foundation', [
                ('Excavation', [('Manual excavation', 'm³', '1500'), ('Machine excavation', 'm³', '2200')]),
                ('Concrete footing', [('C25 footing', 'm³', '8500')]),
            ]),
            ('Structure', [
                ('Columns', [('RC column C25', 'm³', '9200')]),
                ('Beams & slabs', [('RC slab C25', 'm³', '8800'), ('RC beam C25', 'm³', '9000')]),
            ]),
            ('Finishing', [
                ('Walls', [('Hollow block wall', 'm²', '650')]),
                ('Flooring', [('Ceramic tile', 'm²', '1200')]),
            ]),
        ]
        prices = {}
        for i, (mw_name, subs) in enumerate(catalog, start=1):
            mw, _ = MainWork.objects.get_or_create(name=mw_name, defaults={'order': i})
            for j, (sw_name, items) in enumerate(subs, start=1):
                sw, _ = SubWork.objects.get_or_create(
                    main_work=mw, name=sw_name,
                    defaults={'order': Decimal(f'{i}.{j}')},
                )
                for k, (ssw_name, unit, price) in enumerate(items, start=1):
                    ssw, _ = SubSubWork.objects.get_or_create(
                        sub_work=sw, name=ssw_name,
                        defaults={'unit_measure': unit, 'order': f'{i}.{j}.{k}'},
                    )
                    for city in cities.values():
                        up, _ = SubWorkUnitPrice.objects.get_or_create(
                            sub_sub_work=ssw,
                            city=city,
                            sub_work=None,
                            defaults={'unit_price': Decimal(price)},
                        )
                        prices[(ssw.id, city.id)] = up
        self.stdout.write(self.style.SUCCESS(
            f'  Catalog: {MainWork.objects.count()} main works, '
            f'{SubWorkUnitPrice.objects.count()} unit prices'
        ))
        return {'prices': prices, 'cities': cities}

    # ------------------------------------------------------------------ users
    def _ensure_user(self, username, **defaults):
        user, created = CustomUser.objects.get_or_create(
            username=username,
            defaults=defaults,
        )
        changed = False
        for key, value in defaults.items():
            if key == 'password':
                continue
            if getattr(user, key) != value:
                setattr(user, key, value)
                changed = True
        if created or not user.has_usable_password():
            user.set_password(DEFAULT_PASSWORD)
            changed = True
        if created:
            user.set_password(DEFAULT_PASSWORD)
            changed = True
        # Always reset demo passwords so seed is predictable
        user.set_password(DEFAULT_PASSWORD)
        if changed or True:
            user.save()
        return user

    def _seed_users(self, geo):
        b = geo['branches']
        d = geo['districts']
        users = {}

        users['admin_sys'] = self._ensure_user(
            'admin.sys', email='admin.sys@decsi.local', phone_number='0911000001',
            role='admin', first_name='System', last_name='Admin',
            is_staff=True, is_superuser=False,
        )
        users['eng_head'] = self._ensure_user(
            'eng.head', email='eng.head@decsi.local', phone_number='0911000002',
            role='engineering_head', first_name='Hagos', last_name='Berhe',
            district=d['Mekelle District'],
        )
        users['eng1'] = self._ensure_user(
            'eng.mekele', email='eng.mekele@decsi.local', phone_number='0911000003',
            role='engineer', first_name='Selam', last_name='Gebre',
            district=d['Mekelle District'], branch=b['Mekelle Main Branch'],
        )
        users['eng2'] = self._ensure_user(
            'eng.adigrat', email='eng.adigrat@decsi.local', phone_number='0911000004',
            role='engineer', first_name='Meron', last_name='Tesfay',
            district=d['Eastern District'], branch=b['Adigrat Branch'],
        )
        users['bm1'] = self._ensure_user(
            'bm.mekele', email='bm.mekele@decsi.local', phone_number='0911000010',
            role='branch_manager', first_name='Alem', last_name='Hailu',
            district=d['Mekelle District'], branch=b['Mekelle Main Branch'],
        )
        users['bm2'] = self._ensure_user(
            'bm.adigrat', email='bm.adigrat@decsi.local', phone_number='0911000011',
            role='branch_manager', first_name='Tigist', last_name='Araya',
            district=d['Eastern District'], branch=b['Adigrat Branch'],
        )
        users['bm3'] = self._ensure_user(
            'bm.axum', email='bm.axum@decsi.local', phone_number='0911000012',
            role='branch_manager', first_name='Yonas', last_name='Kebede',
            district=d['Central District'], branch=b['Axum Branch'],
        )
        users['lo1'] = self._ensure_user(
            'lo.mekele1', email='lo.mekele1@decsi.local', phone_number='0911000020',
            role='loan_officer', first_name='Sara', last_name='Mebrahtu',
            district=d['Mekelle District'], branch=b['Mekelle Main Branch'],
        )
        users['lo2'] = self._ensure_user(
            'lo.mekele2', email='lo.mekele2@decsi.local', phone_number='0911000021',
            role='loan_officer', first_name='Dawit', last_name='Abraha',
            district=d['Mekelle District'], branch=b['Mekelle Industrial Branch'],
        )
        users['lo3'] = self._ensure_user(
            'lo.adigrat', email='lo.adigrat@decsi.local', phone_number='0911000022',
            role='loan_officer', first_name='Helen', last_name='Girmay',
            district=d['Eastern District'], branch=b['Adigrat Branch'],
        )
        users['acct1'] = self._ensure_user(
            'acct.mekele', email='acct.mekele@decsi.local', phone_number='0911000030',
            role='accountant', first_name='Kidane', last_name='Welde',
            district=d['Mekelle District'], branch=b['Mekelle Main Branch'],
        )
        users['dm1'] = self._ensure_user(
            'dm.mekele', email='dm.mekele@decsi.local', phone_number='0911000040',
            role='district_manager', first_name='Berhanu', last_name='Tadesse',
            district=d['Mekelle District'],
        )
        users['op'] = self._ensure_user(
            'op.manager', email='op.manager@decsi.local', phone_number='0911000050',
            role='operation_manager', first_name='Mulugeta', last_name='Assefa',
        )
        users['fin'] = self._ensure_user(
            'fin.manager', email='fin.manager@decsi.local', phone_number='0911000051',
            role='finance_manager', first_name='Rahel', last_name='Gebremichael',
        )
        users['cc1'] = self._ensure_user(
            'cc.member1', email='cc1@decsi.local', phone_number='0911000060',
            role='credit_committee', first_name='Fitsum', last_name='Negash',
            district=d['Mekelle District'], branch=b['Mekelle Main Branch'],
        )
        users['cc2'] = self._ensure_user(
            'cc.member2', email='cc2@decsi.local', phone_number='0911000061',
            role='credit_committee', first_name='Liya', last_name='Haile',
            district=d['Eastern District'], branch=b['Adigrat Branch'],
        )
        users['ceo'] = self._ensure_user(
            'ceo', email='ceo@decsi.local', phone_number='0911000070',
            role='ceo', first_name='Executive', last_name='CEO', is_staff=True,
        )
        users['vp'] = self._ensure_user(
            'vp', email='vp@decsi.local', phone_number='0911000071',
            role='vp', first_name='Executive', last_name='VP',
        )
        users['board'] = self._ensure_user(
            'board.member', email='board@decsi.local', phone_number='0911000072',
            role='board_member', first_name='Board', last_name='Member',
        )
        users['risk'] = self._ensure_user(
            'risk.officer', email='risk@decsi.local', phone_number='0911000080',
            role='risk_compliance', first_name='Risk', last_name='Officer',
        )
        users['auditor'] = self._ensure_user(
            'auditor', email='auditor@decsi.local', phone_number='0911000081',
            role='auditor', first_name='Internal', last_name='Auditor',
        )

        # Keep existing admin usable with known demo password too (optional)
        admin = CustomUser.objects.filter(username='admin').first()
        if admin:
            admin.role = 'superadmin'
            admin.phone_number = admin.phone_number or '0911000000'
            admin.set_password(DEFAULT_PASSWORD)
            admin.save()
            users['admin'] = admin

        self.stdout.write(self.style.SUCCESS(f'  Users: {CustomUser.objects.count()}'))
        return users

    def _seed_committee(self, users):
        levels = [
            (ApprovalCommitteeLevel.LEVEL_BRANCH, 'Branch Committee', 1, '2', None, '500000'),
            (ApprovalCommitteeLevel.LEVEL_DISTRICT, 'District Committee', 2, '2', '500000.01', '2000000'),
            (ApprovalCommitteeLevel.LEVEL_HEAD_OFFICE, 'Head Office Committee', 3, '2', '2000000.01', '10000000'),
            (ApprovalCommitteeLevel.LEVEL_MANAGEMENT, 'Management Committee', 4, '2', '10000000.01', None),
        ]
        level_objs = {}
        for key, name, order, min_appr, min_amt, max_amt in levels:
            lvl, _ = ApprovalCommitteeLevel.objects.get_or_create(
                key=key,
                defaults={
                    'name': name,
                    'sequence_order': order,
                    'is_active': True,
                    'min_approvals_required': int(min_appr),
                    'min_declines_required': 2,
                    'min_loan_amount': Decimal(min_amt) if min_amt else None,
                    'max_loan_amount': Decimal(max_amt) if max_amt else None,
                },
            )
            level_objs[key] = lvl

        rules = [
            (ApprovalCommitteeLevel.LEVEL_BRANCH, 'role', 'branch_manager', None),
            (ApprovalCommitteeLevel.LEVEL_BRANCH, 'role', 'accountant', None),
            (ApprovalCommitteeLevel.LEVEL_BRANCH, 'role', 'credit_committee', None),
            (ApprovalCommitteeLevel.LEVEL_DISTRICT, 'role', 'district_manager', None),
            (ApprovalCommitteeLevel.LEVEL_DISTRICT, 'role', 'credit_committee', None),
            (ApprovalCommitteeLevel.LEVEL_HEAD_OFFICE, 'role', 'operation_manager', None),
            (ApprovalCommitteeLevel.LEVEL_HEAD_OFFICE, 'role', 'finance_manager', None),
            (ApprovalCommitteeLevel.LEVEL_MANAGEMENT, 'user', '', users['ceo']),
            (ApprovalCommitteeLevel.LEVEL_MANAGEMENT, 'user', '', users['vp']),
            (ApprovalCommitteeLevel.LEVEL_MANAGEMENT, 'user', '', users['board']),
        ]
        for key, ptype, role, user in rules:
            lvl = level_objs[key]
            defaults = {
                'participant_type': ptype,
                'role': role or '',
                'user': user,
                'is_active': True,
                'label': role or (user.username if user else ''),
            }
            if ptype == 'role':
                ApprovalCommitteeMemberRule.objects.get_or_create(
                    level=lvl, participant_type='role', role=role, defaults=defaults,
                )
            else:
                ApprovalCommitteeMemberRule.objects.get_or_create(
                    level=lvl, participant_type='user', user=user, defaults=defaults,
                )
        self.stdout.write(self.style.SUCCESS(
            f'  Committee levels: {ApprovalCommitteeLevel.objects.count()}'
        ))

    # ------------------------------------------------------------------ loans
    def _next_loan_id(self, n):
        counter, _ = LatestLoanRequestID.objects.get_or_create(pk=1, defaults={'latest_id': 1000})
        counter.latest_id = max(counter.latest_id, 1000) + n
        counter.save(update_fields=['latest_id'])
        return f'DCSI-{counter.latest_id:06d}'

    def _seed_loans(self, geo, categories, collateral_types, users, catalog):
        now = timezone.now()
        b = geo['branches']
        d = geo['districts']
        city_me = catalog['cities']['Mekelle']

        specs = [
            # Pending manager queue
            dict(
                key='pending1', applicant='Abebe Kebede', phone='0912111001',
                customer_number='1001', category='MSME Trade', collateral='Building / House',
                amount='350000', branch=b['Mekelle Main Branch'], district=d['Mekelle District'],
                reason='Working capital for retail shop expansion',
                op=False, fin=False, status_hint='Pending', days_ago=3,
                officer=users['lo1'], history='new',
            ),
            dict(
                key='pending2', applicant='Aster Girmay', phone='0912111002',
                customer_number='1002', category='MSME Agriculture', collateral='Land',
                amount='180000', branch=b['Adigrat Branch'], district=d['Eastern District'],
                reason='Input financing for irrigation farming',
                op=False, fin=False, status_hint='Pending', days_ago=5,
                officer=users['lo3'], history='existing',
            ),
            # Op approved only
            dict(
                key='op_only', applicant='Tekle Hagos', phone='0912111003',
                customer_number='1003', category='MSME Services', collateral='Vehicle',
                amount='420000', branch=b['Mekelle Industrial Branch'], district=d['Mekelle District'],
                reason='Purchase of delivery van for logistics',
                op=True, fin=False, status_hint='Pending', days_ago=7,
                officer=users['lo2'], history='new',
            ),
            # Queue approved — assigned officer, ready for collateral/appraisal
            dict(
                key='queue1', applicant='Frehiwot Desta', phone='0912111004',
                customer_number='1004', category='MSME Manufacturing', collateral='Building / House',
                amount='750000', branch=b['Mekelle Main Branch'], district=d['Mekelle District'],
                reason='Machinery upgrade for small bakery',
                op=True, fin=True, status_hint='Approved', days_ago=10,
                officer=users['lo1'], engineer=users['eng1'], history='existing',
                with_building=True, with_appraisal=True, score='78.50', band='acceptable',
            ),
            dict(
                key='queue2', applicant='Mulugeta Haileselassie', phone='0912111005',
                customer_number='1005', category='MSME Trade', collateral='Other Movable',
                amount='220000', branch=b['Axum Branch'], district=d['Central District'],
                reason='Inventory financing for electronics shop',
                op=True, fin=True, status_hint='Approved', days_ago=12,
                officer=users['lo1'], history='new',
                with_other=True, with_appraisal=True, score='65.00', band='acceptable',
            ),
            # Land collateral sample
            dict(
                key='queue3', applicant='Genet Asmelash', phone='0912111006',
                customer_number='1006', category='MSME Agriculture', collateral='Land',
                amount='500000', branch=b['Wukro Branch'], district=d['Eastern District'],
                reason='Land development for commercial farming',
                op=True, fin=True, status_hint='Approved', days_ago=14,
                officer=users['lo3'], engineer=users['eng2'], history='existing',
                with_land=True, with_appraisal=True, score='71.00', band='acceptable',
            ),
            # Corporate
            dict(
                key='corp1', applicant='Tigray Agro Processing PLC', phone='0912111007',
                customer_number='2001', category='Corporate Working Capital', collateral='Building / House',
                amount='5500000', branch=b['Mekelle Main Branch'], district=d['Mekelle District'],
                reason='Working capital for seasonal procurement',
                op=True, fin=True, status_hint='Approved', days_ago=8,
                officer=users['lo2'], history='existing',
                with_building=True, with_appraisal=True, score='82.00', band='strong',
                corporate=True,
            ),
            # Rejected
            dict(
                key='rejected1', applicant='Solomon Berhe', phone='0912111008',
                customer_number='1008', category='MSME Trade', collateral='Vehicle',
                amount='90000', branch=b['Shire Branch'], district=d['Central District'],
                reason='Personal consumption — declined sample',
                op=False, fin=False, status_hint='Rejected', days_ago=20,
                officer=users['lo1'], history='new', force_rejected=True,
            ),
            # Committee pending after appraisal
            dict(
                key='committee1', applicant='Hiwot Gebrehiwot', phone='0912111009',
                customer_number='1009', category='MSME Services', collateral='Building / House',
                amount='950000', branch=b['Mekelle Main Branch'], district=d['Mekelle District'],
                reason='Clinic renovation and equipment',
                op=True, fin=True, status_hint='Approved', days_ago=18,
                officer=users['lo1'], history='existing',
                with_building=True, with_appraisal=True, score='74.00', band='acceptable',
                committee='pending',
            ),
            # Committee approved
            dict(
                key='committee2', applicant='Yared Manufacturing', phone='0912111010',
                customer_number='1010', category='MSME Manufacturing', collateral='Machinery / Equipment',
                amount='1250000', branch=b['Mekelle Industrial Branch'], district=d['Mekelle District'],
                reason='CNC machine acquisition',
                op=True, fin=True, status_hint='Approved', days_ago=30,
                officer=users['lo2'], history='existing',
                with_other=True, with_appraisal=True, score='86.00', band='strong',
                committee='approved',
            ),
            # More pending for dashboard volume
            dict(
                key='pending3', applicant='Rediet Alemu', phone='0912111011',
                customer_number='1011', category='MSME Trade', collateral='Other Movable',
                amount='150000', branch=b['Adigrat Branch'], district=d['Eastern District'],
                reason='Stock replenishment for boutique',
                op=False, fin=False, status_hint='Pending', days_ago=1,
                officer=users['lo3'], history='new',
            ),
            dict(
                key='pending4', applicant='Kaleb Construction', phone='0912111012',
                customer_number='2012', category='Corporate CapEx', collateral='Land',
                amount='12000000', branch=b['Mekelle Main Branch'], district=d['Mekelle District'],
                reason='Site acquisition for warehouse expansion',
                op=True, fin=True, status_hint='Approved', days_ago=4,
                officer=users['lo1'], history='existing',
                with_land=True, with_appraisal=True, score='69.00', band='weak',
                corporate=True,
            ),
        ]

        loans = []
        for i, spec in enumerate(specs, start=1):
            loan = self._upsert_loan(spec, now, i, city_me, categories, collateral_types, users)
            loans.append(loan)

        self.stdout.write(self.style.SUCCESS(f'  Loan requests: {LoanRequest.objects.count()}'))
        return loans

    def _upsert_loan(self, spec, now, index, city_me, categories, collateral_types, users):
        # Stable ID based on key for idempotency
        loan_id = f'DCSI-S{index:04d}'
        loan = LoanRequest.objects.filter(loan_request_id=loan_id).first()
        defaults = {
            'applicant_name': spec['applicant'],
            'phone_number': spec['phone'],
            'customer_number': spec.get('customer_number'),
            'email': f"{spec['key']}@example.com",
            'category': categories[spec['category']],
            'collateral': collateral_types[spec['collateral']],
            'amount_requested': Decimal(spec['amount']),
            'reason': spec['reason'],
            'branch': spec['branch'],
            'district': spec['district'],
            'customer_history': spec.get('history', 'new'),
            'date_requested': now - timedelta(days=spec.get('days_ago', 1)),
            'assigned_loan_officer': spec.get('officer'),
            'assigned_engineer': spec.get('engineer'),
            'operation_manager_approval': False,
            'finance_approval': False,
            'declared_address_text': f"{spec['applicant']} residence, {spec['branch'].name}, Tigray",
        }
        if loan is None:
            loan = LoanRequest(loan_request_id=loan_id, **defaults)
            loan.save()
        else:
            for k, v in defaults.items():
                setattr(loan, k, v)
            loan.save()

        # Apply approvals carefully (save() auto-sets status/queue)
        loan.operation_manager_approval = bool(spec.get('op'))
        loan.finance_approval = bool(spec.get('fin'))
        if spec.get('force_rejected'):
            loan.operation_manager_approval = False
            loan.finance_approval = False
            loan.status = 'Rejected'
            loan.queue_approved = False
            loan.date_reviewed = now - timedelta(days=2)
            loan.save()
        else:
            loan.save()

        if spec.get('officer') and loan.queue_approved:
            loan.documents_reviewed_at = now - timedelta(days=max(1, spec.get('days_ago', 2) - 2))
            loan.documents_reviewed_by = spec['officer']
            loan.save(update_fields=['documents_reviewed_at', 'documents_reviewed_by'])

        if spec.get('with_building'):
            building, _ = Building.objects.get_or_create(
                loan_request=loan,
                name=f"{spec['applicant']} Building",
                defaults={
                    'construction_type': 'Reinforced concrete',
                    'floors': 2,
                    'city': city_me,
                    'site_gps_lat': Decimal('13.49670000'),
                    'site_gps_lon': Decimal('39.47530000'),
                },
            )
            if not BuildingValuation.objects.filter(building=building).exists():
                ssw = SubSubWork.objects.filter(name='RC slab C25').first()
                if ssw:
                    BuildingValuation.objects.create(
                        building=building,
                        sub_sub_work=ssw,
                        quantity=Decimal('85'),
                        unit_price=Decimal('8800'),
                    )

        if spec.get('with_land'):
            LandValuation.objects.get_or_create(
                loan_request=loan,
                defaults={
                    'land_size_sqm': Decimal('450'),
                    'unit_price_per_sqm': Decimal('2500'),
                    'notes': f'Plot near {spec["branch"].name}',
                    'site_gps_lat': Decimal('13.50010000'),
                    'site_gps_lon': Decimal('39.47000000'),
                },
            )

        if spec.get('with_other'):
            OtherCollateralItem.objects.get_or_create(
                loan_request=loan,
                name='Sample movable asset',
                defaults={
                    'notes': 'Generator / equipment package',
                    'estimated_value': Decimal('280000'),
                    'condition_grade': 'good',
                    'make_model': 'Generic Equipment Pack',
                    'year_made': 2022,
                },
            )

        if spec.get('with_appraisal') and spec.get('officer'):
            appraisal, _ = LoanAppraisal.objects.get_or_create(
                loan_request=loan,
                defaults={'created_by': spec['officer']},
            )
            mode = 'corporate' if spec.get('corporate') else 'msme'
            appraisal.appraisal_mode = mode
            appraisal.credit_score_total = Decimal(spec.get('score', '70'))
            appraisal.credit_score_band = spec.get('band', 'acceptable')
            appraisal.dscr = Decimal('1.35')
            appraisal.dscr_annual = Decimal('1.40')
            appraisal.net_monthly_cashflow = Decimal('45000')
            appraisal.proposed_monthly_installment = Decimal('32000')
            appraisal.qualitative_total_score = Decimal('78')
            appraisal.qualitative_passed = True
            appraisal.recommendation = 'approve'
            appraisal.recommendation_comment = 'Sample seeded recommendation — adequate cashflow and collateral.'
            appraisal.amount_approved = Decimal(spec['amount'])
            appraisal.collateral_coverage_ratio = Decimal('1.25')
            if mode == 'corporate':
                appraisal.corp_annual_revenue = Decimal('18000000')
            appraisal.save()

            basic_info, _ = LoanRequestBasicInfo.objects.get_or_create(
                loan_request=loan,
                defaults={
                    'tin_number': f"00{index:08d}",
                    'business_name': spec['applicant'],
                    'term_months': 24,
                    'repayment_frequency': 'Monthly',
                    'interest_rate': Decimal('16.50'),
                    'interest_basis': 'Declining',
                    'home_address': loan.declared_address_text,
                    'business_address': loan.declared_address_text,
                    'economic_sector': 'Trade',
                    'form_of_ownership': 'Sole Proprietorship',
                    'gender': 'Male',
                    'age': 35,
                },
            )
            AppraisalPurposeLine.objects.get_or_create(
                basic_info=basic_info,
                description='Primary purpose line',
                defaults={
                    'quantity': Decimal('1'),
                    'unit_price': Decimal(spec['amount']),
                    'value': Decimal(spec['amount']),
                    'display_order': 1,
                },
            )

            loan.appraisal_completed_at = now - timedelta(days=1)
            if spec.get('committee') == 'pending':
                loan.committee_status = LoanRequest.COMMITTEE_PENDING
                loan.submitted_to_committee_at = now - timedelta(hours=12)
                loan.submitted_to_committee_by = spec['officer']
                loan.committee_submission_notes = 'Submitted for sample committee review.'
                branch_level = ApprovalCommitteeLevel.objects.filter(
                    key=ApprovalCommitteeLevel.LEVEL_BRANCH
                ).first()
                loan.current_approval_level = branch_level
            elif spec.get('committee') == 'approved':
                loan.committee_status = LoanRequest.COMMITTEE_APPROVED
                loan.committee_final_decision = 'approve'
                loan.committee_final_amount = Decimal(spec['amount'])
                loan.committee_decided_at = now - timedelta(days=3)
                loan.submitted_to_committee_at = now - timedelta(days=5)
                loan.submitted_to_committee_by = spec['officer']
            loan.save()

        return loan

    def _seed_notifications(self, users, loans):
        if not loans:
            return
        sample = loans[0]
        for user_key in ('lo1', 'bm1', 'op', 'fin'):
            user = users.get(user_key)
            if not user:
                continue
            LoanNotification.objects.get_or_create(
                user=user,
                loan_request=sample,
                kind=LoanNotification.KIND_DOCUMENT_REQUESTED,
                title='Welcome to DECSI Loan Hub demo',
                defaults={
                    'message': 'Sample notification seeded for dashboard testing.',
                    'is_read': False,
                    'url': '/',
                },
            )
        self.stdout.write(self.style.SUCCESS(
            f'  Notifications: {LoanNotification.objects.count()}'
        ))
