"""Optional DBE product catalog on top of the live Credit Intelligence factory.

Does not change existing DECSI categories. Creates product-family categories
and sample funding windows if they are missing.
"""

from django.core.management.base import BaseCommand

from decimal import Decimal

from loans.models import (
    CollateralType,
    FinancingFund,
    LoanApplicationDocumentType,
    LoanCategory,
    LoanCategoryDocumentRequirement,
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
    suggested_appraisal_mode,
)


DBE_CATEGORIES = [
    ('Project Financing', FAMILY_PROJECT),
    ('Lease Financing', FAMILY_LEASE),
    ('Wholesale / PFI Facility', FAMILY_WHOLESALE),
    ('Consumer Financing', FAMILY_CONSUMER),
    ('IFB Murabaha', FAMILY_IFB_MURABAHA),
    ('IFB Ijarah', FAMILY_IFB_IJARAH),
    ('External Fund Window', FAMILY_EXTERNAL_FUND),
    ('Idea / Quasi-Equity', FAMILY_IDEA_EQUITY),
]

DBE_FUNDS = [
    {
        'code': 'OWN',
        'name': 'Own book',
        'kind': FinancingFund.KIND_OWN,
        'source_name': '',
        'notes': 'Default untagged book.',
    },
    {
        'code': 'KFW21826',
        'name': 'EU/KfW MSME recovery',
        'kind': FinancingFund.KIND_DONOR,
        'source_name': 'KfW / EU',
        'notes': 'Tigray, Amhara, Afar — PFI on-lending. DBE→PFI 4.5%, end-user ≤11%.',
        'envelope_amount': None,
        'dbe_to_pfi_rate_pct': Decimal('4.50'),
        'max_end_user_rate_pct': Decimal('11.00'),
        'eligible_regions': 'Tigray, Amhara, Afar',
        'women_min_pct': Decimal('30'),
        'youth_min_pct': Decimal('20'),
        'par90_max_pct': Decimal('10'),
        'agreement_ref': '218.26',
    },
    {
        'code': 'RUFIP3',
        'name': 'RUFIP III',
        'kind': FinancingFund.KIND_DONOR,
        'source_name': 'IFAD / EIB',
        'notes': 'Wholesale to MFIs and RUSACCOs.',
        'women_min_pct': Decimal('30'),
        'youth_min_pct': Decimal('20'),
    },
    {
        'code': 'SMEFP',
        'name': 'SME Finance Project',
        'kind': FinancingFund.KIND_DONOR,
        'source_name': 'World Bank',
        'notes': 'Direct lease to SMEs and wholesale WC / lease to PFIs. PFIs match own funds.',
    },
]


