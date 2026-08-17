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
    Department,
    ApprovalCommitteeLevel,
    ApprovalCommitteeMemberRule,
    AppraisalAmortizationEntry,
    AppraisalCondition,
    AppraisalCreditHistoryEntry,
    AppraisalESChecklistItem,
    AppraisalPurposeLine,
    AppraisalQualitativeFactor,
    AppraisalRiskMitigation,
    Branch,
    City,
    CollateralEstimationConfig,
    CollateralType,
    CommitteeApprovalPolicy,
    CustomUser,
    DelegationActionLog,
    District,
    DocumentAuthenticationPolicy,
    ES_CHECKLIST_STRUCTURE,
    LatestLoanRequestID,
    LoanAnalysisPolicyConfig,
    LoanApplicationDocumentType,
    LoanAppraisal,
    LoanCategory,
    LoanNotification,
    LoanRequest,
    LoanRequestBasicInfo,
    LoanRequestDocument,
    QUALITATIVE_RATING_CHOICES_BY_FACTOR,
    Region,
    StaffDelegation,
    Zone,
)
from loans.delegation import (
    SCOPE_APPRAISAL,
    SCOPE_ASSIGN_OFFICER,
    SCOPE_COMMITTEE,
    SCOPE_COOPERATIVE,
    SCOPE_FINANCE,
)
from loans.qualitative_scoring import best_rating_for_factor, update_appraisal_qualitative_totals
from loans.appraisal_scorecard import persist_credit_scorecard
from loans.appraisal_mode import qualitative_factor_keys_for_mode, ensure_appraisal_mode
from loans.cashflow_utils import (
    max_loan_capacity_from_cashflow,
    seed_monthly_grid_from_averages,
    suggested_installment_declining,
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
        self._seed_delegations(users)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Sample data ready.'))
        self.stdout.write(f'  Login password for demo users: {DEFAULT_PASSWORD}')
        self.stdout.write('  Examples: bm.mekele / lo.mekele1 / eng.head / coop.manager / ceo / admin.sys')
        self.stdout.write('  Delegation demo: acct.mekele acts for bm.mekele (Alem locked out until cover ends)')
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
            ('Collateral Restriction (government)', 65, False, False),
            ('Loan Collateral Power of Attorney', 66, False, False),
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
        users['lo1b'] = self._ensure_user(
            'lo.mekele3', email='lo.mekele3@decsi.local', phone_number='0911000023',
            role='loan_officer', first_name='Frehiwot', last_name='Gebreselassie',
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
        users['dlo1'] = self._ensure_user(
            'lo.district.mekele', email='lo.district.mekele@decsi.local', phone_number='0911000041',
            role='loan_officer', first_name='District', last_name='Officer',
            district=d['Mekelle District'], branch=None,
        )
        users['auditor_br'] = self._ensure_user(
            'auditor.mekele', email='auditor.mekele@decsi.local', phone_number='0911000082',
            role='auditor', first_name='Branch', last_name='Auditor',
            district=d['Mekelle District'], branch=b['Mekelle Main Branch'],
        )
        users['op'] = self._ensure_user(
            'coop.manager', email='coop.manager@decsi.local', phone_number='0911000050',
            role='cooperative_manager', first_name='Mulugeta', last_name='Assefa',
            district=d['Mekelle District'], branch=b['Mekelle Main Branch'],
        )
        # Alias for older seed references
        users['coop'] = users['op']
        users['credit_head'] = self._ensure_user(
            'credit.head', email='credit.head@decsi.local', phone_number='0911000052',
            role='credit_head', first_name='Selam', last_name='Berhe',
        )
        users['credit_lo'] = self._ensure_user(
            'credit.lo', email='credit.lo@decsi.local', phone_number='0911000053',
            role='credit_loan_officer', first_name='Hagos', last_name='Alemu',
        )
        users['fin'] = self._ensure_user(
            'fin.manager', email='fin.manager@decsi.local', phone_number='0911000051',
            role='finance_manager', first_name='Rahel', last_name='Gebremichael',
        )
        users['fin_asst'] = self._ensure_user(
            'fin.assistant', email='fin.assistant@decsi.local', phone_number='0911000054',
            role='accountant', first_name='Senait', last_name='Hailu',
        )
        users['ceo'] = self._ensure_user(
            'ceo', email='ceo@decsi.local', phone_number='0911000070',
            role='ceo', first_name='Executive', last_name='CEO', is_staff=True,
        )
        users['vp'] = self._ensure_user(
            'vp', email='vp@decsi.local', phone_number='0911000071',
            role='vp', first_name='Executive', last_name='VP',
        )
        users['vp_ops'] = self._ensure_user(
            'vp.operations', email='vp.operations@decsi.local', phone_number='0911000073',
            role='vp_operations', first_name='Operations', last_name='VP',
        )
        users['vp_it'] = self._ensure_user(
            'vp.it', email='vp.it@decsi.local', phone_number='0911000074',
            role='vp_it', first_name='IT', last_name='VP',
        )
        users['vp_cs'] = self._ensure_user(
            'vp.customerservice', email='vp.cs@decsi.local', phone_number='0911000075',
            role='vp_customer_service', first_name='Customer', last_name='Service VP',
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


        # Departments + HO attachments
        dept_defs = [
            (Department.KEY_COOPERATIVE, 'Branch Cooperative', 1),
            (Department.KEY_FINANCE, 'Finance', 2),
            (Department.KEY_CREDIT, 'Credit', 3),
            (Department.KEY_MANAGEMENT, 'Management', 4),
            (Department.KEY_BOARD, 'Board of Directors', 5),
        ]
        depts = {}
        for key, name, order in dept_defs:
            dept, _ = Department.objects.get_or_create(
                key=key, defaults={'name': name, 'sort_order': order, 'is_active': True},
            )
            depts[key] = dept
        role_dept = {
            'cooperative_manager': Department.KEY_COOPERATIVE,
            'finance_manager': Department.KEY_FINANCE,
            'credit_head': Department.KEY_CREDIT,
            'credit_loan_officer': Department.KEY_CREDIT,
            'ceo': Department.KEY_MANAGEMENT,
            'vp': Department.KEY_MANAGEMENT,
            'vp_operations': Department.KEY_MANAGEMENT,
            'vp_it': Department.KEY_MANAGEMENT,
            'vp_customer_service': Department.KEY_MANAGEMENT,
            'board_member': Department.KEY_BOARD,
        }
        # Finance assistant sits in Finance dept (same sphere as finance manager)
        if users.get('fin_asst'):
            users['fin_asst'].department = depts[Department.KEY_FINANCE]
            users['fin_asst'].save(update_fields=['department'])
        for u in users.values():
            key = role_dept.get(getattr(u, 'role', None))
            if key and getattr(u, 'department_id', None) != depts[key].id:
                u.department = depts[key]
                u.save(update_fields=['department'])


        # Retire legacy Credit Committee Member demo accounts
        for uname in ('cc.member1', 'cc.member2'):
            legacy = CustomUser.objects.filter(username=uname).first()
            if legacy and legacy.role == 'credit_committee':
                legacy.role = 'accountant'
                legacy.save(update_fields=['role'])

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
            (ApprovalCommitteeLevel.LEVEL_DISTRICT, 'role', 'district_manager', None),
            (ApprovalCommitteeLevel.LEVEL_HEAD_OFFICE, 'role', 'credit_head', None),
            (ApprovalCommitteeLevel.LEVEL_HEAD_OFFICE, 'role', 'credit_loan_officer', None),
            (ApprovalCommitteeLevel.LEVEL_HEAD_OFFICE, 'role', 'finance_manager', None),
            (ApprovalCommitteeLevel.LEVEL_MANAGEMENT, 'role', 'ceo', None),
            (ApprovalCommitteeLevel.LEVEL_MANAGEMENT, 'role', 'vp', None),
            (ApprovalCommitteeLevel.LEVEL_MANAGEMENT, 'role', 'vp_operations', None),
            (ApprovalCommitteeLevel.LEVEL_MANAGEMENT, 'role', 'vp_it', None),
            (ApprovalCommitteeLevel.LEVEL_MANAGEMENT, 'role', 'vp_customer_service', None),
            (ApprovalCommitteeLevel.LEVEL_MANAGEMENT, 'role', 'board_member', None),
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
            self._seed_full_appraisal(loan, spec, index, now)

        return loan

    def _ensure_qual_factors(self, appraisal):
        mode = ensure_appraisal_mode(appraisal, appraisal.loan_request)
        expected = qualitative_factor_keys_for_mode(mode)
        expected_keys = {k for k, _ in expected}
        appraisal.qualitative_factors.exclude(factor_key__in=expected_keys).delete()
        existing = set(appraisal.qualitative_factors.values_list('factor_key', flat=True))
        for order, (key, name) in enumerate(expected):
            if key not in existing:
                AppraisalQualitativeFactor.objects.create(
                    appraisal=appraisal,
                    factor_key=key,
                    factor_name=name,
                    display_order=order,
                )
            else:
                AppraisalQualitativeFactor.objects.filter(
                    appraisal=appraisal, factor_key=key,
                ).update(factor_name=name, display_order=order)

    def _ensure_es_items(self, appraisal):
        existing = set(appraisal.es_checklist_items.values_list('item_key', flat=True))
        order = 0
        for section_key, section_label, rows in ES_CHECKLIST_STRUCTURE:
            for item_key, question in rows:
                order += 1
                if item_key in existing:
                    continue
                AppraisalESChecklistItem.objects.create(
                    appraisal=appraisal,
                    section_key=section_key,
                    section_label=section_label,
                    item_key=item_key,
                    question_text=question,
                    display_order=order,
                )

    def _seed_corporate_audit_document(self, loan, officer, now):
        """Attach a verified Audited Financial Statements doc (corporate gate)."""
        from django.core.files.base import ContentFile

        dtype = LoanApplicationDocumentType.objects.filter(name__icontains='audit').first()
        if not dtype:
            return
        existing = loan.application_documents.filter(document_type=dtype).first()
        if existing:
            existing.auth_status = LoanRequestDocument.AUTH_VERIFIED
            existing.auth_verdict = LoanRequestDocument.VERDICT_AUTHENTIC
            existing.authenticated_by = officer
            existing.authenticated_at = now
            existing.save(update_fields=[
                'auth_status', 'auth_verdict', 'authenticated_by', 'authenticated_at',
            ])
            return
        doc = LoanRequestDocument(
            loan_request=loan,
            document_type=dtype,
            uploaded_by=officer,
            original_filename='audited_financials_demo.pdf',
            file_size=64,
            auth_status=LoanRequestDocument.AUTH_VERIFIED,
            auth_verdict=LoanRequestDocument.VERDICT_AUTHENTIC,
            authenticated_by=officer,
            authenticated_at=now,
            auth_notes='Demo seeded verified audited statements.',
        )
        doc.file.save(
            f'{loan.loan_request_id}_audited_financials.pdf',
            ContentFile(b'%PDF-1.4\n% demo audited financial statements\n'),
            save=True,
        )

    def _seed_amortization(self, appraisal, basic_info, loan):
        AppraisalAmortizationEntry.objects.filter(appraisal=appraisal).delete()
        amount = loan.amount_requested or Decimal('0')
        term_months = basic_info.term_months or 12
        annual_rate = (basic_info.interest_rate or Decimal('0')) / Decimal('100')
        if amount <= 0 or term_months <= 0:
            return
        n = term_months
        r = annual_rate / 12 if annual_rate else Decimal('0')
        balance = amount
        start = timezone.now().date()
        entries = []
        for period in range(1, n + 1):
            if r > 0:
                interest = (balance * r).quantize(Decimal('0.01'))
                remaining = n - period + 1
                principal = (balance / remaining).quantize(Decimal('0.01'))
                if period == n:
                    principal = balance
                payment = principal + interest
            else:
                interest = Decimal('0')
                principal = (amount / n).quantize(Decimal('0.01'))
                if period == n:
                    principal = balance
                payment = principal
            balance = max((balance - principal).quantize(Decimal('0.01')), Decimal('0'))
            # simple month add
            month = start.month - 1 + period
            year = start.year + month // 12
            month = month % 12 + 1
            day = min(start.day, 28)
            from datetime import date
            pay_date = date(year, month, day)
            entries.append(AppraisalAmortizationEntry(
                appraisal=appraisal,
                period_number=period,
                payment_date=pay_date,
                payment_amount=payment,
                principal=principal,
                interest=interest,
                balance_after=balance,
            ))
        AppraisalAmortizationEntry.objects.bulk_create(entries)

    def _seed_full_appraisal(self, loan, spec, index, now):
        """Populate Sheets 1–7 with realistic demo content."""
        officer = spec['officer']
        amount = Decimal(spec['amount'])
        mode = 'corporate' if spec.get('corporate') else 'msme'

        appraisal, _ = LoanAppraisal.objects.get_or_create(
            loan_request=loan,
            defaults={'created_by': officer},
        )
        ensure_appraisal_mode(appraisal, loan)
        appraisal.appraisal_mode = mode
        appraisal.created_by = officer

        # ----- Sheet 1 -----
        basic_info, _ = LoanRequestBasicInfo.objects.get_or_create(loan_request=loan)
        basic_info.tin_number = f'00{index:08d}'
        basic_info.gender = 'Female' if index % 2 == 0 else 'Male'
        basic_info.age = 28 + (index % 20)
        basic_info.marital_status = 'Married'
        basic_info.education_level = 'College'
        basic_info.home_address = loan.declared_address_text or f'Kebele {index}, Mekelle'
        basic_info.spouse_name = f'Spouse of {spec["applicant"].split()[0]}'
        basic_info.spouse_occupation = 'Trader' if index % 2 else 'Teacher'
        basic_info.father_name = f'Father-{index}'
        basic_info.grandfather_name = f'GFather-{index}'
        basic_info.business_name = spec['applicant']
        basic_info.business_description = spec['reason']
        basic_info.business_address = loan.declared_address_text or f'Business kebele {index}'
        basic_info.date_business_started = (now - timedelta(days=365 * (3 + index % 5))).date()
        basic_info.form_of_ownership = 'PLC' if mode == 'corporate' else 'Sole Proprietorship'
        basic_info.economic_sector = 'Trade'
        basic_info.subsector_activity = spec['category']
        basic_info.employees_full_time = 4 + index
        basic_info.employees_part_time = 2
        basic_info.employees_seasonal = 1
        basic_info.employees_ft_equivalent = Decimal(str(4 + index)) + Decimal('0.50')
        basic_info.family_members_employed = 1 + (index % 2)
        basic_info.number_business_owners = 3 if mode == 'corporate' else 1
        basic_info.peak_sales_months = 'Nov-Jan'
        basic_info.lowest_sales_months = 'Jun-Aug'
        basic_info.peak_sales_percent = Decimal('130')
        basic_info.lowest_sales_percent = Decimal('70')
        basic_info.term_months = 24
        basic_info.repayment_frequency = 'Monthly'
        basic_info.interest_rate = Decimal('16.50')
        basic_info.interest_basis = 'Declining'
        basic_info.grace_period_months = 0
        basic_info.interest_only_months = 0
        basic_info.instalments_per_year = 12
        basic_info.cash_contribution = (amount * Decimal('0.20')).quantize(Decimal('0.01'))
        if mode == 'corporate':
            basic_info.legal_registration_number = f'CR/{1000 + index}'
            basic_info.directors_summary = 'Board of 3 directors; managing director is primary contact.'
            basic_info.ubo_summary = 'Two UBOs hold 60% / 40%; both Ethiopian nationals.'
        basic_info.save()

        AppraisalPurposeLine.objects.filter(basic_info=basic_info).delete()
        AppraisalPurposeLine.objects.create(
            basic_info=basic_info,
            description='Working capital – inventory restock',
            quantity=Decimal('1'),
            unit_price=(amount * Decimal('0.70')).quantize(Decimal('0.01')),
            value=(amount * Decimal('0.70')).quantize(Decimal('0.01')),
            display_order=1,
        )
        AppraisalPurposeLine.objects.create(
            basic_info=basic_info,
            description='Investment – equipment / fixtures',
            quantity=Decimal('1'),
            unit_price=(amount * Decimal('0.30')).quantize(Decimal('0.01')),
            value=(amount * Decimal('0.30')).quantize(Decimal('0.01')),
            display_order=2,
        )

        # ----- Sheet 2 -----
        appraisal.nbe_credit_report_obtained = True
        appraisal.nbe_report_date_received = (now - timedelta(days=10)).date()
        appraisal.total_number_repaid_loans = 2
        appraisal.credit_history_max_score = Decimal('80')
        appraisal.bureau_score = Decimal('620')
        appraisal.bureau_score_band = 'good'
        appraisal.bureau_report_date = (now - timedelta(days=10)).date()
        appraisal.bureau_active_loans_count = 1
        appraisal.bureau_total_outstanding = Decimal('85000')
        appraisal.bureau_total_monthly_debt_service = Decimal('6500')
        appraisal.bureau_inquiries_6m = 1
        appraisal.bureau_defaults_ever = False
        appraisal.bureau_restructured_ever = False
        appraisal.bureau_thin_file = False
        appraisal.business_assessment = (
            'Established operator with stable local demand and adequate supplier access. '
            'Seasonality managed via inventory planning.'
        )
        appraisal.character_assessment = (
            'Cooperative client; documents provided; community references positive. '
            'No adverse character findings in branch file.'
        )
        appraisal.save()

        AppraisalCreditHistoryEntry.objects.filter(appraisal=appraisal).delete()
        AppraisalCreditHistoryEntry.objects.create(
            appraisal=appraisal,
            lender='DECSI (prior facility)',
            purpose='Working capital',
            loan_amount=Decimal('120000'),
            current_balance=Decimal('0'),
            maturity_date=(now - timedelta(days=90)).date(),
            status='settled_on_time',
            repayment='On time',
            letter_from_lender='Yes',
            score=Decimal('85'),
            display_order=1,
        )
        AppraisalCreditHistoryEntry.objects.create(
            appraisal=appraisal,
            lender='Other MFI (active)',
            purpose='Fixed Asset',
            loan_amount=Decimal('95000'),
            current_balance=Decimal('42000'),
            maturity_date=(now + timedelta(days=400)).date(),
            status='regular',
            repayment='Regular',
            letter_from_lender='Yes',
            score=Decimal('70'),
            display_order=2,
        )

        self._ensure_qual_factors(appraisal)
        # Dummy ratings: mostly strong, one mid-tier so scores are realistic not all 100
        mid_keys = {'project_plan', 'savings_record', 'transparency', 'related_party'}
        for factor in appraisal.qualitative_factors.all():
            opts = QUALITATIVE_RATING_CHOICES_BY_FACTOR.get(factor.factor_key) or []
            if factor.factor_key in mid_keys and len(opts) >= 2:
                factor.rating = opts[1]
            else:
                factor.rating = best_rating_for_factor(factor.factor_key) or (opts[0] if opts else '')
            factor.notes = f'Demo justification for {factor.factor_name or factor.factor_key}.'
            factor.save(update_fields=['rating', 'notes'])
        update_appraisal_qualitative_totals(appraisal)

        # ----- Sheet 3 -----
        # Sized so base + Excel-style stress (20% sales drop / 10% cost up) clear DSCR hard min ≥1.0
        # Corporate: scale P&L with ask so max cashflow capacity ≥ requested amount.
        drop_pct = Decimal('20')
        cost_pct = Decimal('10')
        other_inc = Decimal('5000')
        other_exp = Decimal('2000')
        if mode == 'corporate':
            sales = (amount / Decimal('5')).quantize(Decimal('0.01'))
            expenses = (sales * Decimal('0.46')).quantize(Decimal('0.01'))
            other_inc = (sales * Decimal('0.02')).quantize(Decimal('0.01'))
            other_exp = (sales * Decimal('0.01')).quantize(Decimal('0.01'))
            installment = suggested_installment_declining(
                amount, basic_info.interest_rate, basic_info.term_months, payments_per_year=12,
            )
            if not installment or installment <= 0:
                installment = (amount / Decimal('24')).quantize(Decimal('0.01'))
        else:
            sales = Decimal('280000')
            expenses = Decimal('130000')
            installment = Decimal('32000')

        appraisal.cf_monthly_sales = sales
        appraisal.cf_monthly_cogs = (sales * Decimal('0.36')).quantize(Decimal('0.01'))
        appraisal.cf_monthly_salaries = (expenses * Decimal('0.14')).quantize(Decimal('0.01'))
        appraisal.cf_monthly_rent = (expenses * Decimal('0.06')).quantize(Decimal('0.01'))
        appraisal.cf_monthly_utilities = (expenses * Decimal('0.02')).quantize(Decimal('0.01'))
        appraisal.cf_monthly_transport = (expenses * Decimal('0.01')).quantize(Decimal('0.01'))
        appraisal.cf_monthly_other_operating = Decimal('0')
        appraisal.cf_monthly_taxes = Decimal('0')
        appraisal.monthly_business_income = sales
        appraisal.monthly_business_expenses = expenses
        appraisal.other_monthly_income = other_inc
        appraisal.other_monthly_expenses = other_exp
        appraisal.proposed_monthly_installment = installment
        net = sales + other_inc - expenses - other_exp
        appraisal.net_monthly_cashflow = net
        appraisal.dscr = (net / installment).quantize(Decimal('0.01')) if installment else None
        appraisal.cf_annual_net_cashflow = (net * 12).quantize(Decimal('0.01'))
        appraisal.cf_annual_debt_service = (installment * 12).quantize(Decimal('0.01'))
        appraisal.dscr_annual = (
            appraisal.cf_annual_net_cashflow / appraisal.cf_annual_debt_service
        ).quantize(Decimal('0.01')) if installment else None
        appraisal.stress_sales_drop_pct = drop_pct
        appraisal.stress_cost_increase_pct = cost_pct
        # Same formula as AppraisalSheet3Form (not net*0.8 − expenses*0.1)
        stressed_inc = (sales + other_inc) * (Decimal('1') - drop_pct / Decimal('100'))
        stressed_exp = (expenses + other_exp) * (Decimal('1') + cost_pct / Decimal('100'))
        stressed_net = (stressed_inc - stressed_exp).quantize(Decimal('0.01'))
        appraisal.stressed_net_monthly_cashflow = stressed_net
        appraisal.stressed_dscr = (
            (stressed_net / installment).quantize(Decimal('0.01')) if installment else None
        )
        if mode == 'corporate':
            appraisal.bs_current_assets = (amount * Decimal('0.55')).quantize(Decimal('0.01'))
            appraisal.bs_current_liabilities = (amount * Decimal('0.22')).quantize(Decimal('0.01'))
            appraisal.bs_inventory = (amount * Decimal('0.15')).quantize(Decimal('0.01'))
            appraisal.bs_total_assets = (amount * Decimal('1.80')).quantize(Decimal('0.01'))
            appraisal.bs_total_liabilities = (amount * Decimal('0.55')).quantize(Decimal('0.01'))
            appraisal.bs_equity = (amount * Decimal('1.25')).quantize(Decimal('0.01'))
            appraisal.corp_annual_revenue = (sales * 12).quantize(Decimal('0.01'))
            appraisal.corp_operating_profit = (net * 12 * Decimal('0.55')).quantize(Decimal('0.01'))
            appraisal.bureau_score = Decimal('710')
            appraisal.bureau_score_band = 'excellent'
        else:
            appraisal.bs_current_assets = Decimal('450000')
            appraisal.bs_current_liabilities = Decimal('180000')
            appraisal.bs_inventory = Decimal('120000')
            appraisal.bs_total_assets = Decimal('980000')
            appraisal.bs_total_liabilities = Decimal('320000')
            appraisal.bs_equity = Decimal('660000')
        appraisal.ratio_current = Decimal('2.50')
        appraisal.ratio_acid_test = Decimal('1.83')
        appraisal.ratio_debt_equity = Decimal('0.48')
        appraisal.max_loan_capacity = max_loan_capacity_from_cashflow(
            appraisal.cf_annual_net_cashflow,
            basic_info.interest_rate,
            basic_info.term_months,
            target_dscr=Decimal('1.2'),
            payments_per_year=12,
        )
        appraisal.monthly_cashflow_grid = seed_monthly_grid_from_averages(sales, expenses)
        appraisal.save()

        # Banking conduct metrics (CREDIT_SCORE_ALGORITHM_V2) from customer number
        try:
            from loans.services.banking_transactions import refresh_appraisal_banking
            if (loan.customer_number or '').strip():
                refresh_appraisal_banking(appraisal, loan)
        except Exception:
            pass

        if mode == 'corporate':
            self._seed_corporate_audit_document(loan, officer, now)

        # ----- Sheet 4 (loan officer E&S sign-off — not committee) -----
        self._ensure_es_items(appraisal)
        for item in appraisal.es_checklist_items.all():
            # Default safe answers for demo
            if item.item_key in (
                'excluded_activities', 'displacement', 'child_labour',
                'green_area', 'chemicals_pesticides', 'pollutants', 'vegetation',
            ):
                item.response_yes_no = 'no'
                item.description = 'Not applicable for this activity.'
                item.mitigation = ''
            elif item.item_key in ('owner_of_premises', 'sanitation', 'waste_minimization'):
                item.response_yes_no = 'yes'
                item.description = 'Confirmed during field discussion.'
                item.mitigation = 'Maintain current controls.'
            else:
                item.response_yes_no = 'na'
                item.description = 'Reviewed; no material concern.'
                item.mitigation = 'Monitor during supervision.'
            item.save()

        appraisal.es_risk_category = LoanAppraisal.ES_RISK_LOW
        appraisal.es_eligibility_decision = LoanAppraisal.ES_ELIGIBILITY_PASS
        appraisal.es_screened_by = officer
        appraisal.es_checked_by = officer
        appraisal.es_approved_by = officer  # loan officer confirmation — committee signs later
        appraisal.es_assessment_date = (now - timedelta(days=2)).date()
        appraisal.es_notes = (
            'E&S screening completed by loan officer. Low residual risk. '
            'Credit committee signature occurs on committee pack / voting.'
        )

        # ----- Sheet 5 -----
        if mode == 'corporate':
            imm = Decimal('900000') if spec.get('with_building') or spec.get('with_land') else Decimal('0')
            mov = Decimal('280000') if spec.get('with_other') else Decimal('150000')
            # Scale immovable so coverage clears policy warning (≥1.0)
            need = (amount * Decimal('1.15')).quantize(Decimal('0.01'))
            if imm + mov + Decimal('100000') < need:
                imm = (need - mov - Decimal('100000')).quantize(Decimal('0.01'))
        else:
            imm = Decimal('900000') if spec.get('with_building') or spec.get('with_land') else Decimal('0')
            mov = Decimal('280000') if spec.get('with_other') else Decimal('150000')
        appraisal.collateral_immovable_value = imm
        appraisal.collateral_moveable_value = mov
        appraisal.collateral_intangible_value = Decimal('0')
        appraisal.collateral_guarantors_value = Decimal('100000')
        total_coll = imm + mov + Decimal('100000')
        appraisal.collateral_total_value = total_coll
        appraisal.collateral_coverage_ratio = (total_coll / amount).quantize(Decimal('0.01')) if amount else None

        # ----- Sheet 6 -----
        appraisal.recommendation = 'approve'
        appraisal.recommendation_comment = (
            'Cashflow capacity and collateral coverage support the request. '
            'Recommend approval subject to standard covenants.'
        )
        appraisal.strengths = (
            '- Adequate DSCR and net cashflow\n'
            '- Positive credit history / bureau band\n'
            '- Collateral coverage above policy minimum\n'
            '- E&S eligibility: PASS (loan officer screened)'
        )
        if mode == 'corporate':
            appraisal.weaknesses = (
                '- Working-capital seasonality / receivable concentration\n'
                '- Monitor covenant compliance post-disbursement'
            )
        else:
            appraisal.weaknesses = (
                '- Seasonal sales variability\n'
                '- Limited formal financial records (MSME typical)'
            )
        appraisal.committee_comments = (
            'For committee review: officer recommends approve. '
            'Committee members cast formal votes on the approval queue.'
        )
        appraisal.amount_approved = amount
        appraisal.term_approved_months = 24
        appraisal.rate_approved = Decimal('16.50')
        appraisal.credit_score_total = Decimal(spec.get('score', '75'))
        appraisal.credit_score_band = spec.get('band', 'acceptable')
        appraisal.save()

        AppraisalRiskMitigation.objects.filter(appraisal=appraisal).delete()
        AppraisalRiskMitigation.objects.create(
            appraisal=appraisal,
            risk='Seasonal cashflow shortfall',
            severity='medium',
            mitigation='Align repayment with peak months; grace if needed.',
            owner='Client / branch',
            status='Open',
            display_order=1,
        )
        AppraisalRiskMitigation.objects.create(
            appraisal=appraisal,
            risk='Collateral liquidity delay',
            severity='low',
            mitigation='Title verification completed; maintain insurance.',
            owner='Credit / engineering',
            status='In progress',
            display_order=2,
        )
        AppraisalCondition.objects.filter(appraisal=appraisal).delete()
        AppraisalCondition.objects.create(
            appraisal=appraisal,
            condition_type='cp',
            description='Submit updated tax clearance before disbursement.',
            responsible_party='Client',
            fulfilled=False,
            required_before_disbursement=True,
            display_order=1,
        )
        AppraisalCondition.objects.create(
            appraisal=appraisal,
            condition_type='covenant',
            description='Maintain collateral insurance for full loan term.',
            responsible_party='Client',
            fulfilled=False,
            required_before_disbursement=False,
            display_order=2,
        )

        persist_credit_scorecard(appraisal)

        # ----- Sheet 7 -----
        self._seed_amortization(appraisal, basic_info, loan)

        loan.appraisal_completed_at = now - timedelta(days=1)
        if spec.get('committee') == 'pending':
            loan.committee_status = LoanRequest.COMMITTEE_PENDING
            loan.submitted_to_committee_at = now - timedelta(hours=12)
            loan.submitted_to_committee_by = officer
            loan.committee_submission_notes = 'Submitted for sample committee review.'
            branch_level = ApprovalCommitteeLevel.objects.filter(
                key=ApprovalCommitteeLevel.LEVEL_BRANCH
            ).first()
            loan.current_approval_level = branch_level
        elif spec.get('committee') == 'approved':
            loan.committee_status = LoanRequest.COMMITTEE_APPROVED
            loan.committee_final_decision = 'approve'
            loan.committee_final_amount = amount
            loan.committee_decided_at = now - timedelta(days=3)
            loan.submitted_to_committee_at = now - timedelta(days=5)
            loan.submitted_to_committee_by = officer
            loan.disbursement_status = LoanRequest.DISBURSE_AWAITING_CONDITIONS
        loan.save()

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

    def _seed_delegations(self, users):
        """Realistic authority-cover scenarios for Mekelle / Adigrat demo staff."""
        now = timezone.now()
        admin = users.get('admin_sys') or users.get('admin')
        bm = users.get('bm1')
        acct = users.get('acct1')
        lo_sara = users.get('lo1')
        lo_fre = users.get('lo1b')
        lo_helen = users.get('lo3')
        eng_meron = users.get('eng2')
        coop = users.get('op')
        fin = users.get('fin')
        fin_asst = users.get('fin_asst')
        bm_adigrat = users.get('bm2')

        # Clear prior seed rows so re-runs stay idempotent
        StaffDelegation.objects.filter(reason__startswith='[SEED]').delete()
        DelegationActionLog.objects.filter(detail__seed=True).delete()

        def _make(**kwargs):
            return StaffDelegation.objects.create(**kwargs)

        created = []

        # 1) Active cover — BM Alem on leave; Kidane (accountant) assigns officers.
        #    Alem is locked out of the hub until ends_at.
        if bm and acct and admin:
            d = _make(
                principal=bm,
                delegate=acct,
                scopes=[SCOPE_ASSIGN_OFFICER, SCOPE_COMMITTEE],
                starts_at=now - timedelta(days=1),
                ends_at=now + timedelta(days=6),
                status=StaffDelegation.STATUS_APPROVED,
                is_active=True,
                reason='[SEED] Annual leave — family obligations in Adwa; Kidane covers officer assignment and branch committee votes',
                created_by=bm,
                reviewed_by=admin,
                reviewed_at=now - timedelta(hours=20),
            )
            created.append(d)
            DelegationActionLog.objects.create(
                delegation=d,
                actor=acct,
                principal=bm,
                action='seed_note',
                detail={'seed': True, 'note': 'Demo: log in as acct.mekele to assign officers while bm.mekele is locked out.'},
            )

        # 2) Pending — Helen (Adigrat LO) asks Meron (engineer, same branch) to cover appraisal
        if lo_helen and eng_meron:
            created.append(_make(
                principal=lo_helen,
                delegate=eng_meron,
                scopes=[SCOPE_APPRAISAL],
                starts_at=now,
                ends_at=now + timedelta(days=10),
                status=StaffDelegation.STATUS_PENDING,
                is_active=False,
                reason='[SEED] Credit training in Mekelle HQ — Meron to continue document / appraisal work on my Adigrat files',
                created_by=lo_helen,
            ))

        # 3) Pending — Finance Rahel proposes Senait for disbursement cover
        if fin and fin_asst:
            created.append(_make(
                principal=fin,
                delegate=fin_asst,
                scopes=[SCOPE_FINANCE],
                starts_at=now + timedelta(days=1),
                ends_at=now + timedelta(days=8),
                status=StaffDelegation.STATUS_PENDING,
                is_active=False,
                reason='[SEED] Audit fieldwork in Shire — Senait to clear ready disbursements in my absence',
                created_by=fin,
            ))

        # 4) Active — Sara LO covers Frehiwot for a short field mission (Sara locked out briefly)
        #    Skip locking second LO if we want lo.mekele1 for demos — use Frehiwot → Sara instead
        #    so Sara stays loginable: Frehiwot on leave, Sara covers her appraisals.
        if lo_sara and lo_fre and admin:
            created.append(_make(
                principal=lo_fre,
                delegate=lo_sara,
                scopes=[SCOPE_APPRAISAL],
                starts_at=now - timedelta(hours=6),
                ends_at=now + timedelta(days=4),
                status=StaffDelegation.STATUS_APPROVED,
                is_active=True,
                reason='[SEED] Field verification — Hawzen / Wukro corridor; Sara continues appraisal on my Mekelle Main files',
                created_by=lo_fre,
                reviewed_by=admin,
                reviewed_at=now - timedelta(hours=5),
            ))

        # 5) Ended (approved, window passed) — historical Adigrat BM cover
        if bm_adigrat and lo_helen and admin:
            created.append(_make(
                principal=bm_adigrat,
                delegate=lo_helen,
                scopes=[SCOPE_ASSIGN_OFFICER],
                starts_at=now - timedelta(days=20),
                ends_at=now - timedelta(days=12),
                status=StaffDelegation.STATUS_APPROVED,
                is_active=True,
                reason='[SEED] Medical leave (closed) — Helen temporarily assigned officers at Adigrat',
                created_by=bm_adigrat,
                reviewed_by=admin,
                reviewed_at=now - timedelta(days=20),
            ))

        # 6) Rejected — coop request that admin declined
        if coop and acct and admin:
            created.append(_make(
                principal=coop,
                delegate=acct,
                scopes=[SCOPE_COOPERATIVE],
                starts_at=now - timedelta(days=3),
                ends_at=now + timedelta(days=3),
                status=StaffDelegation.STATUS_REJECTED,
                is_active=False,
                reason='[SEED] Workshop attendance — request declined; keep intake with Cooperative desk',
                created_by=coop,
                reviewed_by=admin,
                reviewed_at=now - timedelta(days=2),
                review_note='Overlap with Kidane’s BM assign cover — use another cover person.',
            ))

        # 7) Revoked — short DM cover pulled early
        dm = users.get('dm1')
        if dm and bm and admin:
            created.append(_make(
                principal=dm,
                delegate=bm,
                scopes=[SCOPE_ASSIGN_OFFICER, SCOPE_COMMITTEE],
                starts_at=now - timedelta(days=8),
                ends_at=now + timedelta(days=2),
                status=StaffDelegation.STATUS_REVOKED,
                is_active=False,
                reason='[SEED] District conference travel — revoked when BM Alem started own leave cover',
                created_by=dm,
                reviewed_by=admin,
                reviewed_at=now - timedelta(days=7),
                revoked_at=now - timedelta(days=5),
                revoked_by=admin,
            ))

        self.stdout.write(self.style.SUCCESS(f'  Delegations seeded: {len(created)}'))
        self.stdout.write('    Active: Alem→Kidane (assign/committee), Frehiwot→Sara (appraisal)')
        self.stdout.write('    Pending: Helen→Meron (appraisal), Rahel→Senait (finance)')
        self.stdout.write('    Login as admin.sys to approve pending; acct.mekele to use BM cover')
