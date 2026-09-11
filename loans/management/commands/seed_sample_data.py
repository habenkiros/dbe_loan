"""
Populate demo master data, users, loans, appraisals, and collateral samples.

Usage:
  python manage.py seed_sample_data
  python manage.py seed_sample_data --flush-loans   # delete sample loans first
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import hashlib
import io

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
    LoanProcessPolicyConfig,
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
PORTAL_PASSWORD = 'Demo@12345'


def _demo_png(seed: str) -> bytes:
    """Unique but readable demo portrait (ID + matching selfie use the same seed)."""
    from PIL import Image, ImageDraw

    digest = hashlib.md5((seed or 'demo').encode()).digest()
    bg = (40 + digest[0] % 160, 50 + digest[1] % 160, 70 + digest[2] % 140)
    img = Image.new('RGB', (640, 480), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([24, 24, 616, 456], outline=(255, 255, 255), width=8)
    draw.ellipse([220, 90, 420, 290], fill=(240, 220, 200), outline=(40, 40, 40), width=3)
    label = (seed or 'ID')[:42]
    draw.rectangle([40, 340, 600, 430], fill=(20, 20, 40))
    draw.text((56, 368), label, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _demo_pdf(label: str) -> bytes:
    text = (label or 'demo document').replace('\\', ' ')[:80]
    return (
        b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n'
        b'2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n'
        b'3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n'
        b'trailer<</Root 1 0 R>>\n%%EOF\n%' + text.encode('ascii', 'ignore') + b'\n'
    )


class Command(BaseCommand):
    help = 'Seed sample geography, users, categories, loans, appraisals, and collateral data.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--flush-loans',
            action='store_true',
            help='Delete existing LoanRequest rows before seeding loans (keeps users/master data).',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('Seeding sample data…'))

        self._ensure_dbe_catalog()
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
        self._seed_required_packs(loans, users)
        self._seed_kyc_identity_packs(loans, users)
        self._seed_kyc_desk_packs(loans, users)
        self._seed_portal_applicants(geo, categories, collateral_types, users, loans)
        self._seed_notifications(users, loans)
        self._seed_delegations(users)

        from loans.seed_factory_tour import seed_full_factory_tour
        seed_full_factory_tour(
            stdout=self.stdout, style=self.style, loans=loans, users=users, geo=geo,
        )

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Sample data ready.'))
        self.stdout.write(f'  Login password for demo users: {DEFAULT_PASSWORD}')
        self.stdout.write('  Examples: bm.mekele / lo.mekele1 / eng.head / coop.manager / ceo / admin.sys')
        self.stdout.write('  Delegation demo: acct.mekele acts for bm.mekele (Alem locked out until cover ends)')
        self.stdout.write('  Digital Apply (same password):')
        self.stdout.write('    Person 0912111801 · documents unpaid')
        self.stdout.write('    Institution 0912111802 · Tigray MFI sample')
        self.stdout.write('    Promoter 0912111803 · Mekelle plant promoter')
        self.stdout.write('    Submitted 0912111804 · already in Scan inbox')
        self.stdout.write('    Fee-paid 0912111805 · ready to submit')
        self.stdout.write('  Market portal: 0912111901 / Demo@12345')
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
        for cat in LoanCategory.objects.all():
            out[cat.name] = cat
        self.stdout.write(self.style.SUCCESS(f'  Loan categories: {len(out)}'))
        return out

    def _seed_collateral_types(self):
        names = [
            ('Building / House', CollateralType.KIND_BUILDING),
            ('Land', CollateralType.KIND_LAND),
            ('Vehicle', CollateralType.KIND_MOVABLE),
            ('Machinery / Equipment', CollateralType.KIND_MOVABLE),
            ('Other Movable', CollateralType.KIND_MOVABLE),
            ('Building + Land', CollateralType.KIND_MIXED),
            ('Financed machinery / plant (from this loan)', CollateralType.KIND_FINANCED),
            ('Financed vehicle (from this loan)', CollateralType.KIND_FINANCED),
        ]
        out = {}
        for name, kind in names:
            ct, created = CollateralType.objects.get_or_create(name=name, defaults={'kind': kind})
            if not created and not ct.kind:
                ct.kind = kind
                ct.save(update_fields=['kind'])
            out[name] = ct
        self.stdout.write(self.style.SUCCESS(f'  Collateral types: {len(out)}'))
        return out

    def _seed_document_types(self):
        docs = [
            ('National ID / Kebele ID', 10, True, True),
            ('Director / beneficial owner ID', 12, False, True),
            ('UBO ownership evidence', 13, False, False),
            ('Guarantor identity document', 14, False, True),
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
            dt, created = LoanApplicationDocumentType.objects.get_or_create(
                name=name,
                defaults={
                    'order': order,
                    'is_required': required,
                    'enable_ocr_match': ocr,
                    'allowed_extensions': 'pdf,jpg,jpeg,png',
                    'max_file_size_mb': 10,
                },
            )
            from loans.services.document_extraction_defaults import ensure_document_type_extraction_defaults
            ensure_document_type_extraction_defaults(dt)
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

        from loans.process_policy import default_book_ops_roles, default_workout_decide_roles

        LoanAnalysisPolicyConfig.objects.get_or_create(pk=1)
        LoanProcessPolicyConfig.objects.get_or_create(
            pk=1,
            defaults={
                'book_ops_roles': default_book_ops_roles(),
                'workout_decide_roles': default_workout_decide_roles(),
            },
        )
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
            is_staff=True, is_superuser=True,
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
        users['legal'] = self._ensure_user(
            'legal.officer', email='legal@decsi.local', phone_number='0911000082',
            role='legal_officer', first_name='Legal', last_name='Officer',
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
        from loans.dbe_desks import DBE_DESK_SEED

        dept_defs = [
            (Department.KEY_COOPERATIVE, 'Branch Cooperative', 1),
            (Department.KEY_FINANCE, 'Finance', 2),
            (Department.KEY_CREDIT, 'Credit', 3),
            (Department.KEY_MANAGEMENT, 'Management', 4),
            (Department.KEY_BOARD, 'Board of Directors', 5),
            *DBE_DESK_SEED,
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
            'legal_officer': 'legal',
            'engineer': 'engineering',
            'engineering_head': 'engineering',
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

        extra = []
        if 'Project Financing' in categories:
            extra.append(dict(
                key='project1', applicant='Mekelle Cement Plant PLC', phone='0912111810',
                customer_number='3010', category='Project Financing', collateral='Land',
                amount='45000000', branch=b['Mekelle Main Branch'], district=d['Mekelle District'],
                reason='Greenfield cement grinding plant — promoter equity on file',
                op=True, fin=True, status_hint='Approved', days_ago=9,
                officer=users.get('credit_lo') or users['lo1'], engineer=users['eng1'],
                history='existing', with_land=True, with_building=True, with_appraisal=True,
                score='80.00', band='strong',
            ))
        if 'Wholesale / PFI Facility' in categories:
            extra.append(dict(
                key='wholesale1', applicant='Tigray Microfinance S.C.', phone='0912111811',
                customer_number='3011', category='Wholesale / PFI Facility',
                collateral='Building / House',
                amount='25000000', branch=b['Mekelle Main Branch'], district=d['Mekelle District'],
                reason='Working-capital on-lending facility for MSME book',
                op=True, fin=True, status_hint='Approved', days_ago=11,
                officer=users.get('credit_lo') or users['lo1'], history='existing',
                with_appraisal=True, score='77.00', band='acceptable',
            ))
        if 'Idea / Quasi-Equity' in categories:
            extra.append(dict(
                key='idea1', applicant='Axum AgriTech Start-up', phone='0912111812',
                customer_number='3012', category='Idea / Quasi-Equity',
                collateral='Other Movable',
                amount='3500000', branch=b['Axum Branch'], district=d['Central District'],
                reason='Cap-table backed quasi-equity for irrigation sensors',
                op=True, fin=True, status_hint='Approved', days_ago=6,
                officer=users.get('credit_lo') or users['lo1'], history='new',
                with_other=True, with_appraisal=True, score='72.00', band='acceptable',
            ))
        if 'Lease Financing' in categories:
            extra.append(dict(
                key='lease1', applicant='Adwa Workshop Lease', phone='0912111813',
                customer_number='4013', category='Lease Financing',
                collateral='Machinery / Equipment',
                amount='2800000', branch=b['Mekelle Industrial Branch'],
                district=d['Mekelle District'],
                reason='CNC lathe hire-purchase — bank holds title until buyout',
                op=True, fin=True, status_hint='Approved', days_ago=15,
                officer=users.get('credit_lo') or users['lo2'], history='existing',
                with_other=True, with_appraisal=True, score='76.00', band='acceptable',
            ))
        if 'IFB Ijarah' in categories:
            extra.append(dict(
                key='ijarah1', applicant='Shire Ijarah Transport', phone='0912111814',
                customer_number='4014', category='IFB Ijarah',
                collateral='Vehicle',
                amount='1900000', branch=b['Shire Branch'], district=d['Central District'],
                reason='Ijarah rental of two Isuzu trucks — Sharia cleared',
                op=True, fin=True, status_hint='Approved', days_ago=13,
                officer=users.get('credit_lo') or users['lo1'], history='existing',
                with_other=True, with_appraisal=True, score='74.00', band='acceptable',
            ))
        if 'IFB Murabaha' in categories:
            extra.append(dict(
                key='murabaha1', applicant='Mekelle Murabaha Traders', phone='0912111815',
                customer_number='4015', category='IFB Murabaha',
                collateral='Other Movable',
                amount='850000', branch=b['Mekelle Main Branch'], district=d['Mekelle District'],
                reason='Cost-plus purchase of construction materials from named supplier',
                op=True, fin=True, status_hint='Approved', days_ago=8,
                officer=users.get('credit_lo') or users['lo1'], history='existing',
                with_other=True, with_appraisal=True, score='73.00', band='acceptable',
            ))
        if 'Consumer Financing' in categories:
            extra.append(dict(
                key='consumer1', applicant='Selam Housing Consumer', phone='0912111816',
                customer_number='4016', category='Consumer Financing',
                collateral='Building / House',
                amount='1200000', branch=b['Mekelle Main Branch'], district=d['Mekelle District'],
                reason='Salary-backed housing loan — DTI and LTV on consumer desk',
                op=True, fin=True, status_hint='Approved', days_ago=16,
                officer=users['lo1'], history='existing',
                with_building=True, with_appraisal=True, score='81.00', band='strong',
            ))
        if 'External Fund Window' in categories:
            extra.append(dict(
                key='fund1', applicant='Youth Climate MSME', phone='0912111817',
                customer_number='4017', category='External Fund Window',
                collateral='Land',
                amount='640000', branch=b['Axum Branch'], district=d['Central District'],
                reason='Donor window — youth-owned climate-tagged agri MSME',
                op=True, fin=True, status_hint='Approved', days_ago=7,
                officer=users['lo1'], history='new',
                with_land=True, with_appraisal=True, score='70.00', band='acceptable',
            ))
        extra.append(dict(
            key='collections1', applicant='Wukro Collections Sample', phone='0912111818',
            customer_number='4018', category='MSME Manufacturing',
            collateral='Machinery / Equipment',
            amount='480000', branch=b['Wukro Branch'], district=d['Eastern District'],
            reason='Booked mill now 90+ DPD — collections and rehab sample',
            op=True, fin=True, status_hint='Approved', days_ago=120,
            officer=users['lo3'], history='existing',
            with_other=True, with_appraisal=True, score='68.00', band='weak',
            committee='approved',
        ))
        extra.append(dict(
            key='online1', applicant='Portal Submitted Applicant', phone='0912111819',
            customer_number='4019', category='MSME Trade',
            collateral='Building / House',
            amount='275000', branch=b['Mekelle Main Branch'], district=d['Mekelle District'],
            reason='Digital Apply submitted — Scan/Admin inbox sample',
            op=True, fin=True, status_hint='Approved', days_ago=2,
            officer=users['lo1'], history='new',
            with_building=True, online=True,
        ))
        specs.extend(extra)

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

        if spec.get('online'):
            loan.source_channel = LoanRequest.SOURCE_ONLINE
            loan.save(update_fields=['source_channel'])

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

        self._seed_product_overlay(loan, spec, users)
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
        from loans.product_family import resolve_product_family, suggested_appraisal_mode
        family = resolve_product_family(loan)
        suggested = suggested_appraisal_mode(family)
        if spec.get('corporate'):
            mode = 'corporate'
        elif suggested:
            mode = suggested
        else:
            mode = 'msme'
        heavy = mode in ('corporate', 'project', 'wholesale', 'idea_equity')

        appraisal, _ = LoanAppraisal.objects.get_or_create(
            loan_request=loan,
            defaults={'created_by': officer},
        )
        ensure_appraisal_mode(appraisal, loan)
        appraisal.appraisal_mode = mode
        appraisal.created_by = officer

        # ----- Sheet 1 -----
        basic_info, _ = LoanRequestBasicInfo.objects.get_or_create(loan_request=loan)
        basic_info.tin_number = f'11{index:08d}'
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
        basic_info.form_of_ownership = 'PLC' if heavy else 'Sole Proprietorship'
        basic_info.economic_sector = 'Trade'
        basic_info.subsector_activity = spec['category']
        basic_info.employees_full_time = 4 + index
        basic_info.employees_part_time = 2
        basic_info.employees_seasonal = 1
        basic_info.employees_ft_equivalent = Decimal(str(4 + index)) + Decimal('0.50')
        basic_info.family_members_employed = 1 + (index % 2)
        basic_info.number_business_owners = 3 if heavy else 1
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
        if heavy:
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
        if heavy:
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
        if heavy:
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

    def _ensure_dbe_catalog(self):
        from loans.management.commands.seed_dbe_product_catalog import Command as DbeCatalog
        DbeCatalog().handle()

    def _seed_product_overlay(self, loan, spec, users):
        from loans.models import (
            ConsumerProfile,
            FundFileTag,
            IdeaProfile,
            IjarahRentLine,
            LeaseAssetProfile,
            MurabahaContract,
            PfiInstitutionProfile,
            ProjectCashflowYear,
            ProjectProfile,
            ShariaReview,
        )
        from loans.product_family import (
            FAMILY_CONSUMER,
            FAMILY_EXTERNAL_FUND,
            FAMILY_IDEA_EQUITY,
            FAMILY_IFB_IJARAH,
            FAMILY_IFB_MURABAHA,
            FAMILY_LEASE,
            FAMILY_PROJECT,
            FAMILY_WHOLESALE,
            resolve_product_family,
        )

        family = resolve_product_family(loan)
        officer = spec.get('officer')
        amount = Decimal(spec['amount'])
        if family == FAMILY_PROJECT:
            profile, _ = ProjectProfile.objects.get_or_create(loan_request=loan)
            profile.project_title = spec['applicant']
            profile.sector = ProjectProfile.SECTOR_INDUSTRY
            profile.location = spec['branch'].name
            profile.implementation_months = 24
            profile.grace_months = 6
            profile.total_project_cost = (amount * Decimal('1.35')).quantize(Decimal('0.01'))
            profile.promoter_equity = (amount * Decimal('0.35')).quantize(Decimal('0.01'))
            profile.requested_debt = amount
            profile.purpose_summary = spec['reason']
            profile.current_account_opened = True
            profile.discount_rate_pct = Decimal('12.00')
            profile.npv = (amount * Decimal('0.18')).quantize(Decimal('0.01'))
            profile.irr_pct = Decimal('19.50')
            profile.project_dscr = Decimal('1.45')
            profile.updated_by = officer
            profile.save()
            if not profile.cashflows.exists():
                cost = profile.total_project_cost
                ds = (amount * Decimal('0.18')).quantize(Decimal('0.01'))
                for year, cap, sales_mult, opex_mult in (
                    (1, Decimal('70'), Decimal('0.55'), Decimal('0.28')),
                    (2, Decimal('85'), Decimal('0.70'), Decimal('0.32')),
                    (3, Decimal('100'), Decimal('0.90'), Decimal('0.36')),
                    (4, Decimal('100'), Decimal('0.95'), Decimal('0.37')),
                    (5, Decimal('100'), Decimal('1.00'), Decimal('0.38')),
                ):
                    sales = (cost * sales_mult).quantize(Decimal('0.01'))
                    opex = (cost * opex_mult).quantize(Decimal('0.01'))
                    ProjectCashflowYear.objects.create(
                        profile=profile,
                        year_number=year,
                        revenue=sales,
                        operating_cost=opex,
                        capacity_pct=cap,
                        operating_cf=sales - opex,
                        debt_service=ds,
                    )
        elif family == FAMILY_WHOLESALE:
            profile, _ = PfiInstitutionProfile.objects.get_or_create(loan_request=loan)
            profile.institution_name = spec['applicant']
            profile.kind = PfiInstitutionProfile.KIND_MFI
            profile.license_number = 'NBE-MFI-DEMO-11'
            profile.ownership = 'Share company'
            profile.footprint_regions = 'Tigray'
            profile.branch_count = 18
            profile.has_adequate_mis = True
            profile.capital = Decimal('120000000')
            profile.npl_pct = Decimal('4.20')
            profile.par30_pct = Decimal('8.00')
            profile.par90_pct = Decimal('6.10')
            profile.audited_year = timezone.now().year - 1
            profile.credit_policy_on_file = True
            profile.on_lending_policy_on_file = True
            profile.has_governance = True
            profile.has_esms = True
            profile.facility_amount = amount
            profile.tenor_months = 36
            profile.facility_purpose = PfiInstitutionProfile.PURPOSE_WC
            profile.end_user_rate_ceiling_pct = Decimal('11.00')
            profile.dbe_to_pfi_rate_pct = Decimal('4.50')
            profile.target_women_pct = Decimal('30')
            profile.target_youth_pct = Decimal('20')
            profile.updated_by = officer
            profile.save()
        elif family == FAMILY_IDEA_EQUITY:
            from loans.models import CapTableEntry
            profile, _ = IdeaProfile.objects.get_or_create(loan_request=loan)
            profile.venture_name = spec['applicant']
            profile.founded_year = timezone.now().year - 2
            profile.implements_in_ethiopia = True
            profile.has_startup_label = True
            profile.proposed_dbe_share_pct = Decimal('15.00')
            profile.sector = 'Agri-tech'
            profile.notes = spec['reason']
            profile.updated_by = officer
            profile.save()
            if not profile.cap_table.exists():
                from loans.models import CapTableEntry
                CapTableEntry.objects.create(
                    profile=profile, holder_name=spec['applicant'],
                    role=CapTableEntry.ROLE_FOUNDER, share_pct=Decimal('70.00'),
                )
                CapTableEntry.objects.create(
                    profile=profile, holder_name='DBE (proposed)',
                    role=CapTableEntry.ROLE_DBE, share_pct=Decimal('15.00'),
                )
                CapTableEntry.objects.create(
                    profile=profile, holder_name='Angel investor',
                    role=CapTableEntry.ROLE_OTHER, share_pct=Decimal('15.00'),
                )
        elif family in (FAMILY_LEASE, FAMILY_IFB_IJARAH):
            profile, _ = LeaseAssetProfile.objects.get_or_create(loan_request=loan)
            profile.supplier_name = 'Mekelle Capital Goods PLC'
            profile.supplier_invoice_ref = f'INV-{spec["key"].upper()}'
            profile.is_new_goods = True
            profile.asset_description = spec['reason']
            profile.make_model = 'Isuzu NPR' if family == FAMILY_IFB_IJARAH else 'Haas VF-2'
            profile.serial_number = f'SN-{spec["customer_number"]}'
            profile.asset_price = amount
            profile.price_checked = True
            profile.price_check_note = 'Invoice matched to supplier quote.'
            profile.ancillary_amount = (amount * Decimal('0.08')).quantize(Decimal('0.01'))
            profile.lessee_contribution = (amount * Decimal('0.22')).quantize(Decimal('0.01'))
            profile.commissioning_date = (timezone.now() - timedelta(days=20)).date()
            profile.delivery_date = (timezone.now() - timedelta(days=25)).date()
            profile.commencement_date = (timezone.now() - timedelta(days=18)).date()
            profile.insurance_in_force = True
            profile.insurance_policy = f'NYA-{spec["customer_number"]}'
            profile.insurance_expiry = (timezone.now() + timedelta(days=340)).date()
            profile.location = spec['branch'].name
            profile.gps_lat = Decimal('13.49670000')
            profile.gps_lon = Decimal('39.47530000')
            profile.residual_value = (amount * Decimal('0.10')).quantize(Decimal('0.01'))
            profile.bank_holds_title = True
            profile.asset_status = LeaseAssetProfile.STATUS_ON_LEASE
            profile.rent_term_months = 36
            profile.updated_by = officer
            if family == FAMILY_IFB_IJARAH:
                profile.monthly_rent = (amount / Decimal('36')).quantize(Decimal('0.01'))
                profile.rent_term_months = 36
            profile.notes = spec['reason']
            profile.save()
            if family == FAMILY_IFB_IJARAH and not profile.rent_lines.exists():
                start = timezone.now().date()
                rent = profile.monthly_rent or Decimal('0')
                for period in range(1, 7):
                    IjarahRentLine.objects.create(
                        profile=profile,
                        period_number=period,
                        due_date=start + timedelta(days=30 * period),
                        rent_amount=rent,
                    )
                ShariaReview.objects.get_or_create(
                    loan_request=loan,
                    kind=ShariaReview.KIND_IJARAH,
                    defaults={
                        'status': ShariaReview.STATUS_CLEARED,
                        'note': 'Asset identified, bank owns, rent is usufruct — demo clearance.',
                        'reviewed_at': timezone.now() - timedelta(days=3),
                        'reviewed_by': officer,
                    },
                )
        elif family == FAMILY_IFB_MURABAHA:
            profile, _ = MurabahaContract.objects.get_or_create(loan_request=loan)
            profile.goods_description = 'Cement, rebar and HCB package'
            profile.supplier_name = 'Mekelle Cement Depot'
            profile.supplier_offer_ref = 'OFFER-MUR-4015'
            profile.delivery_status = MurabahaContract.DELIVERY_RECEIVED
            profile.cost_price = amount
            profile.markup_pct = Decimal('12.50')
            profile.scope = MurabahaContract.SCOPE_DOMESTIC
            profile.selling_price = (amount * Decimal('1.125')).quantize(Decimal('0.01'))
            profile.tenor_months = 12
            profile.notes = spec['reason']
            profile.updated_by = officer
            profile.save()
            ShariaReview.objects.get_or_create(
                loan_request=loan,
                kind=ShariaReview.KIND_MURABAHA,
                defaults={
                    'status': ShariaReview.STATUS_CLEARED,
                    'note': 'Cost disclosed; bank purchased before sale — demo clearance.',
                    'reviewed_at': timezone.now() - timedelta(days=2),
                    'reviewed_by': officer,
                },
            )
        elif family == FAMILY_CONSUMER:
            profile, _ = ConsumerProfile.objects.get_or_create(loan_request=loan)
            profile.purpose = ConsumerProfile.PURPOSE_HOUSING
            profile.employer_name = 'Tigray Education Bureau'
            profile.occupation = 'Teacher'
            profile.monthly_salary = Decimal('28000')
            profile.monthly_obligations = Decimal('4500')
            profile.asset_value = Decimal('1850000')
            profile.term_months = 120
            profile.notes = spec['reason']
            profile.updated_by = officer
            profile.save()
        elif family == FAMILY_EXTERNAL_FUND:
            tag, _ = FundFileTag.objects.get_or_create(loan_request=loan)
            tag.women_owned = False
            tag.youth_owned = True
            tag.climate_tagged = True
            tag.fx_window = False
            tag.region = 'Tigray'
            tag.sector = 'Climate-smart agriculture'
            tag.updated_by = officer
            tag.save()

        self._stamp_modality_appraisal(loan, family, officer, amount)

    def _stamp_modality_appraisal(self, loan, family, officer, amount):
        """Persist officer recommendation + scorecard on product-desk demo files."""
        if officer is None:
            return
        from loans.product_family import (
            FAMILY_CONSUMER,
            FAMILY_IDEA_EQUITY,
            FAMILY_IFB_IJARAH,
            FAMILY_IFB_MURABAHA,
            FAMILY_LEASE,
            FAMILY_PROJECT,
            FAMILY_WHOLESALE,
        )

        try:
            if family == FAMILY_PROJECT:
                from loans.project_appraisal import sync_project_decision_to_appraisal
                profile = loan.project_profile
                sync_project_decision_to_appraisal(
                    loan, profile, officer,
                    recommendation='approve',
                    amount_approved=profile.requested_debt or amount,
                    rate_approved=Decimal('14.50'),
                    term_approved_months=(profile.implementation_months or 24) + (profile.grace_months or 0),
                    recommendation_comment='NPV positive, DSCR above 1.25, plant desks ready for demo.',
                    strengths='Strong NPV/IRR; equity plan on file; current account opened.',
                    weaknesses='Monitor construction draw schedule and cost overruns.',
                )
            elif family == FAMILY_WHOLESALE:
                from loans.wholesale_appraisal import sync_wholesale_decision_to_appraisal
                profile = loan.pfi_profile
                if profile.par30_pct is None:
                    profile.par30_pct = Decimal('8.00')
                if profile.end_user_rate_ceiling_pct is None:
                    profile.end_user_rate_ceiling_pct = Decimal('11.00')
                if profile.dbe_to_pfi_rate_pct is None:
                    profile.dbe_to_pfi_rate_pct = Decimal('4.50')
                profile.save()
                sync_wholesale_decision_to_appraisal(
                    loan, profile, officer,
                    recommendation='approve',
                    amount_approved=profile.facility_amount or amount,
                    rate_approved=profile.dbe_to_pfi_rate_pct or Decimal('4.50'),
                    term_approved_months=profile.tenor_months or 36,
                    recommendation_comment='PAR and controls within wholesale band; facility sized to envelope.',
                    strengths='Adequate MIS/ESMS; PAR>90 under 10%; policies on pack.',
                    weaknesses='Watch sub-portfolio PAR on utilization reports.',
                )
            elif family == FAMILY_IDEA_EQUITY:
                from loans.idea_appraisal import sync_idea_decision_to_appraisal
                profile = loan.idea_profile
                sync_idea_decision_to_appraisal(
                    loan, profile, officer,
                    recommendation='approve',
                    amount_approved=amount,
                    rate_approved=profile.proposed_dbe_share_pct or Decimal('15'),
                    term_approved_months=60,
                    recommendation_comment='Start-up within age gate; Ethiopia + label; share sized for DBE.',
                    strengths='Young venture, Ethiopia implementation, start-up label.',
                    weaknesses='Cap table must match proposed share before investment release.',
                )
            elif family in (FAMILY_LEASE, FAMILY_IFB_IJARAH):
                from loans.lease_appraisal import sync_lease_decision_to_appraisal
                profile = loan.lease_asset
                financed = (profile.asset_price or amount) - (profile.lessee_contribution or 0)
                if profile.ancillary_amount:
                    financed += profile.ancillary_amount
                sync_lease_decision_to_appraisal(
                    loan, profile, officer,
                    recommendation='approve',
                    amount_approved=financed if financed > 0 else amount,
                    rate_approved=Decimal('0') if family == FAMILY_IFB_IJARAH else Decimal('12.00'),
                    term_approved_months=profile.rent_term_months or 36,
                    recommendation_comment=(
                        'Ijarah rent and title support approval.'
                        if family == FAMILY_IFB_IJARAH else
                        'New goods, ≥20% contribution, bank holds title.'
                    ),
                    strengths='New capital goods; contribution and insurance on file.',
                    weaknesses='Confirm serial / delivery before first release.',
                )
            elif family == FAMILY_IFB_MURABAHA:
                from loans.murabaha_appraisal import sync_murabaha_decision_to_appraisal
                contract = loan.murabaha
                sync_murabaha_decision_to_appraisal(
                    loan, contract, officer,
                    recommendation='approve',
                    amount_approved=contract.selling_price or amount,
                    rate_approved=contract.markup_pct or Decimal('12.50'),
                    term_approved_months=contract.tenor_months or 12,
                    recommendation_comment='Cost-plus disclosed; goods received; Sharia trail cleared.',
                    strengths='Supplier offer, markup, and delivery status on file.',
                    weaknesses='Keep Sharia trail current for confirm.',
                )
            elif family == FAMILY_CONSUMER:
                from loans.consumer_appraisal import sync_consumer_decision_to_appraisal
                profile = loan.consumer_profile
                sync_consumer_decision_to_appraisal(
                    loan, profile, officer,
                    recommendation='approve',
                    amount_approved=amount,
                    rate_approved=Decimal('12.00'),
                    recommendation_comment='DTI and housing LTV within HRM band for demo salary profile.',
                    strengths='Stable public employer; LTV under housing cap.',
                    weaknesses='Monitor payment burden vs salary.',
                )
        except Exception as exc:
            self.stdout.write(self.style.WARNING(
                f'  Could not stamp {family} appraisal on {loan.loan_request_id}: {exc}'
            ))

    def _attach_demo_document(self, loan, doc_type, officer, now, *, png=None, label=''):
        from django.core.files.base import ContentFile

        existing = loan.application_documents.filter(document_type=doc_type).first()
        if existing and existing.file:
            return existing
        name = (getattr(doc_type, 'name', '') or 'document').lower()
        use_png = png is not None and any(
            k in name for k in ('national id', 'kebele', 'identity', 'director', 'guarantor', 'passport')
        )
        raw = png if use_png else _demo_pdf(label or doc_type.name)
        filename = f'{loan.loan_request_id}_{doc_type.id}.{"png" if use_png else "pdf"}'
        doc = existing or LoanRequestDocument(
            loan_request=loan,
            document_type=doc_type,
            uploaded_by=officer,
        )
        doc.original_filename = filename
        doc.file_size = len(raw)
        doc.auth_status = LoanRequestDocument.AUTH_VERIFIED
        doc.auth_verdict = LoanRequestDocument.VERDICT_AUTHENTIC
        doc.authenticated_by = officer
        doc.authenticated_at = now
        doc.auth_notes = 'Demo seeded required pack.'
        doc.quality_score = 90
        doc.authenticity_score = 88
        doc.automated_checks = {
            'passed': True,
            'auth_status': 'verified',
            'forensics': {'authenticity_score': 88, 'quality': {'score': 90}},
            'identity_match': {'passed': True} if use_png else {},
        }
        doc.file.save(filename, ContentFile(raw), save=False)
        doc.save()
        return doc

    def _seed_required_packs(self, loans, users):
        from loans.document_checklist import checklist_for_category

        now = timezone.now()
        attached = 0
        for loan in loans:
            officer = loan.assigned_loan_officer or users.get('lo1')
            png = _demo_png(loan.loan_request_id)
            items = list(checklist_for_category(loan.category))
            required = [i.document_type for i in items if i.is_required]
            extra_names = [
                'National ID / Kebele ID',
                'TIN Certificate',
                'Director / beneficial owner ID',
                'UBO ownership evidence',
            ]
            by_name = {dt.name: dt for dt in LoanApplicationDocumentType.objects.all()}
            for name in extra_names:
                dt = by_name.get(name)
                if dt and dt not in required:
                    required.append(dt)
            for dt in required:
                self._attach_demo_document(
                    loan, dt, officer, now, png=png, label=dt.name,
                )
                attached += 1
        self.stdout.write(self.style.SUCCESS(f'  Required documents attached: {attached}'))

    def _seed_kyc_identity_packs(self, loans, users):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from loans.kyc_identity import (
            needs_related_parties,
            save_applicant_identity,
            save_applicant_selfie,
            save_related_party,
        )
        from loans.models import KycParty

        filled = 0
        for index, loan in enumerate(loans, start=1):
            tin = ''
            try:
                tin = (loan.basic_info.tin_number or '').strip()
            except Exception:
                tin = f'11{index:08d}'
            fan = f'1234567{index:03d}'
            try:
                party = save_applicant_identity(
                    loan_request=loan,
                    identity_kind=KycParty.KIND_FAYDA,
                    legal_name_en=loan.applicant_name,
                    fan=fan,
                    tin=tin,
                    id_number=f'ID{index:06d}',
                    verify=True,
                )
                png = _demo_png(loan.loan_request_id)
                if not getattr(party.selfie, 'name', ''):
                    save_applicant_selfie(
                        loan_request=loan,
                        uploaded_file=SimpleUploadedFile(
                            'selfie.png', png, content_type='image/png',
                        ),
                    )
                if needs_related_parties(loan):
                    existing = loan.kyc_identity_case.parties.exclude(
                        role=KycParty.ROLE_APPLICANT,
                    ).count()
                    if existing < 2:
                        first = (loan.applicant_name or 'Owner').split()[0]
                        save_related_party(
                            loan_request=loan,
                            role=KycParty.ROLE_UBO,
                            legal_name_en=f'{first} Beneficial One',
                            id_number=f'UBO{index:04d}A',
                            share_percent='60',
                            capacity='Shareholder',
                            verify=False,
                        )
                        save_related_party(
                            loan_request=loan,
                            role=KycParty.ROLE_UBO,
                            legal_name_en=f'{first} Beneficial Two',
                            id_number=f'UBO{index:04d}B',
                            share_percent='40',
                            capacity='Shareholder',
                            verify=False,
                        )
                        save_related_party(
                            loan_request=loan,
                            role=KycParty.ROLE_DIRECTOR,
                            legal_name_en=f'{first} Chair',
                            id_number=f'DIR{index:04d}',
                            capacity='Chair',
                            verify=False,
                        )
            except Exception as exc:
                self.stderr.write(
                    f'  KYC identity failed for {loan.loan_request_id}: {type(exc).__name__}: {exc}'
                )
                raise
            filled += 1
        self.stdout.write(self.style.SUCCESS(f'  KYC identity cases filled: {filled}'))

    def _seed_kyc_desk_packs(self, loans, users):
        from loans.kyc_desk import (
            complete_checklist_payload,
            ensure_intake_screenings,
            kyc_applies,
            set_screening_status,
        )
        from loans.models import CreditDeskScreening

        cleared = 0
        admin = users.get('admin_sys') or users.get('admin')
        crm = users.get('credit_lo') or users.get('lo1')
        eng = users.get('eng1')
        legal = users.get('legal')
        desk_user = {
            CreditDeskScreening.DESK_SCAN: admin,
            CreditDeskScreening.DESK_CRM: crm,
            CreditDeskScreening.DESK_ENGINEERING: eng,
            CreditDeskScreening.DESK_LEGAL: legal,
        }
        for loan in loans:
            if not kyc_applies(loan):
                continue
            rows = ensure_intake_screenings(loan)
            for row in rows:
                if row.status == CreditDeskScreening.STATUS_CLEARED:
                    continue
                user = desk_user.get(row.desk) or crm or admin
                if user is None:
                    continue
                set_screening_status(
                    loan, row.desk, CreditDeskScreening.STATUS_CLEARED, user,
                    'Demo seeded complete KYC pack.',
                    checklist=complete_checklist_payload(row.desk, loan),
                )
                cleared += 1
                if row.desk == CreditDeskScreening.DESK_SCAN:
                    rows = ensure_intake_screenings(loan)
            cleared += 0
        self.stdout.write(self.style.SUCCESS(f'  KYC desk packs cleared: {cleared}'))

    def _seed_portal_applicants(self, geo, categories, collateral_types, users, loans=None):
        from applicant_portal.models import (
            ApplicantAccount, ApplicantPortalSettings, OnlineApplication,
            OnlineApplicationDocument,
        )
        from django.core.files.base import ContentFile
        from loans.document_checklist import checklist_for_category
        from loans.kyc_identity import save_applicant_identity, save_applicant_selfie
        from loans.models import KycParty
        from django.core.files.uploadedfile import SimpleUploadedFile

        now = timezone.now()
        ApplicantPortalSettings.objects.get_or_create(pk=1)
        branch = geo['branches']['Mekelle Main Branch']
        msme = categories.get('MSME Trade')
        wholesale = categories.get('Wholesale / PFI Facility')
        project = categories.get('Project Financing')
        coll = collateral_types.get('Building / House')
        by_cn = {loan.customer_number: loan for loan in (loans or []) if loan.customer_number}

        specs = [
            dict(
                phone='0912111801', name='Portal Abebe Kebede', customer_number='1001',
                actor='person', email='portal.abebe@example.com',
                category=msme, collateral=coll, amount='350000',
                reason='Working capital — Digital Apply demo with required documents',
                fan='123459001', tin='1188000001',
                stage='documents',
            ),
            dict(
                phone='0912111802', name='Tigray Microfinance S.C.', customer_number='PFI-1802',
                actor='institution', email='portal.pfi@example.com',
                institution_name='Tigray Microfinance S.C.', license_number='NBE-MFI-DEMO-11',
                category=wholesale, collateral=coll, amount='25000000',
                reason='Wholesale on-lending — Digital Apply institution demo',
                fan='123459002', tin='1188000002',
                stage='documents',
            ),
            dict(
                phone='0912111803', name='Mekelle Plant Promoter', customer_number='PRM-1803',
                actor='promoter', email='portal.promoter@example.com',
                category=project, collateral=collateral_types.get('Land'), amount='45000000',
                reason='Project financing — Digital Apply promoter demo',
                fan='123459003', tin='1188000003',
                stage='documents',
            ),
            dict(
                phone='0912111804', name='Portal Submitted Applicant', customer_number='4019',
                actor='person', email='portal.submitted@example.com',
                category=msme, collateral=coll, amount='275000',
                reason='Submitted Digital Apply — already in Scan/Admin inbox',
                fan='123459004', tin='1188000004',
                stage='submitted', link_customer='4019',
            ),
            dict(
                phone='0912111805', name='Portal Fee Paid Applicant', customer_number='P-1805',
                actor='person', email='portal.feepaid@example.com',
                category=msme, collateral=coll, amount='310000',
                reason='Fee paid — last step before submit',
                fan='123459005', tin='1188000005',
                stage='payment_paid',
            ),
        ]
        created = 0
        for spec in specs:
            if spec['category'] is None:
                continue
            acct, made = ApplicantAccount.objects.get_or_create(
                phone_number=spec['phone'],
                defaults={
                    'full_name': spec['name'],
                    'customer_number': spec['customer_number'],
                    'email': spec['email'],
                    'actor_kind': spec['actor'],
                    'institution_name': spec.get('institution_name', ''),
                    'license_number': spec.get('license_number', ''),
                    'preferred_branch': branch,
                    'terms_accepted_at': now,
                    'is_active': True,
                },
            )
            acct.set_password(PORTAL_PASSWORD)
            acct.full_name = spec['name']
            acct.customer_number = spec['customer_number']
            acct.actor_kind = spec['actor']
            acct.is_active = True
            acct.terms_accepted_at = acct.terms_accepted_at or now
            acct.save()
            app = OnlineApplication.objects.filter(
                applicant=acct, category=spec['category'],
            ).first()
            if app is None:
                app = OnlineApplication.objects.create(
                    applicant=acct,
                    applicant_name=spec['name'],
                    phone_number=spec['phone'],
                    email=spec['email'],
                    customer_number=spec['customer_number'],
                    category=spec['category'],
                    collateral=spec['collateral'],
                    branch=branch,
                    amount_requested=Decimal(spec['amount']),
                    reason=spec['reason'],
                    status=OnlineApplication.STATUS_DOCUMENTS,
                    payment_status=OnlineApplication.PAY_UNPAID,
                )
            png = _demo_png(f'portal-{spec["phone"]}')
            save_applicant_identity(
                online_application=app,
                identity_kind=KycParty.KIND_FAYDA,
                legal_name_en=spec['name'],
                fan=spec.get('fan') or '123459001',
                tin=spec.get('tin') or '1188000001',
                id_number=f'PID{spec["phone"][-4:]}',
                verify=True,
            )
            types = []
            for item in checklist_for_category(spec['category']):
                if not item.is_required:
                    continue
                types.append(item.document_type)
            extra_names = ['National ID / Kebele ID', 'TIN Certificate']
            by_name = {dt.name: dt for dt in LoanApplicationDocumentType.objects.all()}
            for name in extra_names:
                dt = by_name.get(name)
                if dt and dt not in types:
                    types.append(dt)
            for dt in types:
                if app.documents.filter(document_type=dt).exists():
                    continue
                use_png = any(k in dt.name.lower() for k in ('id', 'kebele', 'identity'))
                raw = png if use_png else _demo_pdf(dt.name)
                filename = f'{dt.id}.{"png" if use_png else "pdf"}'
                doc = OnlineApplicationDocument(
                    application=app,
                    document_type=dt,
                    original_filename=filename,
                    file_size=len(raw),
                    auth_status='verified',
                    quality_score=90,
                    authenticity_score=88,
                    automated_checks={
                        'passed': True,
                        'auth_status': 'verified',
                        'forensics': {'authenticity_score': 88, 'quality': {'score': 90}},
                    },
                )
                doc.file.save(filename, ContentFile(raw), save=False)
                doc.save()
            app.refresh_from_db()
            party = getattr(app, 'kyc_identity_case', None)
            applicant = None
            if party is not None:
                applicant = party.parties.filter(role=KycParty.ROLE_APPLICANT).first()
            if applicant and not getattr(applicant.selfie, 'name', ''):
                save_applicant_selfie(
                    online_application=app,
                    uploaded_file=SimpleUploadedFile(
                        'selfie.png', png, content_type='image/png',
                    ),
                )
            stage = spec.get('stage') or 'documents'
            if stage == 'submitted':
                linked = by_cn.get(spec.get('link_customer'))
                app.status = OnlineApplication.STATUS_SUBMITTED
                app.payment_status = OnlineApplication.PAY_PAID
                app.processing_fee_amount = Decimal('500.00')
                app.payment_paid_at = now - timedelta(days=1)
                app.submitted_at = now - timedelta(hours=12)
                if linked:
                    app.loan_request = linked
                    app.queue_id = linked.loan_request_id
                app.save()
            elif stage == 'payment_paid':
                app.status = OnlineApplication.STATUS_PAYMENT
                app.payment_status = OnlineApplication.PAY_PAID
                app.processing_fee_amount = Decimal('500.00')
                app.payment_paid_at = now - timedelta(hours=2)
                app.save()
            created += 1
        self.stdout.write(self.style.SUCCESS(f'  Digital Apply accounts ready: {created}'))