class Command(BaseCommand):
    help = 'Create DBE product families and sample funding windows without changing existing DECSI categories.'

    def handle(self, *args, **options):
        from loans.family_policy import ensure_family_policies, family_requires_collateral
        from loans.product_family import suggested_appraisal_mode

        ensure_family_policies()
        created_cats = 0
        for name, family in DBE_CATEGORIES:
            mode = suggested_appraisal_mode(family) or LoanCategory.MODE_MSME
            need_col = family_requires_collateral(family)
            _, created = LoanCategory.objects.get_or_create(
                name=name,
                defaults={
                    'appraisal_mode': mode,
                    'product_family': family,
                    'requires_collateral': need_col,
                },
            )
            if created:
                created_cats += 1
            else:
                obj = LoanCategory.objects.get(name=name)
                updates = []
                if obj.product_family != family:
                    obj.product_family = family
                    updates.append('product_family')
                if obj.appraisal_mode != mode:
                    obj.appraisal_mode = mode
                    updates.append('appraisal_mode')
                if obj.requires_collateral != need_col:
                    obj.requires_collateral = need_col
                    updates.append('requires_collateral')
                if updates:
                    obj.save(update_fields=updates)
        created_funds = 0
        covenant_keys = (
            'envelope_amount', 'dbe_to_pfi_rate_pct', 'max_end_user_rate_pct',
            'eligible_regions', 'women_min_pct', 'youth_min_pct', 'par90_max_pct',
            'agreement_ref',
        )
        for spec in DBE_FUNDS:
            defaults = {
                'name': spec['name'],
                'kind': spec['kind'],
                'source_name': spec['source_name'],
                'notes': spec['notes'],
                'is_active': True,
            }
            for key in covenant_keys:
                if key in spec:
                    defaults[key] = spec[key]
            obj, created = FinancingFund.objects.get_or_create(
                code=spec['code'],
                defaults=defaults,
            )
            if created:
                created_funds += 1
            elif spec['code'] == 'KFW21826' and not obj.women_min_pct:
                for key in covenant_keys:
                    if key in spec and getattr(obj, key) in (None, ''):
                        setattr(obj, key, spec[key])
                obj.save()
        packs = self._seed_document_packs()
        self._link_funds_and_collateral()
        self.stdout.write(self.style.SUCCESS(
            f'DBE catalog: {created_cats} new categories, {created_funds} new funding windows, '
            f'{packs} document-pack rows. '
            f'Total categories {LoanCategory.objects.count()}, funds {FinancingFund.objects.count()}.'
        ))

    def _seed_document_packs(self):
        packs = {
            FAMILY_PROJECT: [
                ('Feasibility / business plan', True),
                ('Site / land evidence', True),
                ('Promoter equity evidence', True),
                ('Implementation schedule', True),
                ('E&S screening note', True),
            ],
            FAMILY_LEASE: [
                ('Supplier quotation', True),
                ('Asset specification', True),
                ('Lessee contribution proof', True),
                ('Insurance binder (DBE co-beneficiary)', True),
            ],
            FAMILY_IFB_IJARAH: [
                ('Supplier quotation', True),
                ('Asset specification', True),
                ('Lessee contribution proof', True),
                ('Insurance binder (DBE co-beneficiary)', True),
                ('Sharia questionnaire', True),
            ],
            FAMILY_IFB_MURABAHA: [
                ('Goods specification', True),
                ('Supplier offer / invoice', True),
                ('Cost sheet (cost + markup)', True),
                ('Sharia questionnaire', True),
            ],
            FAMILY_WHOLESALE: [
                ('NBE / license certificate', True),
                ('Audited financial statements', True),
                ('ESMS policy', True),
                ('On-lending / credit policy', True),
                ('PAR / NPL report', True),
            ],
            FAMILY_IDEA_EQUITY: [
                ('Start-up label / IP / MoLS evidence', True),
                ('Cap table', True),
                ('Business model note', True),
            ],
            FAMILY_EXTERNAL_FUND: [
                ('Eligibility affidavit', True),
                ('Covenant checklist (women / youth / region)', True),
            ],
            FAMILY_CONSUMER: [
                ('National ID / employment letter', True),
                ('Salary evidence (3 months)', True),
                ('Employer confirmation', True),
            ],
        }
        created = 0
        order = 80
        from collections import Counter
        name_counts = Counter(name for rows in packs.values() for name, _req in rows)
        for family, rows in packs.items():
            for name, required in rows:
                mode = family if name_counts[name] == 1 and family != FAMILY_EXTERNAL_FUND else ''
                dt, made = LoanApplicationDocumentType.objects.get_or_create(
                    name=name,
                    defaults={
                        'order': order,
                        'is_required': required,
                        'for_appraisal_mode': mode,
                    },
                )
                if not made and not dt.for_appraisal_mode and mode:
                    dt.for_appraisal_mode = mode
                    dt.save(update_fields=['for_appraisal_mode'])
                order += 1
                for cat in LoanCategory.objects.filter(product_family=family):
                    _, was = LoanCategoryDocumentRequirement.objects.get_or_create(
                        category=cat,
                        document_type=dt,
                        defaults={'is_required': required, 'order': dt.order},
                    )
                    if was:
                        created += 1
        return created

    def _link_funds_and_collateral(self):
        def cats(*families):
            return list(LoanCategory.objects.filter(product_family__in=families))

        kfw = FinancingFund.objects.filter(code='KFW21826').first()
        rufip = FinancingFund.objects.filter(code='RUFIP3').first()
        smefp = FinancingFund.objects.filter(code='SMEFP').first()
        wholesale = cats(FAMILY_WHOLESALE)
        lease_like = cats(FAMILY_LEASE, FAMILY_IFB_IJARAH)
        fund_window = cats(FAMILY_EXTERNAL_FUND)
        for fund, targets in (
            (kfw, wholesale),
            (rufip, wholesale),
            (smefp, wholesale + lease_like + fund_window),
        ):
            if not fund:
                continue
            for cat in targets:
                cat.allowed_funds.add(fund)

        from loans.collateral_policy import ensure_financed_collateral_types

        ensure_financed_collateral_types()
        by_name = {c.name: c for c in CollateralType.objects.all()}
        project_sec = [
            by_name[n] for n in (
                'Building / House', 'Land', 'Building + Land',
                'Financed machinery / plant (from this loan)',
            ) if n in by_name
        ]
        lease_sec = [
            by_name[n] for n in (
                'Financed machinery / plant (from this loan)',
                'Financed vehicle (from this loan)',
            ) if n in by_name
        ]
        murabaha_sec = [
            by_name[n] for n in (
                'Financed machinery / plant (from this loan)',
                'Machinery / Equipment', 'Other Movable',
            ) if n in by_name
        ]
        for cat in cats(FAMILY_PROJECT):
            if project_sec:
                cat.allowed_collateral.set(project_sec)
        for cat in lease_like:
            if lease_sec:
                cat.allowed_collateral.set(lease_sec)
        for cat in cats(FAMILY_IFB_MURABAHA):
            if murabaha_sec:
                cat.allowed_collateral.set(murabaha_sec)
